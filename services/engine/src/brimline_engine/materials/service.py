"""The Materials page (M9): stock, purchase orders, and the shortages of the current plans.

Read: stock.read (staff, planner). Recording a purchase order a person has placed, and marking
one received: purchase.record (staff). Both writes are idempotent and audit-logged. Brimline
never orders anything; suggestions are computed on every read and never stored.
"""

from datetime import datetime
from typing import Any

import psycopg
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from brimline_engine import audit, idempotency
from brimline_engine.materials import stock
from brimline_engine.materials.config import PurchasingConfig
from brimline_engine.materials.shortage import MaterialShortage, for_document
from brimline_engine.permissions import Actor, can
from brimline_engine.scheduling.config import Durations
from brimline_engine.text import SafeText


class NotFoundError(Exception):
    pass


class ForbiddenError(Exception):
    pass


class ConflictError(Exception):
    pass


class InvalidError(Exception):
    pass


class StockRow(BaseModel):
    material: str
    name: str
    on_hand_g: int
    on_order_g: int  # open purchase orders still to come (an overdue one is not counted)
    supplier: str | None
    lead_time_days: int | None


class PurchaseOrderOut(BaseModel):
    number: str
    material: str
    grams: int
    supplier: str
    expected_at: datetime
    status: str
    received_at: datetime | None
    overdue: bool  # open, and its expected time has passed


class Movement(BaseModel):
    material: str
    grams: int
    reason: str
    what: str  # the purchase order, or the task's job
    assumed: bool
    missing_g: int
    at: datetime


class PlanShortages(BaseModel):
    schedule_id: int
    status: str
    made_at: datetime
    material_known: bool  # False for a plan made before stock was part of planning
    # A purchase order was recorded, received or cancelled after this plan was made: its
    # shortages and suggestions may be out of date until someone plans again (review of M9).
    orders_changed: bool
    shortages: list[MaterialShortage]


class MaterialsOut(BaseModel):
    stock: list[StockRow]
    purchase_orders: list[PurchaseOrderOut]
    plans: list[PlanShortages]  # the approved plan, then the newest draft (if any)
    movements: list[Movement]  # the latest changes to stock
    checked: str  # the date config/purchasing.toml was last reviewed
    time_zone: str  # the shop's; times are UTC, shown in this zone


class PurchaseOrderIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    material_code: SafeText = Field(max_length=40)
    grams: int = Field(ge=1, le=1_000_000)
    supplier: SafeText = Field(min_length=1, max_length=100)
    expected_at: AwareDatetime


def order_changes(conn: psycopg.Connection) -> int:
    """How many purchase orders have been recorded, received or cancelled: the audit log is
    append-only, so this only grows. A plan keeps the count it saw; a higher count now means
    orders changed after it, whatever the clocks say (DEFECT_LOG #111)."""
    row = conn.execute(
        "SELECT count(*) FROM audit_log WHERE action IN"
        " ('purchase_order.record', 'purchase_order.receive', 'purchase_order.cancel')"
    ).fetchone()
    return 0 if row is None else int(row[0])


def overview(
    conn: psycopg.Connection,
    actor: Actor,
    now: datetime,
    tz: str,
    durations: Durations,
    purchasing: PurchasingConfig,
) -> MaterialsOut:
    if not can(actor, "stock.read"):
        raise ForbiddenError("stock.read")
    rows = conn.execute(
        "SELECT m.code, m.name, coalesce(s.on_hand_g, 0),"
        "       coalesce((SELECT sum(p.grams) FROM purchase_orders p"
        "                 WHERE p.material_id = m.id AND p.status = 'open'"
        "                 AND p.expected_at >= %s), 0)"
        " FROM materials m LEFT JOIN stock s ON s.material_id = m.id ORDER BY m.code",
        (now,),
    ).fetchall()
    stock_rows = []
    for code, name, on_hand, on_order in rows:
        supply = purchasing.materials.get(code)
        stock_rows.append(
            StockRow(
                material=code,
                name=name,
                on_hand_g=int(on_hand),
                on_order_g=int(on_order),
                supplier=None if supply is None else supply.supplier,
                lead_time_days=None if supply is None else supply.lead_time_days,
            )
        )
    orders = [
        PurchaseOrderOut(
            number=r[0],
            material=r[1],
            grams=r[2],
            supplier=r[3],
            expected_at=r[4],
            status=r[5],
            received_at=r[6],
            overdue=r[5] == "open" and r[4] < now,
        )
        for r in conn.execute(
            "SELECT p.po_number, m.code, p.grams, p.supplier, p.expected_at, p.status,"
            "       p.received_at"
            " FROM purchase_orders p JOIN materials m ON m.id = p.material_id"
            " ORDER BY (p.status = 'open') DESC, p.expected_at DESC, p.id DESC LIMIT 30"
        ).fetchall()
    ]
    changes = order_changes(conn)
    plans = []
    for sid, status, anchor, doc, made, seen in conn.execute(
        "(SELECT id, status, anchor, document, created_at, order_changes_seen FROM schedules"
        "  WHERE status = 'approved')"
        " UNION ALL (SELECT id, status, anchor, document, created_at, order_changes_seen"
        "  FROM schedules WHERE status = 'draft' ORDER BY id DESC LIMIT 1)"
    ).fetchall():
        plans.append(
            PlanShortages(
                schedule_id=sid,
                status=status,
                made_at=made,
                material_known="stock" in doc["instance"],
                orders_changed=changes > seen,
                shortages=for_document(doc, anchor, tz, durations, purchasing, now),
            )
        )
    movements = [
        Movement(
            material=r[0],
            grams=r[1],
            reason=r[2],
            what=r[3] or "",
            assumed=r[4],
            missing_g=r[5],
            at=r[6],
        )
        for r in conn.execute(
            "SELECT m.code, sm.grams_delta, sm.reason,"
            "       coalesce(p.po_number, o.order_number || '-' || j.line_no || ' print'),"
            "       sm.grams_assumed, sm.missing_g, sm.created_at"
            " FROM stock_movements sm JOIN materials m ON m.id = sm.material_id"
            " LEFT JOIN purchase_orders p ON p.id = sm.purchase_order_id"
            " LEFT JOIN tasks t ON t.id = sm.task_id LEFT JOIN jobs j ON j.id = t.job_id"
            " LEFT JOIN orders o ON o.id = j.order_id"
            " ORDER BY sm.id DESC LIMIT 20"
        ).fetchall()
    ]
    return MaterialsOut(
        stock=stock_rows,
        purchase_orders=orders,
        plans=plans,
        movements=movements,
        checked=purchasing.checked.isoformat(),
        time_zone=tz,
    )


def record_purchase_order(
    conn: psycopg.Connection, actor: Actor, body: PurchaseOrderIn, key: str, now: datetime
) -> tuple[idempotency.StoredResponse, bool]:
    """Record an order a person has placed with a supplier, so planning counts its delivery."""
    if not can(actor, "purchase.record"):
        raise ForbiddenError("purchase.record")
    endpoint = "POST /purchase-orders"
    with conn.transaction():
        stored = idempotency.claim(
            conn,
            user_id=actor.user_id,
            endpoint=endpoint,
            key=key,
            req_hash=idempotency.request_hash(body.model_dump(mode="json")),
        )
        if stored is not None:
            return stored, True
        material = conn.execute(
            "SELECT id FROM materials WHERE code = %s", (body.material_code,)
        ).fetchone()
        if material is None:
            raise InvalidError(f"unknown material {body.material_code}")
        if body.expected_at < now:
            raise InvalidError("the expected delivery time is in the past")
        row = conn.execute(
            "INSERT INTO purchase_orders (material_id, grams, supplier, expected_at, recorded_by,"
            " created_at) VALUES (%s, %s, %s, %s, %s, %s) RETURNING id, po_number",
            (material[0], body.grams, body.supplier, body.expected_at, actor.user_id, now),
        ).fetchone()
        assert row is not None
        after: dict[str, Any] = body.model_dump(mode="json")
        audit.record(
            conn,
            actor_user_id=actor.user_id,
            action="purchase_order.record",
            entity_type="purchase_order",
            entity_id=row[1],
            before=None,
            after=after,
            idempotency_key=key,
        )
        response = idempotency.StoredResponse(201, {"number": row[1], "status": "open"})
        idempotency.store(
            conn, user_id=actor.user_id, endpoint=endpoint, key=key, response=response
        )
        return response, False


def receive_purchase_order(
    conn: psycopg.Connection, actor: Actor, number: str, key: str, now: datetime
) -> tuple[idempotency.StoredResponse, bool]:
    """The delivery arrived: its grams go into stock."""
    if not can(actor, "purchase.record"):
        raise ForbiddenError("purchase.record")
    endpoint = f"POST /purchase-orders/{number}/receive"
    with conn.transaction():
        stored = idempotency.claim(
            conn, user_id=actor.user_id, endpoint=endpoint, key=key, req_hash="receive"
        )
        if stored is not None:
            return stored, True
        row = conn.execute(
            "SELECT id, status FROM purchase_orders WHERE po_number = %s FOR UPDATE", (number,)
        ).fetchone()
        if row is None:
            raise NotFoundError(number)
        if row[1] != "open":
            raise ConflictError(f"{number} is {row[1]}")
        stock.receive(conn, int(row[0]), actor.user_id, now, key)
        response = idempotency.StoredResponse(200, {"number": number, "status": "received"})
        idempotency.store(
            conn, user_id=actor.user_id, endpoint=endpoint, key=key, response=response
        )
        return response, False


def cancel_purchase_order(
    conn: psycopg.Connection, actor: Actor, number: str, key: str, now: datetime
) -> tuple[idempotency.StoredResponse, bool]:
    """The supplier will not deliver (or it was recorded by mistake): planning stops counting it."""
    if not can(actor, "purchase.record"):
        raise ForbiddenError("purchase.record")
    endpoint = f"POST /purchase-orders/{number}/cancel"
    with conn.transaction():
        stored = idempotency.claim(
            conn, user_id=actor.user_id, endpoint=endpoint, key=key, req_hash="cancel"
        )
        if stored is not None:
            return stored, True
        row = conn.execute(
            "SELECT status FROM purchase_orders WHERE po_number = %s FOR UPDATE", (number,)
        ).fetchone()
        if row is None:
            raise NotFoundError(number)
        if row[0] != "open":
            raise ConflictError(f"{number} is {row[0]}")
        conn.execute(
            "UPDATE purchase_orders SET status = 'cancelled', cancelled_at = %s"
            " WHERE po_number = %s",
            (now, number),
        )
        audit.record(
            conn,
            actor_user_id=actor.user_id,
            action="purchase_order.cancel",
            entity_type="purchase_order",
            entity_id=number,
            before={"status": "open"},
            after={"status": "cancelled"},
            idempotency_key=key,
        )
        response = idempotency.StoredResponse(200, {"number": number, "status": "cancelled"})
        idempotency.store(
            conn, user_id=actor.user_id, endpoint=endpoint, key=key, response=response
        )
        return response, False
