from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='config.ini')

    # Encryption
    bolmate_encrypt_secret: str
    bolmate_encryption_value: str
    bolmate_encryption_iterations: int

    # Bol OAuth
    bol_oauth_client_id: str
    bol_oauth_client_secret: str
    bol_oauth_insights_client_id: str
    bol_oauth_insights_client_secret: str

    # Bolmate database
    bolmate_database_user: str
    bolmate_database_password: str
    bolmate_database_name: str
    bolmate_database_port: int
    bolmate_database_host: str


@lru_cache
def get_settings(*, env_file: str = 'config.ini') -> Settings:
    env_file = Path.cwd() / env_file
    # noinspection PyArgumentList
    return Settings(_env_file=env_file)
