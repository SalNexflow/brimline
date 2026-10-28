"""The search filter (M8): a closed set of fields, operators and values, checked by code.

A filter is what every search runs, whether a model read it from a question, a person edited
it as chips, or both. Nothing outside the table below exists, so a reply naming any other field
or operator is refused. The model never writes SQL (hard rule 5): `query.py` builds the query
from fixed pieces and passes every value as a parameter."""

import re
from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

FieldName = Literal[
    "order_number",
    "customer",
    "order_status",
    "job_status",
    "material",
    "process",
    "rush",
    "printed",
    "can_plan",
    "overdue",
    "quantity",
    "part_name",
    "notes",
    "due_date",
]
Op = Literal[
    "in", "is", "eq", "lt", "lte", "gt", "gte", "contains",
    "on", "before", "after", "on_or_before", "on_or_after", "between",
]  # fmt: skip
Sort = Literal["due_date", "created"]
# Text, a number, true/false, or a list of texts (codes, or two ISO dates).
Value = bool | int | str | list[str]

ORDER_STATUSES = ("open", "in_production", "done", "cancelled")
JOB_STATUSES = ("pending", "planned", "in_progress", "done", "failed", "cancelled")
PROCESSES = ("fdm", "resin", "cnc")

# Which operators each field takes, and what kind of value.
OPS: dict[str, tuple[set[str], str]] = {
    "order_number": ({"in"}, "codes"),
    "customer": ({"in"}, "codes"),
    "order_status": ({"in"}, "codes"),
    "job_status": ({"in"}, "codes"),
    "material": ({"in"}, "codes"),
    "process": ({"in"}, "codes"),
    "rush": ({"is"}, "bool"),
    "printed": ({"is"}, "bool"),
    "can_plan": ({"is"}, "bool"),
    "overdue": ({"is"}, "true"),
    "quantity": ({"eq", "lt", "lte", "gt", "gte"}, "int"),
    "part_name": ({"contains"}, "text"),
    "notes": ({"contains"}, "text"),
    "due_date": ({"on", "before", "after", "on_or_before", "on_or_after", "between"}, "date"),
}
MAX_TEXT = 100
MAX_VALUES = 20


class Catalog(BaseModel):
    """The codes a filter may name. Read from the database for each search."""

    customers: dict[str, str]  # code -> name
    materials: dict[str, str]  # code -> name


class Condition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    field: FieldName
    op: Op
    value: Value


class Filter(BaseModel):
    """What a search runs. Conditions are joined with AND."""

    model_config = ConfigDict(extra="forbid")

    conditions: list[Condition] = Field(default_factory=list, max_length=20)
    sort: Sort = "due_date"


def check_condition(c: Condition, catalog: Catalog) -> Condition:
    """The same condition with its value in canonical form, or ValueError in plain words."""
    ops, kind = OPS[c.field]
    if c.op not in ops:
        raise ValueError(f"{c.field} does not take '{c.op}' (only {', '.join(sorted(ops))})")
    v = c.value
    match kind:
        case "codes":
            values = v if isinstance(v, list) else [v]
            if (
                not values
                or len(values) > MAX_VALUES
                or not all(isinstance(x, str) for x in values)
            ):
                raise ValueError(f"{c.field} needs 1 to {MAX_VALUES} values")
            allowed = _allowed(c.field, catalog)
            texts = [str(x) for x in values]
            cleaned = sorted(
                {x.strip().upper() if c.field in _UPPER else x.strip().lower() for x in texts}
            )
            unknown = [x for x in cleaned if allowed is not None and x not in allowed]
            if unknown:
                raise ValueError(f"unknown {c.field.replace('_', ' ')}: {', '.join(unknown)}")
            if c.field == "order_number" and not all(_ORDER.fullmatch(x) for x in cleaned):
                raise ValueError("an order number looks like BL-0001")
            return Condition(field=c.field, op=c.op, value=cleaned)
        case "bool" | "true":
            if not isinstance(v, bool):
                raise ValueError(f"{c.field} is true or false")
            if kind == "true" and v is not True:
                raise ValueError("overdue can only be true (use a due date for the rest)")
            return Condition(field=c.field, op=c.op, value=v)
        case "int":
            if isinstance(v, bool) or not isinstance(v, int) or not 0 <= v <= 1_000_000:
                raise ValueError("quantity is a whole number")
            return Condition(field=c.field, op=c.op, value=v)
        case "text":
            if not isinstance(v, str) or not v.strip() or len(v) > MAX_TEXT:
                raise ValueError(f"{c.field.replace('_', ' ')} needs 1 to {MAX_TEXT} characters")
            if any(ord(ch) < 32 for ch in v):
                raise ValueError("text may not hold control characters")
            return Condition(field=c.field, op=c.op, value=v.strip())
        case _:  # date
            if c.op == "between":
                if not (isinstance(v, list) and len(v) == 2):
                    raise ValueError("between needs two dates")
                start, end = (_iso(x) for x in v)
                if end < start:
                    raise ValueError("the second date is before the first")
                return Condition(field=c.field, op=c.op, value=[start.isoformat(), end.isoformat()])
            return Condition(field=c.field, op=c.op, value=_iso(v).isoformat())


_UPPER = {"order_number", "customer", "material"}


def _allowed(field: str, catalog: Catalog) -> set[str] | None:
    return {
        "customer": set(catalog.customers),
        "material": set(catalog.materials),
        "order_status": set(ORDER_STATUSES),
        "job_status": set(JOB_STATUSES),
        "process": set(PROCESSES),
    }.get(field)  # order numbers are checked by pattern; a missing one simply finds nothing


def _iso(v: object) -> date:
    if not isinstance(v, str):
        raise ValueError("a date is written YYYY-MM-DD")
    try:
        return date.fromisoformat(v)
    except ValueError as e:
        raise ValueError(f"{v!r} is not a date (YYYY-MM-DD)") from e


_ORDER = re.compile(r"BL-[0-9]{4,10}")


def check_filter(f: Filter, catalog: Catalog) -> Filter:
    """Every condition checked and put in canonical form, sorted, duplicates removed. Two
    filters that mean the same thing come out equal (the eval compares these)."""
    seen = {}
    for c in f.conditions:
        checked = check_condition(c, catalog)
        seen[(checked.field, checked.op, repr(checked.value))] = checked
    conditions = sorted(seen.values(), key=lambda c: (c.field, c.op, repr(c.value)))
    return Filter(conditions=conditions, sort=f.sort)


# --- Plain words, written by code ---------------------------------------------------------------

_LABELS = {
    "order_number": "order",
    "customer": "customer",
    "order_status": "order status",
    "job_status": "job status",
    "material": "material",
    "process": "process",
    "quantity": "quantity",
    "part_name": "part name",
    "notes": "order notes",
    "due_date": "due",
}
_OPS_WORDS = {
    "eq": "=", "lt": "<", "lte": "≤", "gt": ">", "gte": "≥",
    "on": "on", "before": "before", "after": "after",
    "on_or_before": "on or before", "on_or_after": "on or after",
}  # fmt: skip


def describe_condition(c: Condition) -> str:
    match c.field:
        case "rush":
            return "rush" if c.value else "not rush"
        case "printed":
            return "printed" if c.value else "not printed yet"
        case "can_plan":
            return "can be planned" if c.value else "cannot be planned yet (missing information)"
        case "overdue":
            return "overdue"
        case _:
            pass
    label = _LABELS[c.field]
    if isinstance(c.value, list):
        if c.op == "between":
            return f"{label} {c.value[0]} to {c.value[1]}"
        return f"{label} {' or '.join(c.value)}"
    if c.op == "contains":
        return f"{label} contains “{c.value}”"
    return f"{label} {_OPS_WORDS[c.op]} {c.value}"


def describe(f: Filter) -> str:
    """The whole filter as one plain sentence, so a person can check what was searched."""
    parts = [describe_condition(c) for c in f.conditions]
    what = "; ".join(parts) if parts else "all jobs you may see"
    order = "soonest due first" if f.sort == "due_date" else "newest first"
    return f"Jobs: {what} ({order})."
