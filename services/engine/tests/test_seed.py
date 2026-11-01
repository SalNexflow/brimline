import psycopg
import pytest
from pydantic import ValidationError

from brimline_engine.db.migrate import drop_database, ensure_database, migrate, with_database
from brimline_engine.db.seed import SeedError, seed
from brimline_engine.settings import Settings
from brimline_engine.shop_config import load_shop_config

SEED_DB = "brimline_test_seed"
TABLES = [
    "customers",
    "users",
    "materials",
    "machines",
    "machine_materials",
    "stock",
    "shifts",
    "orders",
    "jobs",
    "price_material_rates",
    "price_machine_rates",
    "price_post_process_rates",
]


def _fresh_seed_and_dump(settings: Settings) -> dict[str, list[tuple[object, ...]]]:
    assert settings.database_owner_url
    owner = with_database(settings.database_owner_url, SEED_DB)
    drop_database(settings.database_owner_url, SEED_DB)
    ensure_database(settings.database_owner_url, SEED_DB)
    migrate(owner, with_database(settings.database_url, SEED_DB))
    seed(owner)
    with psycopg.connect(owner) as conn:
        dump = {}
        for table in TABLES:
            query = f"SELECT * FROM {table} ORDER BY 1, 2"
            dump[table] = conn.execute(query.encode()).fetchall()
        # created_txid differs on every run by design, so compare every other column.
        dump["price_rule_sets"] = conn.execute(
            "SELECT id, effective_from, setup_cents, rush_multiplier_percent, note, created_by,"
            " created_at FROM price_rule_sets ORDER BY id"
        ).fetchall()
        return dump


def test_seeding_twice_produces_identical_data(settings: Settings) -> None:
    first = _fresh_seed_and_dump(settings)
    second = _fresh_seed_and_dump(settings)
    assert first == second
    assert len(first["orders"]) == 8  # sanity: the comparison is not between two empty dumps


def test_seed_numbers_orders_from_bl_0001(owner_conn: psycopg.Connection) -> None:
    numbers = [
        r[0] for r in owner_conn.execute("SELECT order_number FROM orders ORDER BY id LIMIT 3")
    ]
    assert numbers == ["BL-0001", "BL-0002", "BL-0003"]


def test_seeding_a_database_that_has_data_is_refused(test_database: str, owner_url: str) -> None:
    with pytest.raises(SeedError, match="already has data"):
        seed(owner_url)


def test_every_role_has_a_demo_user(owner_conn: psycopg.Connection) -> None:
    roles = {r[0] for r in owner_conn.execute("SELECT role FROM users")}
    assert roles == {"staff", "planner", "operator", "customer"}


def test_config_with_a_typo_in_a_reference_is_rejected() -> None:
    raw = load_shop_config().model_dump()
    raw["orders"][0]["lines"][0]["material"] = "PLA-BLAK"
    with pytest.raises(ValidationError, match="unknown material PLA-BLAK"):
        type(load_shop_config()).model_validate(raw)


def test_config_rejects_a_material_on_the_wrong_kind_of_machine() -> None:
    raw = load_shop_config().model_dump()
    raw["machines"][0]["materials"].append("RESIN-GREY")  # FDM-1 cannot print resin
    with pytest.raises(ValidationError, match="RESIN-GREY is unknown or not a fdm material"):
        type(load_shop_config()).model_validate(raw)


def test_a_database_seeded_before_m9_gets_its_grams_and_plans_fully(settings: Settings) -> None:
    """DEFECT_LOG #94: the hosted demo migrated to 0013 with its seeded jobs' grams empty, so
    every seeded job would have been "cannot plan". `db setup` now fills them from the config."""
    from datetime import UTC, datetime

    from brimline_engine.db.seed import backfill_seed_grams
    from brimline_engine.planning.inputs import build_inputs
    from brimline_engine.scheduling.config import scheduler_config

    assert settings.database_owner_url
    name = "brimline_test_backfill"
    owner = with_database(settings.database_owner_url, name)
    app = with_database(settings.database_url, name)
    drop_database(settings.database_owner_url, name)
    ensure_database(settings.database_owner_url, name)
    try:
        migrate(owner, app)
        seed(owner)
        with psycopg.connect(owner) as conn:
            conn.execute("UPDATE jobs SET grams_per_part = NULL")  # as seeded before M9
            # A number a person entered later is kept.
            conn.execute(
                "UPDATE jobs SET grams_per_part = 99 FROM orders o WHERE o.id = jobs.order_id"
                " AND o.order_number = 'BL-0001' AND jobs.line_no = 1"
            )
        # 13 seeded lines carry grams in config/shop.toml; one already has a person's 99.
        assert backfill_seed_grams(owner) == 12
        assert backfill_seed_grams(owner) == 0
        with psycopg.connect(owner) as conn:
            rows: dict[str, int] = dict(
                conn.execute(
                    "SELECT o.order_number || '-' || j.line_no, j.grams_per_part FROM jobs j"
                    " JOIN orders o ON o.id = j.order_id"
                ).fetchall()
            )
        assert rows["BL-0001-1"] == 99 and rows["BL-0005-2"] == 55 and rows["BL-0007-2"] == 3
        with psycopg.connect(app) as conn:
            inputs = build_inputs(
                conn, datetime(2026, 10, 26, 9, 0, tzinfo=UTC), scheduler_config(), "Europe/Berlin"
            )
        assert [u["missing"] for u in inputs.unplannable] == [["part size"]]
    finally:
        drop_database(settings.database_owner_url, name)
