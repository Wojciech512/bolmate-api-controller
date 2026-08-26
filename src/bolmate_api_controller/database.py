from bolmate_api_controller.settings import get_settings
from pg_orm import AsyncDatabaseSession
from pg_orm.core.session import Credentials, DatabaseSession


def async_bolmate_connection(**kwargs) -> AsyncDatabaseSession:
    return AsyncDatabaseSession(credentials=_get_credentials(), **kwargs)


def sync_bolmate_connection(**kwargs) -> DatabaseSession:
    return DatabaseSession(credentials=_get_credentials(), **kwargs)


def _get_credentials() -> Credentials:
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
