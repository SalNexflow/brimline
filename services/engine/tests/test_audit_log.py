"""The audit log is append-only, and only migrations (the owner role) can change the schema.

Each statement below is one way someone might try to rewrite history. All of them must fail.
"""

from typing import LiteralString

import psycopg
import pytest

INSERT_ROW = (
    "INSERT INTO audit_log (action, entity_type, entity_id, after)"
    " VALUES ('test.action', 'test', 'T-1', '{}') RETURNING id"
)


def _insert_row(conn: psycopg.Connection) -> int:
    row = conn.execute(INSERT_ROW).fetchone()
    assert row is not None
    return int(row[0])


def test_app_role_can_append_and_read(app_conn: psycopg.Connection) -> None:
    row_id = _insert_row(app_conn)
    found = app_conn.execute("SELECT entity_id FROM audit_log WHERE id = %s", (row_id,)).fetchone()
    assert found == ("T-1",)


# --- Guard 1: triggers block changes for everyone, even the owner -------------------------------


def test_owner_cannot_update_audit_rows(owner_conn: psycopg.Connection) -> None:
    row_id = _insert_row(owner_conn)
    with pytest.raises(psycopg.errors.RaiseException, match="append-only: UPDATE"):
        owner_conn.execute("UPDATE audit_log SET action = 'forged' WHERE id = %s", (row_id,))


def test_owner_cannot_delete_audit_rows(owner_conn: psycopg.Connection) -> None:
    row_id = _insert_row(owner_conn)
    with pytest.raises(psycopg.errors.RaiseException, match="append-only: DELETE"):
        owner_conn.execute("DELETE FROM audit_log WHERE id = %s", (row_id,))


def test_owner_cannot_truncate_audit_log(owner_conn: psycopg.Connection) -> None:
    with pytest.raises(psycopg.errors.RaiseException, match="append-only: TRUNCATE"):
        owner_conn.execute("TRUNCATE audit_log")


# --- Guard 2: the app role has no privilege to change rows, triggers, or schema -----------------

APP_ROLE_FORBIDDEN: list[LiteralString] = [
    "UPDATE audit_log SET action = 'forged'",
    "DELETE FROM audit_log",
    "TRUNCATE audit_log",
    "ALTER TABLE audit_log DISABLE TRIGGER audit_log_no_update_or_delete",
    "ALTER TABLE audit_log DISABLE TRIGGER ALL",
    "DROP TRIGGER audit_log_no_update_or_delete ON audit_log",
    "DROP TABLE audit_log",
    "CREATE OR REPLACE FUNCTION audit_log_reject_change() RETURNS trigger"
    " LANGUAGE plpgsql AS $$ BEGIN RETURN NEW; END; $$",
    # Schema changes are migrations only:
    "CREATE TABLE sneaky (id int)",
    "ALTER TABLE orders ADD COLUMN discount_percent int",
    "DROP TABLE orders",
    "CREATE SCHEMA sneaky",
    "DELETE FROM orders",
    "UPDATE customers SET name = 'renamed'",
    "DELETE FROM schema_migrations",
    # Found by the M1 adversarial review (DEFECT_LOG #6): forging the id or the timestamp.
    "INSERT INTO audit_log (id, action, entity_type, entity_id) OVERRIDING SYSTEM VALUE"
    " VALUES (999999, 'forged', 'order', 'BL-0001')",
    "INSERT INTO audit_log (at, action, entity_type, entity_id)"
    " VALUES ('2000-01-01', 'forged', 'order', 'BL-0001')",
    # A temp table named audit_log would shadow the real one on this connection.
    "CREATE TEMP TABLE audit_log (id int)",
    # The app may change only users.session_version, never a role.
    "UPDATE users SET role = 'staff'",
]


@pytest.mark.parametrize("statement", APP_ROLE_FORBIDDEN)
def test_app_role_is_refused(app_conn: psycopg.Connection, statement: LiteralString) -> None:
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        app_conn.execute(statement)


OWNER_ALLOWED: list[LiteralString] = [
    "CREATE TABLE sneaky (id int)",
    "ALTER TABLE orders ADD COLUMN discount_percent int",
    "CREATE SCHEMA sneaky",
    "ALTER TABLE audit_log DISABLE TRIGGER ALL",
    "INSERT INTO audit_log (id, at, action, entity_type, entity_id) OVERRIDING SYSTEM VALUE"
    " VALUES (999999, '2000-01-01', 'owner', 'order', 'BL-0001')",
    "CREATE TEMP TABLE audit_log (id int)",
    "UPDATE users SET role = role",
]


def test_app_role_cannot_use_temp_tables_and_public_cannot_connect(
    owner_conn: psycopg.Connection,
) -> None:
    # grantee 0 is PUBLIC: after 0004 it holds no privileges on the database at all.
    public_privileges = owner_conn.execute(
        "SELECT a.privilege_type FROM pg_database d, aclexplode(d.datacl) a"
        " WHERE d.datname = current_database() AND a.grantee = 0"
    ).fetchall()
    assert public_privileges == []
    row = owner_conn.execute(
        "SELECT has_database_privilege('brimline_app', current_database(), 'CONNECT'),"
        "       has_database_privilege('brimline_app', current_database(), 'TEMPORARY')"
    ).fetchone()
    assert row == (True, False)


def test_app_role_searches_public_before_temp(app_conn: psycopg.Connection) -> None:
    row = app_conn.execute("SHOW search_path").fetchone()
    assert row == ("public, pg_temp",)


def test_app_role_may_bump_its_session_version(app_conn: psycopg.Connection) -> None:
    app_conn.execute(
        "UPDATE users SET session_version = session_version + 1 WHERE code = 'U-STAFF'"
    )


@pytest.mark.parametrize("statement", OWNER_ALLOWED)
def test_the_same_statements_work_for_the_owner(
    owner_conn: psycopg.Connection, statement: LiteralString
) -> None:
    # Control group: proves the app role is refused for lack of privilege, not because the
    # statement is broken. (Rolled back after the test, like every fixture transaction.)
    owner_conn.execute(statement)


def test_triggers_are_still_enabled(owner_conn: psycopg.Connection) -> None:
    rows = owner_conn.execute(
        "SELECT tgname, tgenabled FROM pg_trigger"
        " WHERE tgrelid = 'audit_log'::regclass AND NOT tgisinternal ORDER BY tgname"
    ).fetchall()
    # 'O' = enabled in normal (origin) mode.
    assert rows == [("audit_log_no_truncate", "O"), ("audit_log_no_update_or_delete", "O")]
