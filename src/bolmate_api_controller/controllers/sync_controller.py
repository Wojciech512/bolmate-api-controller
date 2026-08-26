from random import random
from threading import Semaphore
from time import sleep
from typing import Literal

import requests
from dvrd_pydate import PyDateTime

from bolmate_api_controller.aio_bol_ratelimit import acquire_global_sync, bearer_limiter
from bolmate_api_controller.bolmate_encryption import enc_data
from bolmate_api_controller.constants import MAX_REQUEST_ATTEMPTS, SELECT_QUERY, UPDATE_QUERY, DEACTIVATE_QUERY, \
    ACCOUNT_DEACTIVATED
from bolmate_api_controller.database import sync_bolmate_connection
from bolmate_api_controller.exceptions import APIKeyDeactivated
from bolmate_api_controller.logger import auth_exception, auth_error
from bolmate_api_controller.request_helper import client_credentials_from_oauth_type, build_oauth_request_data, \
    build_legacy_request_data
from bolmate_api_controller.response import SyncResponse
from bolmate_api_controller.types import ID, APIKey

# Allow up to semaphore API key fetches at a time per process.
# This protects the production database from overflowing in sessions
_semaphore = Semaphore(5)


def get_api_key_sync(*, api_key_id: ID) -> tuple[APIKey | None, bool]:
    with _semaphore, sync_bolmate_connection(isolate=True, auto_commit=False) as database:
        database.execute(SELECT_QUERY, {'api_key_id': api_key_id})
        if not (key_dict := database.first()):
            return None, False

        api_key = APIKey.from_dict(data=key_dict)
        if not api_key.bearer_is_expired:
            return api_key, True

        try:
            if api_key.use_oauth:
                api_key, success = _request_oauth_api_key(api_key=api_key)
            else:
                api_key, success = _request_legacy_api_key(api_key=api_key)
            if success:
                database.execute(UPDATE_QUERY,
                                 {'api_bearer': enc_data.encrypt(plaintext=api_key.api_bearer),
                                  'bearer_expires_at': api_key.bearer_expires_at,
                                  'api_key_id': api_key.api_key_id})
        except APIKeyDeactivated:
            success = False
            database.execute(DEACTIVATE_QUERY, {'api_key_id': api_key.api_key_id})
        return api_key, success


def _request_oauth_api_key(*, api_key: APIKey) -> tuple[APIKey, bool]:
    now = PyDateTime()
    refresh_token = api_key.refresh_token
    refresh_expires_at = api_key.refresh_token_expires_at
    if not refresh_token or not refresh_expires_at or refresh_expires_at <= now:
        return api_key, False

    credentials = client_credentials_from_oauth_type(oauth_type=api_key.oauth_type)
    request_data = build_oauth_request_data(refresh_token=refresh_token, credentials=credentials)
    for _ in range(MAX_REQUEST_ATTEMPTS):
        try:
            # Burst protection
            acquire_global_sync('oauth_bearer')
            with (bearer_limiter.ratelimit('oauth_bearer', delay=True),
                  requests.request(method='POST', url=request_data.url, data=request_data.data,
                                   headers=request_data.headers, timeout=request_data.timeout) as response):
                sync_response = SyncResponse.build(response=response)
            api_key, success, keep_trying = _process_auth_response(api_key=api_key, sync_response=sync_response,
                                                                   token_type='OAuth')
            if success:
                return api_key, True
            elif not keep_trying:
                break
        except APIKeyDeactivated:
            raise
        except Exception:
            auth_exception(f'Exception in refreshing OAuth token, API key ID: {api_key.api_key_id}')
            sleep(1 + random())
    return api_key, False


def _request_legacy_api_key(*, api_key: APIKey) -> tuple[APIKey, bool]:
    if not api_key.key or not api_key.secret:
        return api_key, False
    request_data = build_legacy_request_data(key=api_key.key, secret=api_key.secret)
    for _ in range(MAX_REQUEST_ATTEMPTS):
        try:
            # Burst protection
            acquire_global_sync('legacy_bearer')
            with (bearer_limiter.ratelimit('legacy_bearer', delay=True),
                  requests.request(method='POST', url=request_data.url, headers=request_data.headers,
                                   timeout=request_data.timeout) as response):
                sync_response = SyncResponse.build(response=response)
            api_key, success, keep_trying = _process_auth_response(api_key=api_key, sync_response=sync_response,
                                                                   token_type='legacy')
            if success:
                return api_key, True
            elif not keep_trying:
                break
        except APIKeyDeactivated:
            raise
        except Exception:
            auth_exception(f'Exception in refreshing legacy token, API key ID: {api_key.api_key_id}')
            sleep(1 + random())
    return api_key, False


def _process_auth_response(*, api_key: APIKey, sync_response: SyncResponse,
                           token_type: Literal['OAuth', 'legacy']) -> tuple[APIKey, bool, bool]:
    if sync_response.status == 200:
        response_data = sync_response.json()
        expires_in = int(response_data.get('expires_in') or 0)
        expires_at = PyDateTime().add_seconds(expires_in)
        api_key.api_bearer = response_data.get('access_token')
        api_key.bearer_expires_at = expires_at
        return api_key, True, False
    elif sync_response.status == 429:
        # 429 is global, so it's fine to keep the lock whilst waiting. Calls for other API keys would just
        # result in the same 429 response
        retry_after: str | None = sync_response.headers.get('Retry-After')
        if retry_after:
            # Retry-After is in seconds
            sleep(int(retry_after))
            return api_key, False, True
        else:
            return api_key, False, False
    elif sync_response.status >= 500:
        sleep(1 + random())
        return api_key, False, True
    else:
        err = sync_response.text()
        auth_error(f'Error in refreshing {token_type} token: {err}, API key ID: {api_key.api_key_id}')
        if ACCOUNT_DEACTIVATED in err.casefold():
            # Confirmed to no longer be active without possibility to revive.
            raise APIKeyDeactivated()
        # No reason to retry on non-recoverable errors
        return api_key, False, False
