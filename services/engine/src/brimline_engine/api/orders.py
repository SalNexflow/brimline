"""Order routes. Permission checks live in brimline_engine.orders; these only translate."""

from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Path, Response

from brimline_engine import orders
from brimline_engine.api.deps import Conn, CurrentUser, IdempotencyKey, Now
from brimline_engine.dates import shop_today
from brimline_engine.idempotency import IdempotencyConflictError
from brimline_engine.shop_config import load_shop_config
from brimline_engine.text import ORDER_NUMBER_PATTERN

router = APIRouter(tags=["orders"])

# Anything that cannot be an order number is rejected (422) before it reaches SQL.
OrderNumber = Annotated[str, Path(pattern=ORDER_NUMBER_PATTERN)]

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
def get_order(order_number: OrderNumber, conn: Conn, user: CurrentUser) -> orders.OrderDetail:
    try:
        return orders.get_order(conn, user.actor, order_number)
    except tuple(ERRORS) as exc:
        raise _http_error(exc) from None


@router.get("/orders/{order_number}/history")
def get_history(
    order_number: OrderNumber, conn: Conn, user: CurrentUser
) -> list[orders.HistoryEntry]:
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
    idempotency_key: IdempotencyKey,
) -> dict[str, Any]:
    today = shop_today(now, load_shop_config().shop.time_zone)
    try:
        stored, replayed = orders.create_order(conn, user.actor, body, idempotency_key, today)
    except tuple(ERRORS) as exc:
        raise _http_error(exc) from None
    response.status_code = stored.status
    if replayed:
        response.headers["Idempotent-Replayed"] = "true"
    return stored.body
