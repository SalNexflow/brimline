"""A small migration runner for the plain SQL files in db/migrations/.

Rules it enforces:
- Files run in name order, each in its own transaction, as the owner role.
- An applied migration may never change: its checksum is stored and compared on every run.
  To change the schema, add a new file.
- The runtime app role (brimline_app) is created here, because roles live outside any database.
"""

import hashlib
from dataclasses import dataclass
from pathlib import Path

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from brimline_engine.settings import REPO_ROOT

APP_ROLE = "brimline_app"
MIGRATIONS_DIR = REPO_ROOT / "db" / "migrations"
_LOCK_ID = 7_310_001  # arbitrary constant: one migration runner at a time per database


class MigrationError(RuntimeError):
    pass


@dataclass(frozen=True)
class Migration:
    version: str
    sql: str
    checksum: str


def with_database(url: str, dbname: str) -> str:
    """The same server and credentials, pointed at another database."""
    return make_conninfo(url, dbname=dbname)


def database_name(url: str) -> str:
    return str(conninfo_to_dict(url)["dbname"])


def load_migrations(directory: Path = MIGRATIONS_DIR) -> list[Migration]:
    migrations = []
    for path in sorted(directory.glob("*.sql")):
        # Normalise line endings so a Windows checkout hashes the same as Linux CI.
        text = path.read_text(encoding="utf-8").replace("\r\n", "\n")
        checksum = hashlib.sha256(text.encode()).hexdigest()
        migrations.append(Migration(version=path.stem, sql=text, checksum=checksum))
    return migrations


def ensure_database(owner_url: str, dbname: str) -> None:
    with psycopg.connect(with_database(owner_url, "postgres"), autocommit=True) as conn:
        exists = conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (dbname,)).fetchone()
        if not exists:
            conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(dbname)))


def drop_database(owner_url: str, dbname: str) -> None:
    with psycopg.connect(with_database(owner_url, "postgres"), autocommit=True) as conn:
        conn.execute(
            sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(dbname))
        )


def ensure_app_role(conn: psycopg.Connection, app_url: str) -> None:
    params = conninfo_to_dict(app_url)
    if params.get("user") != APP_ROLE:
        raise MigrationError(f"DATABASE_URL must connect as {APP_ROLE}, not {params.get('user')!r}")
    password = sql.Literal(str(params.get("password", "")))
    exists = conn.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (APP_ROLE,)).fetchone()
    verb = sql.SQL("ALTER ROLE") if exists else sql.SQL("CREATE ROLE")
    # Explicitly not a superuser and unable to create databases or roles.
    conn.execute(
        sql.SQL("{} {} WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD {}").format(
            verb, sql.Identifier(APP_ROLE), password
        )
    )


def migrate(owner_url: str, app_url: str, migrations: list[Migration] | None = None) -> list[str]:
    """Apply pending migrations to the owner URL's database. Returns the versions applied."""
    migrations = load_migrations() if migrations is None else migrations
    applied_now: list[str] = []
    with psycopg.connect(owner_url, autocommit=True) as conn:
        conn.execute("SELECT pg_advisory_lock(%s)", (_LOCK_ID,))
        try:
            ensure_app_role(conn, app_url)
            conn.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations ("
                " version text PRIMARY KEY, checksum text NOT NULL,"
                " applied_at timestamptz NOT NULL DEFAULT now())"
            )
            rows = conn.execute("SELECT version, checksum FROM schema_migrations").fetchall()
            applied = {version: checksum for version, checksum in rows}

            unknown = set(applied) - {m.version for m in migrations}
            if unknown:
                raise MigrationError(
                    f"database has migrations missing from disk: {sorted(unknown)}"
                )

            for m in migrations:
                if m.version in applied:
                    if applied[m.version] != m.checksum:
                        raise MigrationError(
                            f"{m.version} changed after it was applied; add a new migration instead"
                        )
                    continue
                with conn.transaction():
                    conn.execute(m.sql.encode())
                    conn.execute(
                        "INSERT INTO schema_migrations (version, checksum) VALUES (%s, %s)",
                        (m.version, m.checksum),
                    )
                applied_now.append(m.version)
        finally:
            conn.execute("SELECT pg_advisory_unlock(%s)", (_LOCK_ID,))
    return applied_now
