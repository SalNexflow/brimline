import dataclasses

import psycopg
import pytest

from brimline_engine.db.migrate import (
    MigrationError,
    drop_database,
    ensure_database,
    load_migrations,
    migrate,
    with_database,
)
from brimline_engine.db.seed import seed
from brimline_engine.settings import Settings


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


def test_0015_takes_plans_made_before_it_as_up_to_date_with_orders(settings: Settings) -> None:
    """DEFECT_LOG #112: on a database with purchase-order history (the hosted demo), migration 0015
    must not make every existing plan say "Plan again". Two order entries exist before it runs, so
    the plan that exists then has seen two."""
    assert settings.database_owner_url
    name = "brimline_test_0015"
    owner, app = (
        with_database(u, name) for u in (settings.database_owner_url, settings.database_url)
    )
    drop_database(settings.database_owner_url, name)
    ensure_database(settings.database_owner_url, name)
    try:
        before = [m for m in load_migrations() if m.version < "0015"]
        migrate(owner, app, before)
        seed(owner)
        with psycopg.connect(owner) as conn:
            planner = conn.execute("SELECT id FROM users WHERE code = 'U-PLANNER'").fetchone()
            assert planner is not None
            run = conn.execute(
                "INSERT INTO planning_runs (requested_by) VALUES (%s) RETURNING id", planner
            ).fetchone()
            assert run is not None
            conn.execute(
                "INSERT INTO schedules (run_id, anchor, document, fingerprint, solver_info,"
                " created_by) VALUES (%s, now(), '{}', 'fp', '{}', %s)",
                (run[0], planner[0]),
            )
            for action in ("purchase_order.record", "purchase_order.receive", "quote.approve"):
                conn.execute(
                    "INSERT INTO audit_log (action, entity_type, entity_id)"
                    " VALUES (%s, 'purchase_order', 'PO-0001')",
                    (action,),
                )
        assert migrate(owner, app) == ["0015_plan_order_changes"]
        with psycopg.connect(owner) as conn:
            assert conn.execute("SELECT order_changes_seen FROM schedules").fetchall() == [(2,)]
    finally:
        drop_database(settings.database_owner_url, name)
