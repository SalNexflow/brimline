"""Permissions and the query (M8). Both are code, run after any model step, on every search.

Two locks, as for orders: a customer's filter is rewritten to their own customer (so the chips
show what was really searched), and the SQL itself is always scoped with order_scope(). The
query is built from the fixed pieces below; every value is a parameter (hard rules 4 and 5)."""

from datetime import date
from typing import Any

import psycopg
from psycopg import sql
from pydantic import BaseModel

from brimline_engine.permissions import Actor, can, order_scope
from brimline_engine.search.filters import Condition, Filter

MAX_ROWS = 200


class ForbiddenError(Exception):
    pass


class Scoped(BaseModel):
    filter: Filter
    notices: list[str]


def scope(f: Filter, actor: Actor, own_code: str | None) -> Scoped:
    """The filter this actor may run. For a customer, every customer condition is replaced by
    their own customer, whatever the question, the model or the chips said."""
    if order_scope(actor) is None:
        return Scoped(filter=f, notices=[])
    if own_code is None:  # a customer without a customer fails closed
        raise ForbiddenError("order.list")
    asked = [c for c in f.conditions if c.field == "customer"]
    kept = [c for c in f.conditions if c.field != "customer"]
    own = Condition(field="customer", op="in", value=[own_code])
    conditions = sorted([*kept, own], key=lambda c: (c.field, c.op, repr(c.value)))
    notices = []
    if any(c.value != [own_code] for c in asked):
        notices.append("Showing your own orders only: you can only search your own orders.")
    return Scoped(filter=Filter(conditions=conditions, sort=f.sort), notices=notices)


class Row(BaseModel):
    order_number: str
    line_no: int
    part_name: str
    quantity: int
    material_code: str
    customer_code: str
    customer_name: str
    order_status: str
    job_status: str
    due_date: date
    rush: bool
    printed: bool
    can_plan: bool


PRINTED = (
    "EXISTS (SELECT 1 FROM tasks t WHERE t.job_id = j.id"
    " AND t.kind IN ('print', 'machining') AND t.status = 'done')"
)
CAN_PLAN = (
    "(j.minutes_per_part IS NOT NULL AND j.part_x_mm IS NOT NULL"
    " AND j.part_y_mm IS NOT NULL AND j.part_z_mm IS NOT NULL)"
)
IN_COLUMNS = {
    "order_number": "o.order_number",
    "customer": "c.code",
    "order_status": "o.status",
    "job_status": "j.status",
    "material": "m.code",
    "process": "m.process",
}
BOOL_EXPRESSIONS = {"rush": "o.rush", "printed": PRINTED, "can_plan": CAN_PLAN}
COMPARE = {"eq": "=", "lt": "<", "lte": "<=", "gt": ">", "gte": ">="}
DATE_COMPARE = {
    "on": "=", "before": "<", "after": ">", "on_or_before": "<=", "on_or_after": ">=",
}  # fmt: skip


def _piece(c: Condition, name: str) -> tuple[str, dict[str, Any]]:
    """One condition as a fixed SQL piece with named parameters. Only these pieces exist."""
    p = f"%({name})s"
    match c.field, c.op:
        case (f, "in") if f in IN_COLUMNS:
            return f"{IN_COLUMNS[f]} = ANY({p}::text[])", {name: c.value}
        case (f, "is") if f in BOOL_EXPRESSIONS:
            return f"({BOOL_EXPRESSIONS[f]}) = {p}::boolean", {name: c.value}
        case ("overdue", "is"):
            return f"(o.due_date < {p}::date AND j.status NOT IN ('done', 'cancelled'))", {}
        case ("quantity", op):
            return f"j.quantity {COMPARE[op]} {p}::integer", {name: c.value}
        case ("part_name", "contains"):
            return f"strpos(lower(j.part_name), lower({p}::text)) > 0", {name: c.value}
        case ("notes", "contains"):
            return f"strpos(lower(o.notes), lower({p}::text)) > 0", {name: c.value}
        case ("due_date", "between"):
            assert isinstance(c.value, list)  # check_filter made it [from, to]
            return (
                f"o.due_date BETWEEN %({name}_a)s::date AND %({name}_b)s::date",
                {f"{name}_a": c.value[0], f"{name}_b": c.value[1]},
            )
        case ("due_date", op):
            return f"o.due_date {DATE_COMPARE[op]} {p}::date", {name: c.value}
    raise ValueError(f"no query piece for {c.field} {c.op}")  # unreachable after check_filter


BASE = (
    "SELECT o.order_number, j.line_no, j.part_name, j.quantity, m.code AS material_code,"
    "       c.code AS customer_code, c.name AS customer_name, o.status AS order_status,"
    f"       j.status AS job_status, o.due_date, o.rush, {PRINTED} AS printed,"
    f"       {CAN_PLAN} AS can_plan, count(*) OVER () AS total"
    " FROM jobs j JOIN orders o ON o.id = j.order_id JOIN customers c ON c.id = o.customer_id"
    " JOIN materials m ON m.id = j.material_id"
    " WHERE (%(scope)s::bigint IS NULL OR o.customer_id = %(scope)s::bigint)"
)
ORDER = {
    "due_date": " ORDER BY o.due_date, o.order_number, j.line_no",
    "created": " ORDER BY o.created_at DESC, o.id DESC, j.line_no",
}


def build(f: Filter, actor: Actor, today: date) -> tuple[sql.Composed, dict[str, Any]]:
    """The SQL text (only our fixed pieces) and its parameters (every value)."""
    params: dict[str, Any] = {"scope": order_scope(actor), "limit": MAX_ROWS}
    parts = [sql.SQL(BASE)]  # fixed text, built from constants only
    for i, c in enumerate(f.conditions):
        text, values = _piece(c, f"p{i}")
        if c.field == "overdue":
            text = text.replace(f"%(p{i})s", "%(today)s")
            params["today"] = today
        parts.append(sql.SQL(" AND " + text))
        params |= values
    parts.append(sql.SQL(ORDER[f.sort] + " LIMIT %(limit)s"))
    return sql.Composed(parts), params


def run(conn: psycopg.Connection, actor: Actor, f: Filter, today: date) -> tuple[list[Row], int]:
    if not can(actor, "order.list"):
        raise ForbiddenError("order.list")
    query, params = build(f, actor, today)
    rows = conn.execute(query, params).fetchall()
    total = int(rows[0][-1]) if rows else 0
    names = list(Row.model_fields)
    return [Row.model_validate(dict(zip(names, r[:-1], strict=True))) for r in rows], total
