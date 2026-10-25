"""Quote routes. Permission checks live in brimline_engine.quotes; these only translate."""

from datetime import date, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Path, Response

from brimline_engine import quotes
from brimline_engine.ai.clients import client_for
from brimline_engine.ai.gateway import GatewayResult
from brimline_engine.api.deps import Conn, CurrentSettings, CurrentUser, IdempotencyKey, Now
from brimline_engine.dates import shop_today
from brimline_engine.idempotency import IdempotencyConflictError, StoredResponse
from brimline_engine.quote_extract import QuoteDraft, extract
from brimline_engine.shop_config import load_shop_config

router = APIRouter(tags=["quotes"])

QuoteNumber = Annotated[str, Path(pattern=r"^Q-[0-9]{4,10}$")]

ERRORS: dict[type[Exception], tuple[int, str | None]] = {
    quotes.NotFoundError: (404, "quote not found"),
    quotes.ForbiddenError: (403, "not allowed"),
    quotes.InvalidQuoteError: (422, None),
    IdempotencyConflictError: (
        409,
        "this Idempotency-Key was already used for a different request",
    ),
}


def _http_error(exc: Exception) -> HTTPException:
    status, message = ERRORS[type(exc)]
    return HTTPException(status, message or str(exc))


def get_extractor(conn: Conn, settings: CurrentSettings) -> quotes.Extractor:
    """Reads a message with the model chosen by AI_MODE. Overridden in tests."""
    catalog = [
        (code, name)
        for code, name in conn.execute("SELECT code, name FROM materials ORDER BY code")
    ]
    client = client_for(settings.ai_mode)

    def run(message: str) -> GatewayResult[QuoteDraft]:
        return extract(client, mode=settings.ai_mode, message=message, catalog=catalog)

    return run


def _reply(response: Response, stored: StoredResponse, replayed: bool) -> dict[str, Any]:
    response.status_code = stored.status
    if replayed:
        response.headers["Idempotent-Replayed"] = "true"
    body: dict[str, Any] = stored.body
    return body


def _today(now: datetime) -> date:
    return shop_today(now, load_shop_config().shop.time_zone)


@router.post("/quote-requests", status_code=201, response_model=quotes.QuoteDetail)
def submit_quote_request(
    body: quotes.QuoteRequestIn,
    response: Response,
    conn: Conn,
    user: CurrentUser,
    now: Now,
    idempotency_key: IdempotencyKey,
    extractor: Annotated[quotes.Extractor, Depends(get_extractor)],
) -> dict[str, Any]:
    try:
        stored, replayed = quotes.submit_request(
            conn, user.actor, body, idempotency_key, _today(now), extractor
        )
    except tuple(ERRORS) as exc:
        raise _http_error(exc) from None
    return _reply(response, stored, replayed)


@router.get("/quotes")
def list_quotes(conn: Conn, user: CurrentUser) -> list[quotes.QuoteSummary]:
    try:
        return quotes.list_quotes(conn, user.actor)
    except tuple(ERRORS) as exc:
        raise _http_error(exc) from None


@router.get("/quotes/{quote_number}")
def get_quote(quote_number: QuoteNumber, conn: Conn, user: CurrentUser) -> quotes.QuoteDetail:
    try:
        return quotes.get_quote(conn, user.actor, quote_number)
    except tuple(ERRORS) as exc:
        raise _http_error(exc) from None


@router.put("/quotes/{quote_number}", response_model=quotes.QuoteDetail)
def edit_quote(
    quote_number: QuoteNumber,
    body: quotes.QuoteEdit,
    response: Response,
    conn: Conn,
    user: CurrentUser,
    now: Now,
    idempotency_key: IdempotencyKey,
) -> dict[str, Any]:
    try:
        stored, replayed = quotes.edit_quote(
            conn, user.actor, quote_number, body, idempotency_key, _today(now)
        )
    except tuple(ERRORS) as exc:
        raise _http_error(exc) from None
    return _reply(response, stored, replayed)


@router.post("/quotes/{quote_number}/decision", response_model=quotes.QuoteDetail)
def decide_quote(
    quote_number: QuoteNumber,
    body: quotes.QuoteDecision,
    response: Response,
    conn: Conn,
    user: CurrentUser,
    now: Now,
    idempotency_key: IdempotencyKey,
) -> dict[str, Any]:
    """Approve (creates the order) or reject. A human decision, enforced here (hard rule 7)."""
    try:
        stored, replayed = quotes.decide_quote(
            conn, user.actor, quote_number, body, idempotency_key, _today(now)
        )
    except tuple(ERRORS) as exc:
        raise _http_error(exc) from None
    return _reply(response, stored, replayed)
