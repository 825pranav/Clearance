from app import config, db


def test_config_loads():
    assert config.DATABASE_URL
    assert config.GITLAB_DRY_RUN is True


def test_database_ping():
    assert db.ping()
