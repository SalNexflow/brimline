import dataclasses

import psycopg
import pytest

from brimline_engine.db.migrate import MigrationError, load_migrations, migrate


def test_all_migrations_are_recorded(owner_conn: psycopg.Connection) -> None:
    versions = [
        r[0] for r in owner_conn.execute("SELECT version FROM schema_migrations ORDER BY 1")
    ]
    assert versions == [m.version for m in load_migrations()]
    assert versions[:6] == [
        "0001_core",
        "0002_audit_log",
        "0003_idempotency_keys",
        "0004_tighten_app_role",
        "0005_price_rules",
        "0006_quotes",
    ]


def test_running_again_applies_nothing(test_database: str, owner_url: str, app_url: str) -> None:
    assert migrate(owner_url, app_url) == []


def test_an_applied_migration_that_was_edited_is_refused(
    test_database: str, owner_url: str, app_url: str
) -> None:
    edited = [
        dataclasses.replace(m, checksum="0" * 64) if i == 0 else m
        for i, m in enumerate(load_migrations())
    ]
    with pytest.raises(MigrationError, match="changed after it was applied"):
        migrate(owner_url, app_url, edited)


def test_runtime_url_must_use_the_app_role(test_database: str, owner_url: str) -> None:
    # Pointing the engine at the owner role would silently bypass every grant.
    with pytest.raises(MigrationError, match="must connect as brimline_app"):
        migrate(owner_url, owner_url)


def test_app_role_is_not_privileged(owner_conn: psycopg.Connection) -> None:
    row = owner_conn.execute(
        "SELECT rolsuper, rolcreatedb, rolcreaterole, rolbypassrls"
        " FROM pg_roles WHERE rolname = 'brimline_app'"
    ).fetchone()
    assert row == (False, False, False, False)


# --- D34, closed in M11: the owner is not a superuser, and the app role cannot reach around ----


def test_the_owner_is_not_a_superuser_and_cannot_switch_triggers_off(owner_url: str) -> None:
    with psycopg.connect(owner_url) as conn:
        row = conn.execute("SELECT rolsuper FROM pg_roles WHERE rolname = current_user").fetchone()
        assert row is not None and row[0] is False
        # A superuser could skip every trigger (the audit log's append-only guard included).
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("SET session_replication_role = replica")


def test_the_app_role_cannot_take_advisory_locks(app_url: str) -> None:
    with psycopg.connect(app_url) as conn, pytest.raises(psycopg.errors.InsufficientPrivilege):
        conn.execute("SELECT pg_advisory_lock(42)")


def test_the_app_role_cannot_connect_to_the_maintenance_database(app_url: str) -> None:
    from brimline_engine.db.migrate import with_database

    with pytest.raises(psycopg.OperationalError, match="permission denied"):
        psycopg.connect(with_database(app_url, "postgres")).close()
