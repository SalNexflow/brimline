"""Orders: list, read, history, and create. Every function checks permissions itself with
can() and order_scope(), so no caller can forget to (hard rule 4). All SQL is parameterised."""

from datetime import date, datetime
from typing import Any, Literal

import psycopg
from psycopg.rows import class_row
from pydantic import BaseModel, ConfigDict, Field

from brimline_engine import audit, idempotency
from brimline_engine.permissions import Actor, OrderTarget, can, order_scope
from brimline_engine.text import SafeText

CREATE_ENDPOINT = "POST /orders"


class NotFoundError(Exception):
    """Missing, or not visible to this actor. The two look the same on purpose."""


class ForbiddenError(Exception):
    pass


class InvalidOrderError(Exception):
    pass


# --- Shapes -----------------------------------------------------------------------------------


class OrderLineIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    part_name: SafeText = Field(min_length=1, max_length=200)
    quantity: int = Field(gt=0, le=10_000)
    material_code: SafeText = Field(min_length=1, max_length=50)


class OrderCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    customer_code: SafeText = Field(min_length=1, max_length=50)
    due_date: date
    rush: bool = False
    notes: SafeText = Field(default="", max_length=2000)
    lines: list[OrderLineIn] = Field(min_length=1, max_length=50)


OrderStatus = Literal["open", "in_production", "done", "cancelled"]


class OrderSummary(BaseModel):
    order_number: str
    customer_code: str
    customer_name: str
    status: OrderStatus
    due_date: date
    rush: bool
    line_count: int
    created_at: datetime


class OrderLineOut(BaseModel):
    line_no: int
    part_name: str
    quantity: int
    material_code: str
    material_name: str
    status: str


class OrderDetail(BaseModel):
    order_number: str
    customer_code: str
    customer_name: str
    status: OrderStatus
    due_date: date
    rush: bool
    notes: str
    created_at: datetime
    created_by_name: str
    lines: list[OrderLineOut]
    can_view_history: bool


class HistoryEntry(BaseModel):
    at: datetime
    actor_name: str | None
    action: str
    idempotency_key: str | None
    before: dict[str, Any] | None
    after: dict[str, Any] | None


class _OrderHeader(BaseModel):
    id: int
    customer_id: int
    order_number: str
    customer_code: str
    customer_name: str
    status: OrderStatus
    due_date: date
    rush: bool
    notes: str
    created_at: datetime
    created_by_name: str


# --- Reads ------------------------------------------------------------------------------------


def list_orders(conn: psycopg.Connection, actor: Actor) -> list[OrderSummary]:
    if not can(actor, "order.list"):
        raise ForbiddenError("order.list")
    scope = order_scope(actor)
    with conn.cursor(row_factory=class_row(OrderSummary)) as cur:
        cur.execute(
            "SELECT o.order_number, c.code AS customer_code, c.name AS customer_name, o.status,"
            "       o.due_date, o.rush, o.created_at,"
            "       (SELECT count(*) FROM jobs j WHERE j.order_id = o.id)::int AS line_count"
            " FROM orders o JOIN customers c ON c.id = o.customer_id"
            " WHERE (%(scope)s::bigint IS NULL OR o.customer_id = %(scope)s::bigint)"
            " ORDER BY o.created_at DESC, o.id DESC",
            {"scope": scope},
        )
        return cur.fetchall()


def _header(conn: psycopg.Connection, actor: Actor, order_number: str) -> _OrderHeader:
    # Two locks on the same door: the query is scoped, and can() checks the row it found.
    scope = order_scope(actor)
    with conn.cursor(row_factory=class_row(_OrderHeader)) as cur:
        cur.execute(
            "SELECT o.id, o.customer_id, o.order_number, c.code AS customer_code,"
            "       c.name AS customer_name, o.status, o.due_date, o.rush, o.notes, o.created_at,"
            "       u.display_name AS created_by_name"
            " FROM orders o JOIN customers c ON c.id = o.customer_id"
            " JOIN users u ON u.id = o.created_by"
            " WHERE o.order_number = %(number)s"
            "   AND (%(scope)s::bigint IS NULL OR o.customer_id = %(scope)s::bigint)",
            {"number": order_number, "scope": scope},
        )
        header = cur.fetchone()
    if header is None or not can(actor, "order.read", OrderTarget(header.customer_id)):
        raise NotFoundError(order_number)
    return header


def get_order(conn: psycopg.Connection, actor: Actor, order_number: str) -> OrderDetail:
    h = _header(conn, actor, order_number)
    with conn.cursor(row_factory=class_row(OrderLineOut)) as cur:
        cur.execute(
            "SELECT j.line_no, j.part_name, j.quantity, m.code AS material_code,"
            "       m.name AS material_name, j.status"
            " FROM jobs j JOIN materials m ON m.id = j.material_id"
            " WHERE j.order_id = %s ORDER BY j.line_no",
            (h.id,),
        )
        lines = cur.fetchall()
    return OrderDetail(
        **h.model_dump(exclude={"id", "customer_id"}),
        lines=lines,
        can_view_history=can(actor, "order.history.read", OrderTarget(h.customer_id)),
    )


def get_history(conn: psycopg.Connection, actor: Actor, order_number: str) -> list[HistoryEntry]:
    h = _header(conn, actor, order_number)  # not visible -> NotFound, before any history check
    if not can(actor, "order.history.read", OrderTarget(h.customer_id)):
        raise ForbiddenError("order.history.read")
    with conn.cursor(row_factory=class_row(HistoryEntry)) as cur:
        cur.execute(
            "SELECT a.at, u.display_name AS actor_name, a.action, a.idempotency_key, a.before, a.after"
            " FROM audit_log a LEFT JOIN users u ON u.id = a.actor_user_id"
            " WHERE a.entity_type = 'order' AND a.entity_id = %s ORDER BY a.id",
            (order_number,),
        )
        return cur.fetchall()


# --- Write ------------------------------------------------------------------------------------


def create_order(
    conn: psycopg.Connection, actor: Actor, body: OrderCreate, key: str, today: date
) -> tuple[idempotency.StoredResponse, bool]:
    """Create an order with one job per line. Returns (response, replayed)."""
    req_hash = idempotency.request_hash(body.model_dump(mode="json"))
    with conn.transaction():
        stored = idempotency.claim(
            conn, user_id=actor.user_id, endpoint=CREATE_ENDPOINT, key=key, req_hash=req_hash
        )
        if stored is not None:
            # Re-read with today's permissions instead of returning the stored snapshot: a replay
            # must never show what a fresh read would not (DEFECT_LOG #8). Raises NotFoundError
            # if the user has lost access to the order since.
            detail = get_order(conn, actor, str(stored.body["order_number"]))
            return idempotency.StoredResponse(stored.status, detail.model_dump(mode="json")), True

        row = conn.execute(
            "SELECT id FROM customers WHERE code = %s", (body.customer_code,)
        ).fetchone()
        if row is None:
            # Only people who may list customers learn whether a customer code exists.
            if can(actor, "customer.list"):
                raise InvalidOrderError(f"unknown customer {body.customer_code}")
            raise ForbiddenError("order.create")
        customer_id = int(row[0])
        if not can(actor, "order.create", OrderTarget(customer_id)):
            raise ForbiddenError("order.create")

        if body.due_date < today:
            raise InvalidOrderError(f"due date {body.due_date} is before today ({today})")

        codes = sorted({line.material_code for line in body.lines})
        materials = {
            code: id_
            for code, id_ in conn.execute(
                "SELECT code, id FROM materials WHERE code = ANY(%s)", (codes,)
            )
        }
        missing = [c for c in codes if c not in materials]
        if missing:
            raise InvalidOrderError(f"unknown material(s): {', '.join(missing)}")

        order = conn.execute(
            "INSERT INTO orders (customer_id, due_date, rush, notes, created_by)"
            " VALUES (%s, %s, %s, %s, %s) RETURNING id, order_number",
            (customer_id, body.due_date, body.rush, body.notes, actor.user_id),
        ).fetchone()
        assert order is not None
        order_id, order_number = int(order[0]), str(order[1])
        for line_no, line in enumerate(body.lines, start=1):
            conn.execute(
                "INSERT INTO jobs (order_id, line_no, part_name, quantity, material_id)"
                " VALUES (%s, %s, %s, %s, %s)",
                (order_id, line_no, line.part_name, line.quantity, materials[line.material_code]),
            )

        detail = get_order(conn, actor, order_number)
        audit.record(
            conn,
            actor_user_id=actor.user_id,
            action="order.create",
            entity_type="order",
            entity_id=order_number,
            before=None,
            after=detail.model_dump(mode="json", exclude={"can_view_history"}),
            idempotency_key=key,
        )
        response = idempotency.StoredResponse(status=201, body=detail.model_dump(mode="json"))
        idempotency.store(
            conn, user_id=actor.user_id, endpoint=CREATE_ENDPOINT, key=key, response=response
        )
        return response, False
