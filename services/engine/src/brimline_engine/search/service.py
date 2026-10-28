"""Search (M8): a question or a filter in, scoped rows out.

    question -> fast path or model -> interpret (code) -> scope (code) -> query (code)
    filter (chips) ---------------------------------------> scope (code) -> query (code)

Search changes no data; the only write is the model call's cost record (ai_calls). Nothing the
model writes is shown to the person: an unclear question gets code's own message, so a reply
cannot carry text (another customer's name, say) to the screen."""

from datetime import datetime
from typing import Literal

import psycopg
from pydantic import BaseModel, ConfigDict, Field

from brimline_engine.ai.calls import record_call
from brimline_engine.ai.gateway import ModelClient
from brimline_engine.dates import shop_today
from brimline_engine.permissions import Actor, can
from brimline_engine.search import query
from brimline_engine.search.filters import Catalog, Filter, check_filter, describe
from brimline_engine.search.reading import Reading, fast_path, interpret, parse_question
from brimline_engine.text import SafeText

ForbiddenError = query.ForbiddenError


class InvalidError(Exception):
    pass


class QuestionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: SafeText = Field(min_length=1, max_length=500)


class AiInfo(BaseModel):
    model: str | None
    outcome: str
    cost_micro_usd: int
    latency_ms: int


class SearchOut(BaseModel):
    kind: Literal["filter", "unclear", "needs_confirmation"]
    filter: Filter | None  # what was run, after permissions
    description: str  # the filter in plain words, written by code
    notices: list[str]
    reason: str  # why it is unclear, written by code
    readings: list[str]  # ISO dates, when a date reads two ways
    options: list[Filter] = []  # one ready filter per reading, already scoped for the asker
    rows: list[query.Row]
    total: int
    limited: bool  # more rows matched than are shown
    ai: AiInfo | None
    injection_suspected: bool


def catalog(conn: psycopg.Connection) -> Catalog:
    return Catalog(
        customers=dict(conn.execute("SELECT code, name FROM customers ORDER BY code").fetchall()),
        materials=dict(conn.execute("SELECT code, name FROM materials ORDER BY code").fetchall()),
    )


def _own_code(conn: psycopg.Connection, actor: Actor) -> str | None:
    if actor.customer_id is None:
        return None
    row = conn.execute("SELECT code FROM customers WHERE id = %s", (actor.customer_id,)).fetchone()
    return str(row[0]) if row else None


UNCLEAR = (
    "The search could not turn this into a filter, so nothing was searched. Ask about jobs and"
    " orders (due dates, status, material, customer, part names), or build the filter below."
)


def _empty(reading: Reading, ai: AiInfo | None, options: list[Filter] | None = None) -> SearchOut:
    if reading.kind == "needs_confirmation":
        reason = reading.reason
    else:
        reason = f"{UNCLEAR} ({reading.reason})" if reading.reason else UNCLEAR
    return SearchOut(
        kind=reading.kind,
        filter=None,
        description="",
        notices=[],
        reason=reason,
        readings=reading.readings,
        options=options or [],
        rows=[],
        total=0,
        limited=False,
        ai=ai,
        injection_suspected=reading.injection_suspected,
    )


def run_filter(
    conn: psycopg.Connection,
    actor: Actor,
    f: Filter,
    now: datetime,
    tz: str,
    *,
    ai: AiInfo | None = None,
    injection_suspected: bool = False,
) -> SearchOut:
    """Check, scope and run a filter: chips come straight here, without any model."""
    if not can(actor, "order.list"):
        raise ForbiddenError("order.list")
    try:
        checked = check_filter(f, catalog(conn))
    except ValueError as e:
        raise InvalidError(str(e)) from e
    scoped = query.scope(checked, actor, _own_code(conn, actor))
    rows, total = query.run(conn, actor, scoped.filter, shop_today(now, tz))
    return SearchOut(
        kind="filter",
        filter=scoped.filter,
        description=describe(scoped.filter),
        notices=scoped.notices,
        reason="",
        readings=[],
        rows=rows,
        total=total,
        limited=total > len(rows),
        ai=ai,
        injection_suspected=injection_suspected,
    )


def search(
    conn: psycopg.Connection,
    actor: Actor,
    body: QuestionIn,
    now: datetime,
    tz: str,
    shifts: dict[str, tuple[str, str]],
    *,
    client: ModelClient | None,
    mode: str,
) -> SearchOut:
    if not can(actor, "order.list"):
        raise ForbiddenError("order.list")
    direct = fast_path(body.question)
    if direct is not None:
        return run_filter(conn, actor, direct, now, tz)
    cat = catalog(conn)
    result = parse_question(client, mode=mode, question=body.question, catalog=cat)
    with conn.transaction():
        record_call(conn, result.record, actor.user_id)
    ai = AiInfo(
        model=result.record.model,
        outcome=result.record.outcome,
        cost_micro_usd=result.record.cost_micro_usd,
        latency_ms=result.record.latency_ms,
    )
    if result.value is None:
        out = _empty(Reading(kind="unclear"), ai)
        return (
            out.model_copy(update={"reason": "AI is off: build the filter below."})
            if client is None
            else out
        )
    reading = interpret(result.value, now, tz, shifts, cat)
    if reading.kind == "needs_confirmation":
        own = _own_code(conn, actor)
        return _empty(reading, ai, [query.scope(o, actor, own).filter for o in reading.options])
    if reading.kind != "filter" or reading.filter is None:
        return _empty(reading, ai)
    return run_filter(
        conn, actor, reading.filter, now, tz, ai=ai, injection_suspected=reading.injection_suspected
    )
