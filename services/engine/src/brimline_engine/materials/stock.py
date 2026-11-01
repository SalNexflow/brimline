"""The stock ledger (M9): every change is one append-only `stock_movements` row, and
`stock.on_hand_g` (the balance) changes in the same transaction. Call inside the caller's
transaction, next to the change that causes it, so both commit together or not at all."""

from dataclasses import dataclass

import psycopg

from brimline_engine import audit
from brimline_engine.costing.outcome import Attempt, Estimate, assumed_grams
from brimline_engine.materials.grams import job_grams


@dataclass(frozen=True)
class Taken:
    material: str
    grams: int  # what the print used (recorded, or assumed)
    assumed: bool
    missing: int  # how much more the stock record should have held (then a count is due)


def _move(conn: psycopg.Connection, material_id: int, delta: int, now: object) -> tuple[int, int]:
    """Change the balance by `delta`, never below 0. Returns (applied delta, grams missing)."""
    row = conn.execute(
        "SELECT on_hand_g FROM stock WHERE material_id = %s FOR UPDATE", (material_id,)
    ).fetchone()
    on_hand = 0 if row is None else int(row[0])
    applied = max(delta, -on_hand)
    if row is None:
        conn.execute(
            "INSERT INTO stock (material_id, on_hand_g, updated_at) VALUES (%s, %s, %s)",
            (material_id, on_hand + applied, now),
        )
    else:
        conn.execute(
            "UPDATE stock SET on_hand_g = %s, updated_at = %s WHERE material_id = %s",
            (on_hand + applied, now, material_id),
        )
    return applied, applied - delta


def take_for_print(
    conn: psycopg.Connection, task_id: int, actor_user_id: int | None, now: object
) -> Taken | None:
    """A machine task just ended (done or failed): take what it used from stock, once.
    Recorded grams win; otherwise the assumed grams of M10 (the job's grams for a finished
    attempt, the share of its time for a failed one). None when nothing gives a number."""
    row = conn.execute(
        "SELECT t.status, t.material_used_g, extract(epoch FROM t.actual_end - t.actual_start),"
        "       j.id, j.quantity, j.minutes_per_part, j.material_id, mat.code"
        " FROM tasks t JOIN jobs j ON j.id = t.job_id JOIN materials mat ON mat.id = j.material_id"
        " WHERE t.id = %s AND t.kind = 'machine' AND t.status IN ('done', 'failed')"
        " AND NOT EXISTS (SELECT 1 FROM stock_movements m WHERE m.task_id = t.id)",
        (task_id,),
    ).fetchone()
    if row is None:
        return None
    status, recorded, seconds, job_id, qty, minutes, material_id, code = row
    if recorded is not None:
        used, assumed = int(recorded), False
    else:
        per_part = job_grams(conn, [job_id])[job_id].per_part
        if per_part is None or minutes is None:
            return None
        attempt = Attempt(
            machine_seconds=int(seconds or 0), grams_used=None, failed=status == "failed"
        )
        used, assumed = assumed_grams(Estimate(qty, per_part, minutes), attempt), True
    applied, missing = _move(conn, material_id, -used, now)
    conn.execute(
        "INSERT INTO stock_movements (material_id, grams_delta, reason, task_id, missing_g,"
        " grams_assumed, recorded_by, created_at) VALUES (%s, %s, 'print', %s, %s, %s, %s, %s)",
        (material_id, applied, task_id, missing, assumed, actor_user_id, now),
    )
    return Taken(code, used, assumed, missing)


def receive(
    conn: psycopg.Connection, po_id: int, actor_user_id: int, now: object, key: str
) -> None:
    """A recorded purchase order arrived: its grams go into stock. The caller checked that it
    is open and that the actor may do this."""
    row = conn.execute(
        "SELECT material_id, grams, po_number FROM purchase_orders WHERE id = %s", (po_id,)
    ).fetchone()
    assert row is not None
    material_id, grams, number = row
    conn.execute(
        "UPDATE purchase_orders SET status = 'received', received_at = %s WHERE id = %s",
        (now, po_id),
    )
    applied, _ = _move(conn, material_id, grams, now)
    conn.execute(
        "INSERT INTO stock_movements (material_id, grams_delta, reason, purchase_order_id,"
        " recorded_by, created_at) VALUES (%s, %s, 'delivery', %s, %s, %s)",
        (material_id, applied, po_id, actor_user_id, now),
    )
    audit.record(
        conn,
        actor_user_id=actor_user_id,
        action="purchase_order.receive",
        entity_type="purchase_order",
        entity_id=number,
        before={"status": "open"},
        after={"status": "received", "grams": grams},
        idempotency_key=key,
    )
