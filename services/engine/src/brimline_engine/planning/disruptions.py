"""Disruptions: a planner's message, how it was understood, and its confirmation (M6).

1. read:     the model reads the message (or AI is off); code interprets the reply and stores
             the disruption for review, with what it could not settle. Nothing else changes.
2. confirm:  the planner confirms or corrects the events; code validates them again. The
             disruption is now pending: every plan made from now on includes it.
   enter:    the same, typed by hand without a message or a model.
3. A plan that includes it is approved (planning/schedules.py): only then are its effects
   applied, in that transaction. Or the planner dismisses it.

Every write is permission-checked, idempotent and audit-logged. The model never decides what
happens; it only proposes events, which code checks and a planner confirms.
"""

from datetime import datetime
from typing import Any, Literal

import psycopg
from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict, Field

from brimline_engine import audit, idempotency
from brimline_engine.ai.calls import record_call
from brimline_engine.ai.gateway import ModelClient
from brimline_engine.disruption_parse import (
    Catalog,
    Event,
    ParsedMessage,
    Review,
    interpret,
    parse_message,
    validate_events,
)
from brimline_engine.permissions import Actor, can
from brimline_engine.shop_config import load_shop_config
from brimline_engine.text import SafeText

Status = Literal["review", "pending", "applied", "dismissed"]


class NotFoundError(Exception):
    pass


class ForbiddenError(Exception):
    pass


class ConflictError(Exception):
    pass


class InvalidError(Exception):
    pass


class MessageIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message: SafeText = Field(min_length=1, max_length=2000)


class EventsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    events: list[Event] = Field(min_length=1, max_length=3)


class DisruptionOut(BaseModel):
    id: int
    message: str
    received_at: datetime
    status: Status
    events: list[Event]
    issues: list[str]  # must be settled before it can be confirmed
    notes: list[str]
    choices: dict[str, list[datetime]]  # event index -> the two readings of an ambiguous date
    warnings: list[str]  # shown prominently: injection, several cancellations
    question: str
    read_by: Literal["model", "hand", "nobody"]  # "nobody": AI was off or failed


def catalog(
    conn: psycopg.Connection,
) -> tuple[Catalog, list[tuple[str, str, str]], list[tuple[str, str]], list[tuple[str, str]]]:
    """The shop's codes for checking, and the same as text for the model's prompt."""
    aliases = {m.code: ", ".join(m.aliases) for m in load_shop_config().machines}
    machines = [
        (code, name, aliases.get(code, ""))
        for code, name in conn.execute("SELECT code, name FROM machines WHERE active ORDER BY code")
    ]
    materials = [
        (code, f"{name} ({process})")
        for code, name, process in conn.execute(
            "SELECT code, name, process FROM materials ORDER BY code"
        )
    ]
    order_rows = conn.execute(
        "SELECT o.order_number, c.name, array_agg(j.part_name ORDER BY j.line_no), count(j.id)"
        " FROM orders o JOIN customers c ON c.id = o.customer_id JOIN jobs j ON j.order_id = o.id"
        " WHERE o.status NOT IN ('done', 'cancelled') GROUP BY o.id, c.name ORDER BY o.order_number"
    ).fetchall()
    orders = [
        (number, f"{customer}: {', '.join(parts)}") for number, customer, parts, _ in order_rows
    ]
    cat = Catalog(
        machines=frozenset(m[0] for m in machines),
        materials=frozenset(m[0] for m in materials),
        orders={number: int(count) for number, _, _, count in order_rows},
    )
    return cat, machines, materials, orders


def _warnings(events: list[Event], injection: bool) -> list[str]:
    out = []
    if injection:
        out.append(
            "The message looks like it tries to give the system instructions. Only the events"
            " listed below were taken from it; nothing else is done."
        )
    cancellations = [e for e in events if e.type == "cancellation"]
    if len(cancellations) >= 2:
        targets = ", ".join(
            f"{e.order}" + (f" line {e.line}" if e.line else "") for e in cancellations
        )
        out.append(
            f"This message cancels {len(cancellations)} orders or lines ({targets}). Check each"
            " one before confirming."
        )
    return out


def _out(row: tuple[Any, ...]) -> DisruptionOut:
    did, message, received, status, events, parsed, ai_call_id, stored = row
    evs = [Event.model_validate(e) for e in events]
    stored = stored or {}
    injection = bool(parsed and parsed.get("injection_suspected"))
    read_by: Literal["model", "hand", "nobody"] = (
        "model" if parsed is not None else "hand" if ai_call_id is None else "nobody"
    )
    return DisruptionOut(
        id=did,
        message=message,
        received_at=received,
        status=status,
        events=evs,
        issues=stored.get("issues", []) if status == "review" else [],
        notes=stored.get("notes", []),
        choices={
            k: [datetime.fromisoformat(d) for d in v] for k, v in stored.get("choices", {}).items()
        }
        if status == "review"
        else {},
        warnings=_warnings(evs, injection),
        question=stored.get("question", "") if status == "review" else "",
        read_by=read_by,
    )


_COLUMNS = "id, message, received_at, status, events, parsed, ai_call_id, review"


def _row(conn: psycopg.Connection, did: int, lock: bool = False) -> tuple[Any, ...]:
    row = conn.execute(
        f"SELECT {_COLUMNS} FROM disruptions WHERE id = %s" + (" FOR UPDATE" if lock else ""),
        (did,),
    ).fetchone()
    if row is None:
        raise NotFoundError(str(did))
    return tuple(row)


def list_open(conn: psycopg.Connection, actor: Actor) -> list[DisruptionOut]:
    if not can(actor, "disruption.report"):
        raise ForbiddenError("disruption.report")
    rows = conn.execute(
        f"SELECT {_COLUMNS} FROM disruptions WHERE status IN ('review', 'pending') ORDER BY id"
    ).fetchall()
    return [_out(tuple(r)) for r in rows]


def _events_json(events: list[Event]) -> list[dict[str, Any]]:
    return [e.model_dump(mode="json") for e in events]


def read(
    conn: psycopg.Connection,
    actor: Actor,
    body: MessageIn,
    key: str,
    now: datetime,
    *,
    client: ModelClient | None,
    mode: str,
    tz: str,
    shifts: dict[str, tuple[str, str]],
) -> tuple[idempotency.StoredResponse, bool]:
    """Read a message into events for the planner to review. The model is called inside the
    transaction, after the key is claimed, so a retry with the same key waits for this one and
    replays its answer instead of calling the model again."""
    if not can(actor, "disruption.report"):
        raise ForbiddenError("disruption.report")
    endpoint = "POST /disruptions"
    req_hash = idempotency.request_hash(body.model_dump())
    with conn.transaction():
        stored = idempotency.claim(
            conn, user_id=actor.user_id, endpoint=endpoint, key=key, req_hash=req_hash
        )
        if stored is not None:
            return stored, True
        cat, machines, materials, orders = catalog(conn)
        result = parse_message(
            client,
            mode=mode,
            message=body.message,
            machines=machines,
            materials=materials,
            orders=orders,
        )
        call_id = record_call(conn, result.record, actor.user_id)
        parsed: ParsedMessage | None = result.value
        if parsed is None:
            review = Review(
                events=[],
                issues=["the message could not be read automatically; enter the events by hand"],
            )
        else:
            review = interpret(parsed, now, tz, shifts, cat)
        row = conn.execute(
            "INSERT INTO disruptions (message, received_at, ai_call_id, parsed, events, review,"
            " created_by) VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id",
            (
                body.message,
                now,
                call_id,
                None if parsed is None else Jsonb(parsed.model_dump(mode="json")),
                Jsonb(_events_json(review.events)),
                Jsonb(
                    {
                        "issues": review.issues,
                        "notes": review.notes,
                        "choices": {
                            str(k): [d.isoformat() for d in v] for k, v in review.choices.items()
                        },
                        "question": review.question,
                    }
                ),
                actor.user_id,
            ),
        ).fetchone()
        assert row is not None
        out = _out(_row(conn, int(row[0])))
        audit.record(
            conn,
            actor_user_id=actor.user_id,
            action="disruption.read",
            entity_type="disruption",
            entity_id=str(out.id),
            before=None,
            after=out.model_dump(mode="json"),
            idempotency_key=key,
        )
        response = idempotency.StoredResponse(201, out.model_dump(mode="json"))
        idempotency.store(
            conn, user_id=actor.user_id, endpoint=endpoint, key=key, response=response
        )
        return response, False


def _check(conn: psycopg.Connection, events: list[Event], received: datetime) -> None:
    cat, *_ = catalog(conn)
    problems = validate_events(events, received, cat)
    if problems:
        raise InvalidError("; ".join(problems))


def confirm(
    conn: psycopg.Connection, actor: Actor, did: int, body: EventsIn, key: str, now: datetime
) -> tuple[idempotency.StoredResponse, bool]:
    """The planner confirms the events (as read, or corrected): they become pending."""
    if not can(actor, "disruption.report"):
        raise ForbiddenError("disruption.report")
    endpoint = f"POST /disruptions/{did}/confirm"
    req_hash = idempotency.request_hash(body.model_dump(mode="json"))
    with conn.transaction():
        stored = idempotency.claim(
            conn, user_id=actor.user_id, endpoint=endpoint, key=key, req_hash=req_hash
        )
        if stored is not None:
            return stored, True
        row = _row(conn, did, lock=True)
        if row[3] != "review":
            raise ConflictError(f"disruption {did} is {row[3]}, not waiting for review")
        _check(conn, body.events, row[2])
        before = _out(row)
        conn.execute(
            "UPDATE disruptions SET events = %s, status = 'pending' WHERE id = %s",
            (Jsonb(_events_json(body.events)), did),
        )
        after = _out(_row(conn, did))
        audit.record(
            conn,
            actor_user_id=actor.user_id,
            action="disruption.confirm",
            entity_type="disruption",
            entity_id=str(did),
            before=before.model_dump(mode="json"),
            after=after.model_dump(mode="json"),
            idempotency_key=key,
        )
        response = idempotency.StoredResponse(200, after.model_dump(mode="json"))
        idempotency.store(
            conn, user_id=actor.user_id, endpoint=endpoint, key=key, response=response
        )
        return response, False


def enter(
    conn: psycopg.Connection, actor: Actor, body: EventsIn, key: str, now: datetime
) -> tuple[idempotency.StoredResponse, bool]:
    """Events typed by hand (no message, no model): pending at once after the same checks."""
    if not can(actor, "disruption.report"):
        raise ForbiddenError("disruption.report")
    endpoint = "POST /disruptions/by-hand"
    req_hash = idempotency.request_hash(body.model_dump(mode="json"))
    with conn.transaction():
        stored = idempotency.claim(
            conn, user_id=actor.user_id, endpoint=endpoint, key=key, req_hash=req_hash
        )
        if stored is not None:
            return stored, True
        _check(conn, body.events, now)
        row = conn.execute(
            "INSERT INTO disruptions (message, received_at, events, status, created_by)"
            " VALUES ('', %s, %s, 'pending', %s) RETURNING id",
            (now, Jsonb(_events_json(body.events)), actor.user_id),
        ).fetchone()
        assert row is not None
        out = _out(_row(conn, int(row[0])))
        audit.record(
            conn,
            actor_user_id=actor.user_id,
            action="disruption.enter",
            entity_type="disruption",
            entity_id=str(out.id),
            before=None,
            after=out.model_dump(mode="json"),
            idempotency_key=key,
        )
        response = idempotency.StoredResponse(201, out.model_dump(mode="json"))
        idempotency.store(
            conn, user_id=actor.user_id, endpoint=endpoint, key=key, response=response
        )
        return response, False


def dismiss(
    conn: psycopg.Connection, actor: Actor, did: int, key: str, now: datetime
) -> tuple[idempotency.StoredResponse, bool]:
    if not can(actor, "disruption.report"):
        raise ForbiddenError("disruption.report")
    endpoint = f"POST /disruptions/{did}/dismiss"
    with conn.transaction():
        stored = idempotency.claim(
            conn, user_id=actor.user_id, endpoint=endpoint, key=key, req_hash="dismiss"
        )
        if stored is not None:
            return stored, True
        row = _row(conn, did, lock=True)
        if row[3] not in ("review", "pending"):
            raise ConflictError(f"disruption {did} is {row[3]}")
        conn.execute(
            "UPDATE disruptions SET status = 'dismissed', decided_by = %s, decided_at = %s"
            " WHERE id = %s",
            (actor.user_id, now, did),
        )
        audit.record(
            conn,
            actor_user_id=actor.user_id,
            action="disruption.dismiss",
            entity_type="disruption",
            entity_id=str(did),
            before={"status": row[3]},
            after={"status": "dismissed"},
            idempotency_key=key,
        )
        response = idempotency.StoredResponse(200, {"id": did, "status": "dismissed"})
        idempotency.store(
            conn, user_id=actor.user_id, endpoint=endpoint, key=key, response=response
        )
        return response, False
