import aiohttp

from bolmate_api_controller.settings import get_settings
from bolmate_api_controller.types import OAuthClientCredentials, OAuthType, AuthRequestData


def client_credentials_from_oauth_type(*, oauth_type: OAuthType) -> OAuthClientCredentials:
    settings = get_settings()
    if oauth_type == 'INVOICES':
        return OAuthClientCredentials(
            client_id=settings.bol_oauth_client_id,
            client_secret=settings.bol_oauth_client_secret,
            oauth_type=oauth_type,
        )
    elif oauth_type == 'DATA_INSIGHTS':
        return OAuthClientCredentials(
            client_id=settings.bol_oauth_insights_client_id,
            client_secret=settings.bol_oauth_insights_client_secret,
            oauth_type=oauth_type,
        )
    else:
        raise ValueError(f'Invalid oauth type: {oauth_type}')


def build_oauth_request_data(*, refresh_token: str, credentials: OAuthClientCredentials) -> AuthRequestData:
    return AuthRequestData(
        url='https://login.bol.com/token',
        data={
            'refresh_token': refresh_token,
            'grant_type': 'refresh_token',
            'client_id': credentials.client_id,
            'client_secret': credentials.client_secret,
        },
        headers={'Content-Type': 'application/x-www-form-urlencoded'},
        timeout=30
    )


def build_legacy_request_data(*, key: str, secret: str) -> AuthRequestData:
    basic_auth = aiohttp.encode_basic_auth(login=key, password=secret)
    return AuthRequestData(
        url='https://login.bol.com/token?grant_type=client_credentials',
        data={},
        headers={'Accept': 'application/json', 'Authorization': basic_auth},
        timeout=30
    )
