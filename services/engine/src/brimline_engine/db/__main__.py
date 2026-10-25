"""Database commands, run as the owner role.

    uv run python -m brimline_engine.db migrate [--database NAME]
    uv run python -m brimline_engine.db seed    [--database NAME]
    uv run python -m brimline_engine.db reset   [--database NAME]   # drop, create, migrate, seed

--database targets another database on the same server (tests use brimline_test and brimline_e2e).
"""

import argparse
import sys

from brimline_engine.db.migrate import (
    database_name,
    drop_database,
    ensure_database,
    migrate,
    with_database,
)
from brimline_engine.db.seed import seed
from brimline_engine.settings import get_settings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m brimline_engine.db")
    parser.add_argument("command", choices=["migrate", "seed", "reset"])
    parser.add_argument("--database", help="database name (default: the one in DATABASE_URL)")
    args = parser.parse_args(argv)

    settings = get_settings()
    if not settings.database_owner_url:
        print("DATABASE_OWNER_URL is not set (see .env.example)", file=sys.stderr)
        return 1
    dbname = args.database or database_name(settings.database_url)
    owner_url = with_database(settings.database_owner_url, dbname)
    app_url = with_database(settings.database_url, dbname)

    if args.command == "reset":
        drop_database(settings.database_owner_url, dbname)
    if args.command in ("reset", "migrate"):
        ensure_database(settings.database_owner_url, dbname)
        applied = migrate(owner_url, app_url)
        print(f"{dbname}: applied {len(applied)} migration(s) {applied}")
    if args.command in ("reset", "seed"):
        seed(owner_url)
        print(f"{dbname}: seeded from config/shop.toml")
    return 0


if __name__ == "__main__":
    sys.exit(main())
