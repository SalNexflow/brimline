"""Quotes: a customer's message becomes a draft (AI reads, code decides), staff edit it, and a
human approves it into an order (hard rule 7). Every function checks permissions itself.

What decides what:
  the model     part descriptions, quantities, material codes, the due-date *rule*, flags
  code          the due date (dates.resolve_due), what is missing, every price (pricing.py)
  staff         grams and minutes per part, corrections, approval
"""

from collections.abc import Callable
from dataclasses import asdict
from datetime import date, datetime
from typing import Any, Literal

import psycopg
from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict, Field

from brimline_engine import audit, idempotency, orders
from brimline_engine.ai.gateway import CallRecord, GatewayResult
from brimline_engine.dates import resolve_due
from brimline_engine.permissions import Actor, OrderTarget, can, order_scope
from brimline_engine.price_rules import load_rules
from brimline_engine.pricing import LineInput, PricingPending, price_quote
from brimline_engine.quote_extract import PostProcess, QuoteDraft
from brimline_engine.text import SafeText

SUBMIT_ENDPOINT = "POST /quote-requests"
EDIT_ENDPOINT = "PUT /quotes"
DECIDE_ENDPOINT = "POST /quotes/decide"

Source = Literal["ai", "staff", "missing"]
Extractor = Callable[[str], GatewayResult[QuoteDraft]]


class NotFoundError(Exception):
    pass


class ForbiddenError(Exception):
    pass


class InvalidQuoteError(Exception):
    pass


# --- Shapes -----------------------------------------------------------------------------------


class QuoteRequestIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    customer_code: SafeText = Field(min_length=1, max_length=50)
    message: SafeText = Field(min_length=1, max_length=10_000)


class QuoteLineEdit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    part_name: SafeText = Field(min_length=1, max_length=200)
    quantity: int | None = Field(default=None, ge=1, le=10_000)
    material_code: SafeText | None = Field(default=None, max_length=50)
    grams_per_part: int | None = Field(default=None, ge=1, le=100_000)
    minutes_per_part: int | None = Field(default=None, ge=1, le=100_000)
    post_processing: list[PostProcess] = Field(default_factory=list, max_length=3)


class QuoteEdit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    due_date: date | None
    rush: bool
    notes: SafeText = Field(default="", max_length=2000)
    lines: list[QuoteLineEdit] = Field(min_length=1, max_length=50)


class QuoteDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision: Literal["approve", "reject"]


class QuoteLineOut(BaseModel):
    line_no: int
    part_name: str
    quantity: int | None
    material_code: str | None
    material_name: str | None
    material_as_written: str | None
    grams_per_part: int | None
    minutes_per_part: int | None
    post_processing: list[str]
    sources: dict[str, Source]
    uncertain: list[str]


class LinePriceOut(BaseModel):
    material_cents: int
    machine_cents: int
    post_process_cents: int
    setup_cents: int
    total_cents: int


class PriceOut(BaseModel):
    rule_set_id: int
    lines: list[LinePriceOut]
    subtotal_cents: int
    rush_surcharge_cents: int
    total_cents: int


class AiInfo(BaseModel):
    outcome: str
    model: str | None
    prompt_version: str
    cost_micro_usd: int
    latency_ms: int


class QuoteSummary(BaseModel):
    quote_number: str
    status: Literal["draft", "approved", "rejected"]
    customer_code: str
    customer_name: str
    received_at: datetime
    line_count: int
    total_cents: int | None  # only for staff, or once approved
    missing_count: int


class QuoteDetail(BaseModel):
    quote_number: str
    status: Literal["draft", "approved", "rejected"]
    customer_code: str
    customer_name: str
    received_at: datetime
    submitted_by_name: str
    message: str
    due_date: date | None
    due_rule: dict[str, Any] | None
    rush: bool
    notes: str
    lines: list[QuoteLineOut]
    missing: list[str]
    questions_for_customer: list[str]
    requests_for_staff: list[str] | None  # staff only
    price: PriceOut | None  # staff, or the customer once approved
    price_pending: list[str]
    ai: AiInfo | None  # staff only
    order_number: str | None
    can_edit: bool
    can_decide: bool


# --- Helpers ----------------------------------------------------------------------------------


def _materials(conn: psycopg.Connection) -> dict[str, tuple[int, str, str]]:
    """code -> (id, name, process)"""
    return {
        code: (mid, name, process)
        for mid, code, name, process in conn.execute(
            "SELECT id, code, name, process FROM materials"
        )
    }


def compute_missing(lines: list[QuoteLineOut], due_date: date | None) -> list[str]:
    """What staff must still fill in before approval. Decided by code, not by the model."""
    missing = [] if lines else ["at least one line"]
    for line in lines:
        for label, value in (
            ("quantity", line.quantity),
            ("material", line.material_code),
            ("grams per part", line.grams_per_part),
            ("minutes per part", line.minutes_per_part),
        ):
            if value is None:
                missing.append(f"line {line.line_no}: {label}")
    if due_date is None:
        missing.append("due date")
    return missing


def _price(
    conn: psycopg.Connection,
    lines: list[QuoteLineOut],
    rush: bool,
    today: date,
    mats: dict[str, tuple[int, str, str]],
) -> tuple[int | None, dict[str, Any]]:
    """(rule set id, price JSON) using the rules in effect today."""
    rules = load_rules(conn, today)
    if rules is None:
        return None, {"pending": ["no price rules in effect"]}
    inputs = [
        LineInput(
            part_name=line.part_name,
            quantity=line.quantity,
            material_code=line.material_code,
            process=mats[line.material_code][2] if line.material_code in mats else None,
            grams_per_part=line.grams_per_part,
            minutes_per_part=line.minutes_per_part,
            post_processing=tuple(line.post_processing),
        )
        for line in lines
    ]
    result = price_quote(inputs, rush=rush, rules=rules)
    if isinstance(result, PricingPending):
        return rules.rule_set_id, {"pending": result.missing}
    lines_out = [{**asdict(p), "total_cents": p.total_cents} for p in result.lines]
    return rules.rule_set_id, {**asdict(result), "lines": lines_out}


def _record_call(conn: psycopg.Connection, record: CallRecord, actor: Actor) -> int:
    u = record.usage
    row = conn.execute(
        "INSERT INTO ai_calls (purpose, mode, model, prompt_version, outcome, attempts, input_tokens,"
        " output_tokens, cache_read_tokens, cache_write_tokens, cost_micro_usd, latency_ms, error, created_by)"
        " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
        (
            record.purpose,
            record.mode,
            record.model,
            record.prompt_version,
            record.outcome,
            record.attempts,
            u.input_tokens,
            u.output_tokens,
            u.cache_read_tokens,
            u.cache_write_tokens,
            record.cost_micro_usd,
            record.latency_ms,
            record.error,
            actor.user_id,
        ),
    ).fetchone()
    assert row is not None
    return int(row[0])


def _write_lines(
    conn: psycopg.Connection,
    quote_id: int,
    lines: list[QuoteLineOut],
    mats: dict[str, tuple[int, str, str]],
) -> None:
    conn.execute("DELETE FROM quote_lines WHERE quote_id = %s", (quote_id,))
    for line in lines:
        conn.execute(
            "INSERT INTO quote_lines (quote_id, line_no, part_name, quantity, material_id, material_as_written,"
            " grams_per_part, minutes_per_part, post_processing, sources, uncertain)"
            " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (
                quote_id,
                line.line_no,
                line.part_name,
                line.quantity,
                mats[line.material_code][0] if line.material_code else None,
                line.material_as_written,
                line.grams_per_part,
                line.minutes_per_part,
                line.post_processing,
                Jsonb(line.sources),
                line.uncertain,
            ),
        )


def _source(value: object) -> Source:
    return "missing" if value is None else "ai"


def lines_from_draft(
    draft: QuoteDraft | None, mats: dict[str, tuple[int, str, str]]
) -> list[QuoteLineOut]:
    if draft is None:
        return []
    return [
        QuoteLineOut(
            line_no=n,
            part_name=line.part_description,
            quantity=line.quantity,
            material_code=line.material_code,
            material_name=mats[line.material_code][1] if line.material_code in mats else None,
            material_as_written=line.material_as_written,
            grams_per_part=None,  # staff measure these; the model never guesses them
            minutes_per_part=None,
            post_processing=list(dict.fromkeys(line.post_processing)),
            sources={
                "part_name": "ai",
                "quantity": _source(line.quantity),
                "material": _source(line.material_code),
                "grams_per_part": "missing",
                "minutes_per_part": "missing",
                "post_processing": "ai",
            },
            uncertain=list(line.uncertain),
        )
        for n, line in enumerate(draft.lines, start=1)
    ]


# --- Reads ------------------------------------------------------------------------------------

_HEADER_SQL = (
    "SELECT q.id, q.customer_id, q.quote_number, q.status, c.code, c.name, r.received_at,"
    "       u.display_name, r.message, q.due_date, q.due_rule, q.rush, q.notes, q.missing,"
    "       q.questions, q.requests_for_staff, q.price, q.total_cents, o.order_number,"
    "       a.outcome, a.model, a.prompt_version, a.cost_micro_usd, a.latency_ms"
    " FROM quotes q JOIN customers c ON c.id = q.customer_id"
    " JOIN quote_requests r ON r.id = q.request_id JOIN users u ON u.id = r.submitted_by"
    " LEFT JOIN orders o ON o.id = q.order_id LEFT JOIN ai_calls a ON a.id = q.ai_call_id"
)


def _find(conn: psycopg.Connection, actor: Actor, quote_number: str) -> tuple[Any, ...]:
    scope = order_scope(actor)
    row = conn.execute(
        (
            _HEADER_SQL
            + " WHERE q.quote_number = %(n)s AND (%(s)s::bigint IS NULL OR q.customer_id = %(s)s::bigint)"
        ).encode(),
        {"n": quote_number, "s": scope},
    ).fetchone()
    if row is None or not can(actor, "quote.read", OrderTarget(row[1])):
        raise NotFoundError(quote_number)
    return tuple(row)


def _lines(conn: psycopg.Connection, quote_id: int) -> list[QuoteLineOut]:
    rows = conn.execute(
        "SELECT l.line_no, l.part_name, l.quantity, m.code, m.name, l.material_as_written,"
        "       l.grams_per_part, l.minutes_per_part, l.post_processing, l.sources, l.uncertain"
        " FROM quote_lines l LEFT JOIN materials m ON m.id = l.material_id"
        " WHERE l.quote_id = %s ORDER BY l.line_no",
        (quote_id,),
    ).fetchall()
    fields = (
        "line_no",
        "part_name",
        "quantity",
        "material_code",
        "material_name",
        "material_as_written",
        "grams_per_part",
        "minutes_per_part",
        "post_processing",
        "sources",
        "uncertain",
    )
    return [QuoteLineOut.model_validate(dict(zip(fields, r, strict=True))) for r in rows]


def get_quote(conn: psycopg.Connection, actor: Actor, quote_number: str) -> QuoteDetail:
    (
        qid,
        customer_id,
        number,
        status,
        ccode,
        cname,
        received,
        submitter,
        message,
        due_date,
        due_rule,
        rush,
        notes,
        missing,
        questions,
        requests,
        price,
        _total,
        order_number,
        ai_outcome,
        ai_model,
        ai_prompt,
        ai_cost,
        ai_latency,
    ) = _find(conn, actor, quote_number)
    target = OrderTarget(customer_id)
    staff_view = can(actor, "quote.edit", target) or can(actor, "price_rules.read")
    lines = _lines(conn, qid)
    if not staff_view:
        # Customers see what they asked for, not the shop's working numbers.
        lines = [
            line.model_copy(update={"grams_per_part": None, "minutes_per_part": None})
            for line in lines
        ]
    show_price = (
        price is not None and "pending" not in price and (staff_view or status == "approved")
    )
    return QuoteDetail(
        quote_number=number,
        status=status,
        customer_code=ccode,
        customer_name=cname,
        received_at=received,
        submitted_by_name=submitter,
        message=message,
        due_date=due_date,
        due_rule=due_rule,
        rush=rush,
        notes=notes,
        lines=lines,
        missing=missing,
        questions_for_customer=questions,
        requests_for_staff=requests if staff_view else None,
        price=PriceOut.model_validate(price) if show_price else None,
        price_pending=(price or {}).get("pending", []) if staff_view else [],
        ai=AiInfo(
            outcome=ai_outcome,
            model=ai_model,
            prompt_version=ai_prompt,
            cost_micro_usd=ai_cost,
            latency_ms=ai_latency,
        )
        if staff_view and ai_outcome is not None
        else None,
        order_number=order_number,
        can_edit=status == "draft" and can(actor, "quote.edit", target),
        can_decide=status == "draft" and can(actor, "quote.approve", target),
    )


def list_quotes(conn: psycopg.Connection, actor: Actor) -> list[QuoteSummary]:
    if not can(actor, "quote.list"):
        raise ForbiddenError("quote.list")
    scope = order_scope(actor)
    staff_view = can(actor, "price_rules.read")
    rows = conn.execute(
        "SELECT q.quote_number, q.status, c.code, c.name, r.received_at,"
        "       (SELECT count(*) FROM quote_lines l WHERE l.quote_id = q.id)::int,"
        "       q.total_cents, jsonb_array_length(q.missing)"
        " FROM quotes q JOIN customers c ON c.id = q.customer_id JOIN quote_requests r ON r.id = q.request_id"
        " WHERE (%(s)s::bigint IS NULL OR q.customer_id = %(s)s::bigint)"
        " ORDER BY q.id DESC",
        {"s": scope},
    ).fetchall()
    return [
        QuoteSummary(
            quote_number=r[0],
            status=r[1],
            customer_code=r[2],
            customer_name=r[3],
            received_at=r[4],
            line_count=r[5],
            total_cents=r[6] if staff_view or r[1] == "approved" else None,
            missing_count=r[7],
        )
        for r in rows
    ]


# --- Writes -----------------------------------------------------------------------------------


def _customer(
    conn: psycopg.Connection, actor: Actor, code: str, action: Literal["quote.submit"]
) -> int:
    row = conn.execute("SELECT id FROM customers WHERE code = %s", (code,)).fetchone()
    if row is None:
        if can(actor, "customer.list"):
            raise InvalidQuoteError(f"unknown customer {code}")
        raise ForbiddenError(action)
    if not can(actor, action, OrderTarget(int(row[0]))):
        raise ForbiddenError(action)
    return int(row[0])


def _key_used(conn: psycopg.Connection, actor: Actor, endpoint: str, key: str) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM idempotency_keys WHERE user_id = %s AND endpoint = %s AND key = %s",
            (actor.user_id, endpoint, key),
        ).fetchone()
        is not None
    )


def submit_request(
    conn: psycopg.Connection,
    actor: Actor,
    body: QuoteRequestIn,
    key: str,
    today: date,
    extractor: Extractor,
) -> tuple[idempotency.StoredResponse, bool]:
    """Store the message, let the model draft a quote, and price what can be priced."""
    customer_id = _customer(conn, actor, body.customer_code, "quote.submit")
    req_hash = idempotency.request_hash(body.model_dump(mode="json"))

    # The model call happens outside the transaction, so no lock is held while it runs. A
    # plain retry with a used key skips the call (and its cost) and replays below.
    result = None if _key_used(conn, actor, SUBMIT_ENDPOINT, key) else extractor(body.message)

    with conn.transaction():
        stored = idempotency.claim(
            conn, user_id=actor.user_id, endpoint=SUBMIT_ENDPOINT, key=key, req_hash=req_hash
        )
        if stored is not None:
            detail = get_quote(conn, actor, str(stored.body["quote_number"]))
            return idempotency.StoredResponse(stored.status, detail.model_dump(mode="json")), True
        if result is None:  # the key was claimed and then rolled back between the two checks
            raise InvalidQuoteError("please retry the request")

        mats = _materials(conn)
        draft = result.value
        call_id = _record_call(conn, result.record, actor)
        request = conn.execute(
            "INSERT INTO quote_requests (customer_id, submitted_by, message) VALUES (%s, %s, %s) RETURNING id",
            (customer_id, actor.user_id, body.message),
        ).fetchone()
        assert request is not None

        lines = lines_from_draft(draft, mats)
        rule = draft.due if draft else None
        due_date = resolve_due(rule, today) if rule else None
        rush = draft.rush_requested if draft else False
        rule_set_id, price = _price(conn, lines, rush, today, mats)
        quote = conn.execute(
            "INSERT INTO quotes (request_id, customer_id, ai_call_id, ai_draft, due_rule, due_date, rush, notes,"
            " missing, questions, requests_for_staff, price_rule_set_id, price)"
            " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id, quote_number",
            (
                request[0],
                customer_id,
                call_id,
                Jsonb(draft.model_dump(mode="json")) if draft else None,
                Jsonb(rule.model_dump(mode="json")) if rule else None,
                due_date,
                rush,
                draft.notes_for_shop if draft else "",
                Jsonb(compute_missing(lines, due_date)),
                Jsonb(draft.questions_for_customer if draft else []),
                Jsonb(draft.requests_for_staff if draft else []),
                rule_set_id,
                Jsonb(price),
            ),
        ).fetchone()
        assert quote is not None
        _write_lines(conn, int(quote[0]), lines, mats)

        detail = get_quote(conn, actor, str(quote[1]))
        audit.record(
            conn,
            actor_user_id=actor.user_id,
            action="quote.create",
            entity_type="quote",
            entity_id=detail.quote_number,
            before=None,
            after={"draft": detail.model_dump(mode="json"), "ai_outcome": result.record.outcome},
            idempotency_key=key,
        )
        response = idempotency.StoredResponse(201, {"quote_number": detail.quote_number})
        idempotency.store(
            conn, user_id=actor.user_id, endpoint=SUBMIT_ENDPOINT, key=key, response=response
        )
        return idempotency.StoredResponse(201, detail.model_dump(mode="json")), False


def _draft_for_change(
    conn: psycopg.Connection,
    actor: Actor,
    quote_number: str,
    action: Literal["quote.edit", "quote.approve"],
) -> QuoteDetail:
    detail = get_quote(conn, actor, quote_number)  # NotFound if not visible at all
    customer_id = conn.execute(
        "SELECT customer_id FROM quotes WHERE quote_number = %s", (quote_number,)
    ).fetchone()
    assert customer_id is not None
    if not can(actor, action, OrderTarget(int(customer_id[0]))):
        raise ForbiddenError(action)
    if detail.status != "draft":
        raise InvalidQuoteError(f"quote {quote_number} is {detail.status} and can no longer change")
    return detail


def _replay(
    conn: psycopg.Connection, actor: Actor, stored: idempotency.StoredResponse, quote_number: str
) -> tuple[idempotency.StoredResponse, bool]:
    detail = get_quote(conn, actor, quote_number)  # today's permissions, not the stored snapshot
    return idempotency.StoredResponse(stored.status, detail.model_dump(mode="json")), True


def edit_quote(
    conn: psycopg.Connection,
    actor: Actor,
    quote_number: str,
    body: QuoteEdit,
    key: str,
    today: date,
) -> tuple[idempotency.StoredResponse, bool]:
    endpoint = f"{EDIT_ENDPOINT}/{quote_number}"
    req_hash = idempotency.request_hash(body.model_dump(mode="json"))
    with conn.transaction():
        stored = idempotency.claim(
            conn, user_id=actor.user_id, endpoint=endpoint, key=key, req_hash=req_hash
        )
        if stored is not None:
            return _replay(conn, actor, stored, quote_number)
        before = _draft_for_change(conn, actor, quote_number, "quote.edit")
        mats = _materials(conn)
        unknown = sorted(
            {
                line.material_code
                for line in body.lines
                if line.material_code and line.material_code not in mats
            }
        )
        if unknown:
            raise InvalidQuoteError(f"unknown material(s): {', '.join(unknown)}")

        old = {line.line_no: line for line in before.lines}
        lines: list[QuoteLineOut] = []
        for n, edit in enumerate(body.lines, start=1):
            prev = old.get(n)

            def source(
                name: str, value: object, previous: object, prev: QuoteLineOut | None = prev
            ) -> Source:
                if value is None:
                    return "missing"
                if prev is not None and value == previous:
                    return prev.sources.get(name, "staff")
                return "staff"

            lines.append(
                QuoteLineOut(
                    line_no=n,
                    part_name=edit.part_name,
                    quantity=edit.quantity,
                    material_code=edit.material_code,
                    material_name=mats[edit.material_code][1] if edit.material_code else None,
                    material_as_written=prev.material_as_written if prev else None,
                    grams_per_part=edit.grams_per_part,
                    minutes_per_part=edit.minutes_per_part,
                    post_processing=list(dict.fromkeys(edit.post_processing)),
                    sources={
                        "part_name": source(
                            "part_name", edit.part_name, prev.part_name if prev else None
                        ),
                        "quantity": source(
                            "quantity", edit.quantity, prev.quantity if prev else None
                        ),
                        "material": source(
                            "material", edit.material_code, prev.material_code if prev else None
                        ),
                        "grams_per_part": source(
                            "grams_per_part",
                            edit.grams_per_part,
                            prev.grams_per_part if prev else None,
                        ),
                        "minutes_per_part": source(
                            "minutes_per_part",
                            edit.minutes_per_part,
                            prev.minutes_per_part if prev else None,
                        ),
                        "post_processing": source(
                            "post_processing",
                            sorted(edit.post_processing),
                            sorted(prev.post_processing) if prev else None,
                        ),
                    },
                    # A field staff have now set is no longer uncertain.
                    uncertain=[
                        u
                        for u in (prev.uncertain if prev else [])
                        if not (
                            u == "quantity" and edit.quantity != (prev.quantity if prev else None)
                        )
                        and not (
                            u == "material"
                            and edit.material_code != (prev.material_code if prev else None)
                        )
                    ],
                )
            )
        rule_set_id, price = _price(conn, lines, body.rush, today, mats)
        conn.execute(
            "UPDATE quotes SET due_date = %s, rush = %s, notes = %s, missing = %s, price_rule_set_id = %s,"
            " price = %s, updated_at = now() WHERE quote_number = %s",
            (
                body.due_date,
                body.rush,
                body.notes,
                Jsonb(compute_missing(lines, body.due_date)),
                rule_set_id,
                Jsonb(price),
                quote_number,
            ),
        )
        qid = conn.execute(
            "SELECT id FROM quotes WHERE quote_number = %s", (quote_number,)
        ).fetchone()
        assert qid is not None
        _write_lines(conn, int(qid[0]), lines, mats)
        after = get_quote(conn, actor, quote_number)
        audit.record(
            conn,
            actor_user_id=actor.user_id,
            action="quote.edit",
            entity_type="quote",
            entity_id=quote_number,
            before=before.model_dump(mode="json"),
            after=after.model_dump(mode="json"),
            idempotency_key=key,
        )
        response = idempotency.StoredResponse(200, {"quote_number": quote_number})
        idempotency.store(
            conn, user_id=actor.user_id, endpoint=endpoint, key=key, response=response
        )
        return idempotency.StoredResponse(200, after.model_dump(mode="json")), False


def decide_quote(
    conn: psycopg.Connection,
    actor: Actor,
    quote_number: str,
    body: QuoteDecision,
    key: str,
    today: date,
) -> tuple[idempotency.StoredResponse, bool]:
    """Approve (creates the order) or reject. Only staff, only drafts, only complete quotes."""
    endpoint = f"{DECIDE_ENDPOINT}/{quote_number}"
    req_hash = idempotency.request_hash(body.model_dump(mode="json"))
    with conn.transaction():
        stored = idempotency.claim(
            conn, user_id=actor.user_id, endpoint=endpoint, key=key, req_hash=req_hash
        )
        if stored is not None:
            return _replay(conn, actor, stored, quote_number)
        before = _draft_for_change(conn, actor, quote_number, "quote.approve")
        row = conn.execute(
            "SELECT id, customer_id FROM quotes WHERE quote_number = %s", (quote_number,)
        ).fetchone()
        assert row is not None
        qid, customer_id = int(row[0]), int(row[1])

        if body.decision == "reject":
            conn.execute(
                "UPDATE quotes SET status = 'rejected', decided_by = %s, decided_at = now(), updated_at = now() WHERE id = %s",
                (actor.user_id, qid),
            )
        else:
            if before.missing:
                raise InvalidQuoteError(
                    "cannot approve while information is missing: " + "; ".join(before.missing)
                )
            assert before.due_date is not None
            if before.due_date < today:
                raise InvalidQuoteError(f"due date {before.due_date} is before today ({today})")
            # Price again with the rules in effect today: approval locks today's price.
            mats = _materials(conn)
            rule_set_id, price = _price(conn, before.lines, before.rush, today, mats)
            if "pending" in price:
                raise InvalidQuoteError("cannot price this quote: " + "; ".join(price["pending"]))
            order_id, _ = orders.insert_order(
                conn,
                customer_id=customer_id,
                due_date=before.due_date,
                rush=before.rush,
                notes=before.notes,
                created_by=actor.user_id,
                jobs=[
                    (line.part_name, line.quantity or 0, mats[line.material_code or ""][0])
                    for line in before.lines
                ],
            )
            conn.execute(
                "UPDATE quotes SET status = 'approved', price_rule_set_id = %s, price = %s, total_cents = %s,"
                " decided_by = %s, decided_at = now(), order_id = %s, updated_at = now() WHERE id = %s",
                (rule_set_id, Jsonb(price), price["total_cents"], actor.user_id, order_id, qid),
            )
        after = get_quote(conn, actor, quote_number)
        audit.record(
            conn,
            actor_user_id=actor.user_id,
            action=f"quote.{body.decision}",
            entity_type="quote",
            entity_id=quote_number,
            before=before.model_dump(mode="json"),
            after=after.model_dump(mode="json"),
            idempotency_key=key,
        )
        response = idempotency.StoredResponse(200, {"quote_number": quote_number})
        idempotency.store(
            conn, user_id=actor.user_id, endpoint=endpoint, key=key, response=response
        )
        return idempotency.StoredResponse(200, after.model_dump(mode="json")), False
