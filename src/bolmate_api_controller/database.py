from urllib.parse import unquote, urlsplit

from bolmate_api_controller.settings import get_settings
from pg_orm import AsyncDatabaseSession
from pg_orm.core.session import Credentials, DatabaseSession

_configured_credentials: Credentials | None = None


def configure_database(*, dsn: str | None = None, credentials: Credentials | None = None) -> None:
    global _configured_credentials
    if dsn is not None and credentials is not None:
        raise ValueError('Pass either dsn or credentials, not both')
    if dsn is not None:
        credentials = credentials_from_dsn(dsn)
    _configured_credentials = credentials


def credentials_from_dsn(dsn: str) -> Credentials:
    parts = urlsplit(dsn)
    if not parts.hostname or not parts.path.lstrip('/'):
        raise ValueError('DSN must carry at least a host and a database name')
    return Credentials(
        username=unquote(parts.username or ''),
        password=unquote(parts.password or ''),
        host=parts.hostname,
        port=parts.port or 5432,
        database_name=parts.path.lstrip('/'),
    )


def async_bolmate_connection(**kwargs) -> AsyncDatabaseSession:
    return AsyncDatabaseSession(credentials=_get_credentials(), **kwargs)


def sync_bolmate_connection(**kwargs) -> DatabaseSession:
    return DatabaseSession(credentials=_get_credentials(), **kwargs)


def _get_credentials() -> Credentials:
    if _configured_credentials is not None:
        return _configured_credentials
    settings = get_settings()
    db_user = settings.bolmate_database_user
    db_password = settings.bolmate_database_password
    db_host = settings.bolmate_database_host
    db_port = settings.bolmate_database_port
    db_name = settings.bolmate_database_name
    return Credentials(
        username=db_user,
        password=db_password,
        host=db_host,
        port=db_port,
        database_name=db_name
    )
