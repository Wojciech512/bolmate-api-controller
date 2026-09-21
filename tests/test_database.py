import pytest

from bolmate_api_controller import configure_database, credentials_from_dsn
from bolmate_api_controller import database


@pytest.fixture(autouse=True)
def reset_configuration():
    yield
    configure_database()


def test_credentials_from_dsn_parses_every_part():
    credentials = credentials_from_dsn('postgresql://mcp_user:s3cret@db.internal:6432/bolmate')
    assert credentials.username == 'mcp_user'
    assert credentials.password == 's3cret'
    assert credentials.host == 'db.internal'
    assert credentials.port == 6432
    assert credentials.database_name == 'bolmate'


def test_credentials_from_dsn_percent_decodes_and_defaults_the_port():
    credentials = credentials_from_dsn('postgresql://ro%40mcp:p%40ss%2Fword@localhost/bolmate')
    assert credentials.username == 'ro@mcp'
    assert credentials.password == 'p@ss/word'
    assert credentials.port == 5432


def test_credentials_from_dsn_rejects_incomplete_dsns():
    with pytest.raises(ValueError):
        credentials_from_dsn('postgresql://user:pw@localhost')
    with pytest.raises(ValueError):
        credentials_from_dsn('not-a-dsn')


def test_configure_database_takes_precedence_over_settings():
    configure_database(dsn='postgresql://explicit:pw@configured-host:5433/configured_db')
    credentials = database._get_credentials()
    assert credentials.host == 'configured-host'
    assert credentials.database_name == 'configured_db'


def test_configure_database_reverts_to_settings(monkeypatch):
    class FakeSettings:
        bolmate_database_user = 'ini-user'
        bolmate_database_password = 'ini-password'
        bolmate_database_host = 'ini-host'
        bolmate_database_port = 5432
        bolmate_database_name = 'ini-db'

    monkeypatch.setattr(database, 'get_settings', lambda: FakeSettings())
    configure_database(dsn='postgresql://explicit:pw@configured-host:5433/configured_db')
    configure_database()
    credentials = database._get_credentials()
    assert credentials.host == 'ini-host'
    assert credentials.database_name == 'ini-db'


def test_configure_database_rejects_both_arguments():
    with pytest.raises(ValueError):
        configure_database(dsn='postgresql://u:p@h/db',
                           credentials=credentials_from_dsn('postgresql://u:p@h/db'))
