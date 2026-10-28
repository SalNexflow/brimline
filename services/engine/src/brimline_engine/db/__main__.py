"""Database commands, run as the owner role.

    uv run python -m brimline_engine.db migrate [--database NAME]
    uv run python -m brimline_engine.db seed    [--database NAME]
    uv run python -m brimline_engine.db reset   [--database NAME]   # drop, create, migrate, seed
    uv run python -m brimline_engine.db setup   [--database NAME]   # migrate; seed only if empty
    uv run python -m brimline_engine.db reset --demo                 # the hosted demo (M11)

reset --demo empties the database in place (no maintenance database needed, so it works on a
hosted Postgres without a superuser), moves the seed to this week, and approves a first plan.

--database targets another database on the same server (tests use brimline_test and brimline_e2e).
"""

import argparse
import sys
from datetime import UTC, datetime

import psycopg

from brimline_engine.dates import shop_today
from brimline_engine.db.demo_seed import plan_and_approve, shifted
from brimline_engine.db.migrate import (
    database_name,
    drop_database,
    ensure_database,
    migrate,
    with_database,
)
from brimline_engine.db.seed import SeedError, seed, seed_price_rules_if_missing
from brimline_engine.settings import get_settings
from brimline_engine.shop_config import load_shop_config


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m brimline_engine.db")
    parser.add_argument("command", choices=["migrate", "seed", "reset", "setup"])
    parser.add_argument("--database", help="database name (default: the one in DATABASE_URL)")
    parser.add_argument("--demo", action="store_true", help="reset: in place, this week, planned")
    args = parser.parse_args(argv)

    settings = get_settings()
    if not settings.database_owner_url:
        print("DATABASE_OWNER_URL is not set (see .env.example)", file=sys.stderr)
        return 1
    dbname = args.database or database_name(settings.database_url)
    owner_url = with_database(settings.database_owner_url, dbname)
    app_url = with_database(settings.database_url, dbname)

    if args.demo:
        if args.command != "reset":
            print("--demo goes with reset", file=sys.stderr)
            return 1
        return demo_reset(owner_url, app_url, dbname)
    if args.command == "reset":
        drop_database(settings.database_owner_url, dbname)
    if args.command in ("reset", "migrate", "setup"):
        ensure_database(settings.database_owner_url, dbname)
        applied = migrate(owner_url, app_url)
        print(f"{dbname}: applied {len(applied)} migration(s) {applied}")
    if args.command in ("reset", "seed"):
        seed(owner_url)
        print(f"{dbname}: seeded from config/shop.toml")
    if args.command == "setup":
        # Safe to re-run: seeds only an empty database and leaves existing data alone.
        try:
            seed(owner_url)
            print(f"{dbname}: seeded from config/shop.toml")
        except SeedError:
            print(f"{dbname}: already has data, not seeded (use reset to start over)")
            if seed_price_rules_if_missing(owner_url):
                print(f"{dbname}: added the price rules from config/shop.toml")
    return 0


def demo_reset(owner_url: str, app_url: str, dbname: str) -> int:
    """Empty the schema in place, migrate, seed this week, approve a first plan."""
    with psycopg.connect(owner_url, autocommit=True) as conn:
        conn.execute("DROP SCHEMA IF EXISTS public CASCADE")
        conn.execute("CREATE SCHEMA public")
    applied = migrate(owner_url, app_url)
    shop = load_shop_config()
    now = datetime.now(UTC)
    today = shop_today(now, shop.shop.time_zone)
    seed(owner_url, shifted(shop, today))
    schedule_id = plan_and_approve(app_url, now, shop.shop.time_zone)
    print(
        f"{dbname}: demo reset: {len(applied)} migration(s), seed moved to the week of {today},"
        f" plan {schedule_id} approved"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
