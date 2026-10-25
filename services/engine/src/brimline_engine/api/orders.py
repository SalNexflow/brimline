"""Order routes. Permission checks live in brimline_engine.orders; these only translate."""

from typing import Annotated, Any

from fastapi import APIRouter, Header, HTTPException, Response

from brimline_engine import orders
from brimline_engine.api.deps import Conn, CurrentUser, Now
from brimline_engine.dates import shop_today
from brimline_engine.idempotency import IdempotencyConflictError
from brimline_engine.shop_config import load_shop_config

router = APIRouter(tags=["orders"])

# Mapped here so every route answers the same way: 404 hides orders you may not see.
ERRORS: dict[type[Exception], int] = {
    orders.NotFoundError: 404,
    orders.ForbiddenError: 403,
    orders.InvalidOrderError: 422,
    IdempotencyConflictError: 409,
}
MESSAGES = {
    404: "order not found",
    403: "not allowed",
    409: "this Idempotency-Key was already used for a different request",
}


def _http_error(exc: Exception) -> HTTPException:
    status = ERRORS[type(exc)]
    return HTTPException(status, str(exc) if status == 422 else MESSAGES[status])


@router.get("/orders")
def list_orders(conn: Conn, user: CurrentUser) -> list[orders.OrderSummary]:
    try:
        return orders.list_orders(conn, user.actor)
    except tuple(ERRORS) as exc:
        raise _http_error(exc) from None


@router.get("/orders/{order_number}")
def get_order(order_number: str, conn: Conn, user: CurrentUser) -> orders.OrderDetail:
    try:
        return orders.get_order(conn, user.actor, order_number)
    except tuple(ERRORS) as exc:
        raise _http_error(exc) from None


@router.get("/orders/{order_number}/history")
def get_history(order_number: str, conn: Conn, user: CurrentUser) -> list[orders.HistoryEntry]:
    try:
        return orders.get_history(conn, user.actor, order_number)
    except tuple(ERRORS) as exc:
        raise _http_error(exc) from None


@router.post(
    "/orders",
    status_code=201,
    response_model=orders.OrderDetail,
    responses={409: {"description": "Idempotency-Key reused with a different request"}},
)
def create_order(
    body: orders.OrderCreate,
    response: Response,
    conn: Conn,
    user: CurrentUser,
    now: Now,
    idempotency_key: Annotated[str | None, Header()] = None,
) -> dict[str, Any]:
    if idempotency_key is None or not 8 <= len(idempotency_key) <= 200:
        raise HTTPException(400, "an Idempotency-Key header of 8 to 200 characters is required")
    today = shop_today(now, load_shop_config().shop.time_zone)
    try:
        stored, replayed = orders.create_order(conn, user.actor, body, idempotency_key, today)
    except tuple(ERRORS) as exc:
        raise _http_error(exc) from None
    response.status_code = stored.status
    if replayed:
        response.headers["Idempotent-Replayed"] = "true"
    return stored.body
