"""Shared fixtures. Database tests use their own database (brimline_test), rebuilt once per run,
so your development data is never touched."""

from collections.abc import Iterator
from datetime import UTC, datetime

import psycopg
import pytest
from fastapi.testclient import TestClient

from brimline_engine.api.deps import utc_now
from brimline_engine.db.migrate import drop_database, ensure_database, migrate, with_database
from brimline_engine.db.seed import seed
from brimline_engine.main import app
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


# The engine's clock in API tests, so date rules are deterministic. Shop time (Berlin) is 10:00.
FIXED_NOW = datetime(2026, 10, 26, 9, 0, tzinfo=UTC)


@pytest.fixture(scope="session")
def client(test_database: str, app_url: str) -> Iterator[TestClient]:
    """The real app, pointed at the test database, with demo login on and a fixed clock."""
    patch = pytest.MonkeyPatch()
    patch.setenv("DATABASE_URL", app_url)
    patch.setenv("DEMO_LOGIN", "true")
    get_settings.cache_clear()
    app.dependency_overrides[utc_now] = lambda: FIXED_NOW
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    patch.undo()
    get_settings.cache_clear()


def login(client: TestClient, user_code: str) -> dict[str, str]:
    """Headers for a signed-in demo user."""
    response = client.post("/auth/demo-login", json={"user_code": user_code})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['token']}"}


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
