"""Load config/shop.toml into a freshly migrated database, as the owner role.

The seed is not an app write, so it writes no audit rows. It refuses a database that already
has data: use `reset` to start over. Inserting in file order into an empty database, with fixed
timestamps, makes every seed produce identical rows (ids and order numbers included).
"""

import psycopg

from brimline_engine.costing.config import costing_config
from brimline_engine.costing.scenario import history
from brimline_engine.costing.store import insert_synthetic
from brimline_engine.shop_config import ShopConfig, load_shop_config


class SeedError(RuntimeError):
    pass


def _ids(conn: psycopg.Connection, table: str) -> dict[str, int]:
    query = {
        "customers": "SELECT code, id FROM customers",
        "users": "SELECT code, id FROM users",
        "materials": "SELECT code, id FROM materials",
        "machines": "SELECT code, id FROM machines",
    }[table]
    return {code: id_ for code, id_ in conn.execute(query)}


def seed(owner_url: str, config: ShopConfig | None = None) -> None:
    cfg = load_shop_config() if config is None else config
    at = cfg.seed_time
    with psycopg.connect(owner_url) as conn, conn.transaction():
        if conn.execute("SELECT 1 FROM customers LIMIT 1").fetchone():
            raise SeedError("database already has data; run `reset` instead of seeding twice")

        for c in cfg.customers:
            conn.execute(
                "INSERT INTO customers (code, name, email, created_at) VALUES (%s, %s, %s, %s)",
                (c.code, c.name, c.email, at),
            )
        customer_ids = _ids(conn, "customers")

        for u in cfg.users:
            conn.execute(
                "INSERT INTO users (code, display_name, role, customer_id, created_at)"
                " VALUES (%s, %s, %s, %s, %s)",
                (u.code, u.display_name, u.role, customer_ids.get(u.customer or ""), at),
            )
        user_ids = _ids(conn, "users")

        for m in cfg.materials:
            conn.execute(
                "INSERT INTO materials (code, name, process, color, created_at)"
                " VALUES (%s, %s, %s, %s, %s)",
                (m.code, m.name, m.process, m.color, at),
            )
        material_ids = _ids(conn, "materials")

        for mc in cfg.machines:
            x, y, z = mc.build_mm
            conn.execute(
                "INSERT INTO machines (code, name, process, build_x_mm, build_y_mm, build_z_mm, created_at)"
                " VALUES (%s, %s, %s, %s, %s, %s, %s)",
                (mc.code, mc.name, mc.process, x, y, z, at),
            )
        machine_ids = _ids(conn, "machines")
        for mc in cfg.machines:
            for code in mc.materials:
                conn.execute(
                    "INSERT INTO machine_materials (machine_id, material_id) VALUES (%s, %s)",
                    (machine_ids[mc.code], material_ids[code]),
                )

        for code, grams in cfg.stock.items():
            conn.execute(
                "INSERT INTO stock (material_id, on_hand_g, updated_at) VALUES (%s, %s, %s)",
                (material_ids[code], grams, at),
            )

        for s in cfg.shifts:
            for weekday in s.weekdays:
                conn.execute(
                    "INSERT INTO shifts (weekday, starts_at, ends_at) VALUES (%s, %s, %s)",
                    (weekday, s.starts, s.ends),
                )

        seed_price_rules(conn, cfg, material_ids)

        for o in cfg.orders:
            row = conn.execute(
                "INSERT INTO orders (customer_id, due_date, rush, notes, created_by, created_at, updated_at)"
                " VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id",
                (
                    customer_ids[o.customer],
                    o.due_date,
                    o.rush,
                    o.notes,
                    user_ids[o.created_by],
                    at,
                    at,
                ),
            ).fetchone()
            assert row is not None
            for line_no, line in enumerate(o.lines, start=1):
                size = line.part_mm or (None, None, None)
                conn.execute(
                    "INSERT INTO jobs (order_id, line_no, part_name, quantity, material_id,"
                    " minutes_per_part, part_x_mm, part_y_mm, part_z_mm, post_processing, created_at)"
                    " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                    (
                        row[0],
                        line_no,
                        line.part,
                        line.quantity,
                        material_ids[line.material],
                        line.minutes_per_part,
                        *size,
                        list(line.post),
                        at,
                    ),
                )

        # Finished jobs from before the seed, for the quoted-versus-actual report (M10). Synthetic,
        # and labelled so on the Reports page; one material is truly under-quoted.
        sc = costing_config().scenario
        insert_synthetic(
            conn,
            history(
                cfg,
                sc,
                seed=sc.demo_seed,
                jobs_per_type=sc.demo_jobs_per_material,
                biased=sc.demo_biased_material,
                bias=sc.demo_bias,
                end=at,
            ),
        )


def seed_price_rules(
    conn: psycopg.Connection, cfg: ShopConfig, material_ids: dict[str, int]
) -> None:
    """The first dated version of the price rules (created_by null: it comes from config)."""
    pr = cfg.price_rules
    row = conn.execute(
        "INSERT INTO price_rule_sets (effective_from, setup_cents, rush_multiplier_percent, note, created_at)"
        " VALUES (%s, %s, %s, %s, %s) RETURNING id",
        (
            pr.effective_from,
            pr.setup_cents,
            pr.rush_multiplier_percent,
            "Seeded from config/shop.toml",
            cfg.seed_time,
        ),
    ).fetchone()
    assert row is not None
    rule_set_id = row[0]
    for code, cents in pr.material_cents_per_gram.items():
        conn.execute(
            "INSERT INTO price_material_rates (rule_set_id, material_id, cents_per_gram) VALUES (%s, %s, %s)",
            (rule_set_id, material_ids[code], cents),
        )
    for process, cents in pr.machine_minute_cents.items():
        conn.execute(
            "INSERT INTO price_machine_rates (rule_set_id, process, cents_per_minute) VALUES (%s, %s, %s)",
            (rule_set_id, process, cents),
        )
    for kind, cents in pr.post_process_cents_per_part.items():
        conn.execute(
            "INSERT INTO price_post_process_rates (rule_set_id, kind, cents_per_part) VALUES (%s, %s, %s)",
            (rule_set_id, kind, cents),
        )


def seed_price_rules_if_missing(owner_url: str) -> bool:
    """For a database seeded before price rules existed (M1): add the configured version once."""
    cfg = load_shop_config()
    with psycopg.connect(owner_url) as conn, conn.transaction():
        if conn.execute("SELECT 1 FROM price_rule_sets LIMIT 1").fetchone():
            return False
        seed_price_rules(conn, cfg, _ids(conn, "materials"))
        return True
