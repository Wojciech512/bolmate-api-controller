from asyncio import Semaphore, sleep
from random import random
from typing import Literal

import aiohttp
from aiohttp import ClientTimeout
from dvrd_pydate import PyDateTime

from bolmate_api_controller.aio_bol_ratelimit import acquire_global_async, bearer_limiter
from bolmate_api_controller.response import AsyncResponse
from bolmate_api_controller.bolmate_encryption import enc_data
from bolmate_api_controller.constants import MAX_REQUEST_ATTEMPTS, SELECT_QUERY, UPDATE_QUERY
from bolmate_api_controller.database import async_bolmate_connection
from bolmate_api_controller.logger import auth_exception, auth_error
from bolmate_api_controller.request_helper import client_credentials_from_oauth_type, build_oauth_request_data, \
    build_legacy_request_data
from bolmate_api_controller.types import ID, APIKey

# Allow up to semaphore API key fetches at a time per process.
# This protects the production database from overflowing in sessions
_semaphore = Semaphore(5)


async def get_api_key_async(*, api_key_id: ID) -> tuple[APIKey | None, bool]:
    async with _semaphore, async_bolmate_connection(isolate=True, auto_commit=False) as database:
        await database.execute(SELECT_QUERY, {'api_key_id': api_key_id})
        if not (key_dict := await database.first()):
            return None, False

        api_key = APIKey.from_dict(data=key_dict)
        if not api_key.bearer_is_expired:
            return api_key, True

        if api_key.use_oauth:
            api_key, success = await _request_oauth_api_key(api_key=api_key)
        else:
            api_key, success = await _request_legacy_api_key(api_key=api_key)
        if success:
            await database.execute(UPDATE_QUERY,
                                   {'api_bearer': enc_data.encrypt(plaintext=api_key.api_bearer),
                                    'bearer_expires_at': api_key.bearer_expires_at,
                                    'api_key_id': api_key.api_key_id})
        return api_key, success


async def _request_oauth_api_key(*, api_key: APIKey) -> tuple[APIKey, bool]:
    now = PyDateTime()
    refresh_token = api_key.refresh_token
    refresh_expires_at = api_key.refresh_token_expires_at
    if not refresh_token or not refresh_expires_at or refresh_expires_at <= now:
        return api_key, False

    credentials = client_credentials_from_oauth_type(oauth_type=api_key.oauth_type)
    request_data = build_oauth_request_data(refresh_token=refresh_token, credentials=credentials)
    try:
        for _ in range(MAX_REQUEST_ATTEMPTS):
            # Burst protection
            await acquire_global_async('oauth_bearer')
            async with (bearer_limiter.ratelimit('oauth_bearer', delay=True),
                        aiohttp.request(method='POST', url=request_data.url, data=request_data.data,
                                        headers=request_data.headers,
                                        timeout=ClientTimeout(total=request_data.timeout)) as response):
                aio_response = await AsyncResponse.build(response=response)
            api_key, success, keep_trying = await _process_auth_response(api_key=api_key, aio_response=aio_response,
                                                                         token_type='OAuth')
            if success:
                return api_key, True
            elif not keep_trying:
                break
    except Exception:
        auth_exception(f'Exception in refreshing OAuth token, API key ID: {api_key.api_key_id}')
    return api_key, False


async def _request_legacy_api_key(*, api_key: APIKey) -> tuple[APIKey, bool]:
    if not api_key.key or not api_key.secret:
        return api_key, False
    request_data = build_legacy_request_data(key=api_key.key, secret=api_key.secret)
    try:
        for _ in range(MAX_REQUEST_ATTEMPTS):
            # Burst protection
            await acquire_global_async('legacy_bearer')
            async with (bearer_limiter.ratelimit('legacy_bearer', delay=True),
                        aiohttp.request(method='POST', url=request_data.url, headers=request_data.headers,
                                        timeout=ClientTimeout(total=request_data.timeout)) as response):
                aio_response = await AsyncResponse.build(response=response)
            api_key, success, keep_trying = await _process_auth_response(api_key=api_key, aio_response=aio_response,
                                                                         token_type='legacy')
            if success:
                return api_key, True
            elif not keep_trying:
                break
    except Exception:
        auth_exception(f'Exception in refreshing legacy token, API key ID: {api_key.api_key_id}')
    return api_key, False


async def _process_auth_response(*, api_key: APIKey, aio_response: AsyncResponse,
                                 token_type: Literal['OAuth', 'legacy']) -> tuple[APIKey, bool, bool]:
    if aio_response.status == 200:
        response_data = aio_response.json()
        expires_in = int(response_data.get('expires_in') or 0)
        expires_at = PyDateTime().add_seconds(expires_in)
        api_key.api_bearer = response_data.get('access_token')
        api_key.bearer_expires_at = expires_at
        return api_key, True, False
    elif aio_response.status == 429:
        # 429 is global, so it's fine to keep the lock whilst waiting. Calls for other API keys would just
        # result in the same 429 response
        retry_after: str | None = aio_response.headers.get('Retry-After')
        if retry_after:
            # Retry-After is in seconds
            await sleep(int(retry_after))
            return api_key, False, True
        else:
            return api_key, False, False
    elif aio_response.status >= 500:
        await sleep(1 + random())
        return api_key, False, True
    else:
        err = aio_response.text()
        auth_error(f'Error in refreshing {token_type} token: {err}, API key ID: {api_key.api_key_id}')
        # No reason to retry on non-recoverable errors
        return api_key, False, False
