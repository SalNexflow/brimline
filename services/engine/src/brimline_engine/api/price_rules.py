"""Price-rule versions. Permission checks live in brimline_engine.price_rules."""

from typing import Any

from fastapi import APIRouter, HTTPException, Response

from brimline_engine import price_rules
from brimline_engine.api.deps import Conn, CurrentUser, IdempotencyKey, Now
from brimline_engine.dates import shop_today
from brimline_engine.idempotency import IdempotencyConflictError
from brimline_engine.shop_config import load_shop_config

router = APIRouter(tags=["price rules"])

ERRORS: dict[type[Exception], tuple[int, str | None]] = {
    price_rules.ForbiddenError: (403, "not allowed"),
    price_rules.InvalidRulesError: (422, None),  # None: the message itself explains the problem
    IdempotencyConflictError: (
        409,
        "this Idempotency-Key was already used for a different request",
    ),
}


def _http_error(exc: Exception) -> HTTPException:
    status, message = ERRORS[type(exc)]
    return HTTPException(status, message or str(exc))


@router.get("/price-rules")
def list_price_rules(conn: Conn, user: CurrentUser) -> list[price_rules.PriceRulesOut]:
    """All versions, newest effective date first."""
    try:
        return price_rules.list_versions(conn, user.actor)
    except tuple(ERRORS) as exc:
        raise _http_error(exc) from None


@router.post("/price-rules", status_code=201, response_model=price_rules.PriceRulesOut)
def create_price_rules(
    body: price_rules.PriceRulesIn,
    response: Response,
    conn: Conn,
    user: CurrentUser,
    now: Now,
    idempotency_key: IdempotencyKey,
) -> dict[str, Any]:
    today = shop_today(now, load_shop_config().shop.time_zone)
    try:
        stored, replayed = price_rules.create_version(
            conn, user.actor, body, idempotency_key, today
        )
    except tuple(ERRORS) as exc:
        raise _http_error(exc) from None
    response.status_code = stored.status
    if replayed:
        response.headers["Idempotent-Replayed"] = "true"
    return stored.body
