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
