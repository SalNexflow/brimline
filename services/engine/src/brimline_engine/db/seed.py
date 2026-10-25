"""Load config/shop.toml into a freshly migrated database, as the owner role.

The seed is not an app write, so it writes no audit rows. It refuses a database that already
has data: use `reset` to start over. Inserting in file order into an empty database, with fixed
timestamps, makes every seed produce identical rows (ids and order numbers included).
"""

import psycopg

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
                conn.execute(
                    "INSERT INTO jobs (order_id, line_no, part_name, quantity, material_id, created_at)"
                    " VALUES (%s, %s, %s, %s, %s, %s)",
                    (row[0], line_no, line.part, line.quantity, material_ids[line.material], at),
                )
