"""Shared fixtures. Database tests use their own database (brimline_test), rebuilt once per run,
so your development data is never touched."""

from collections.abc import Iterator

import psycopg
import pytest

from brimline_engine.db.migrate import drop_database, ensure_database, migrate, with_database
from brimline_engine.db.seed import seed
from brimline_engine.settings import Settings, get_settings

TEST_DB = "brimline_test"


@pytest.fixture(scope="session")
def settings() -> Settings:
    s = get_settings()
    assert s.database_owner_url, "DATABASE_OWNER_URL must be set for database tests"
    return s


@pytest.fixture(scope="session")
def owner_url(settings: Settings) -> str:
    assert settings.database_owner_url
    return with_database(settings.database_owner_url, TEST_DB)


@pytest.fixture(scope="session")
def app_url(settings: Settings) -> str:
    return with_database(settings.database_url, TEST_DB)


@pytest.fixture(scope="session")
def test_database(settings: Settings, owner_url: str, app_url: str) -> str:
    """A freshly migrated and seeded test database. Returns its name."""
    assert settings.database_owner_url
    drop_database(settings.database_owner_url, TEST_DB)
    ensure_database(settings.database_owner_url, TEST_DB)
    migrate(owner_url, app_url)
    seed(owner_url)
    return TEST_DB


@pytest.fixture
def owner_conn(test_database: str, owner_url: str) -> Iterator[psycopg.Connection]:
    """Owner connection inside a transaction that is rolled back after the test."""
    with psycopg.connect(owner_url) as conn:
        yield conn
        conn.rollback()


@pytest.fixture
def app_conn(test_database: str, app_url: str) -> Iterator[psycopg.Connection]:
    """App-role connection inside a transaction that is rolled back after the test."""
    with psycopg.connect(app_url) as conn:
        yield conn
        conn.rollback()
