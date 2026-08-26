from typing import Final

SELECT_QUERY = ("SELECT id, api_bearer, bearer_expires_at, oauth_refresh_token, oauth_refresh_token_expires_at, oauth_type, use_oauth, key, secret "
                "FROM api_key WHERE id = %(api_key_id)s FOR UPDATE;")
UPDATE_QUERY = "UPDATE api_key SET api_bearer = %(api_bearer)s, bearer_expires_at = %(bearer_expires_at)s WHERE id = %(api_key_id)s;"

BEARER_REFRESH_MARGIN: Final[int] = 60
MAX_REQUEST_ATTEMPTS: Final[int] = 5
