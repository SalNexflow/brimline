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
]


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
