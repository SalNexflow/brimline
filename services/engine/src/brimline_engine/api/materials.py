"""Materials routes (M9): stock, purchase orders, shortages and purchase suggestions. The rules
live in brimline_engine.materials; these only translate. Writes need an Idempotency-Key."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Path, Response

from brimline_engine.api.deps import Conn, CurrentUser, IdempotencyKey, Now
from brimline_engine.api.planning import Config, Tz
from brimline_engine.demo import check_storage
from brimline_engine.idempotency import IdempotencyConflictError
from brimline_engine.materials import service
from brimline_engine.materials.config import PurchasingConfig, purchasing_config

router = APIRouter(tags=["materials"])

ERRORS: dict[type[Exception], int] = {
    service.NotFoundError: 404,
    service.ForbiddenError: 403,
    service.ConflictError: 409,
    service.InvalidError: 422,
    IdempotencyConflictError: 409,
}
Purchasing = Annotated[PurchasingConfig, Depends(purchasing_config)]
PoNumber = Annotated[str, Path(pattern=r"^PO-[0-9]{4,10}$")]


def _error(exc: Exception) -> HTTPException:
    status = ERRORS[type(exc)]
    if isinstance(exc, IdempotencyConflictError):
        return HTTPException(409, "this Idempotency-Key was already used for a different request")
    return HTTPException(status, {404: "not found", 403: "not allowed"}.get(status, str(exc)))


@router.get("/stock")
def get_stock(
    conn: Conn, user: CurrentUser, now: Now, cfg: Config, tz: Tz, purchasing: Purchasing
) -> service.MaterialsOut:
    """Stock, purchase orders, and for the approved plan and the newest draft: each material
    that runs short, when, the jobs affected, and what to order by when. Suggestions only."""
    try:
        return service.overview(conn, user.actor, now, tz, cfg.durations, purchasing)
    except tuple(ERRORS) as exc:
        raise _error(exc) from None


@router.post("/purchase-orders", status_code=201)
def record_purchase_order(
    body: service.PurchaseOrderIn,
    response: Response,
    conn: Conn,
    user: CurrentUser,
    now: Now,
    key: IdempotencyKey,
) -> dict[str, Any]:
    """Record an order a person has already placed with a supplier (Brimline never orders)."""
    check_storage(conn, "purchase_orders")  # demo mode only (config/demo.toml)
    try:
        stored, replayed = service.record_purchase_order(conn, user.actor, body, key, now)
    except tuple(ERRORS) as exc:
        raise _error(exc) from None
    response.status_code = stored.status
    if replayed:
        response.headers["Idempotent-Replayed"] = "true"
    return stored.body


@router.post("/purchase-orders/{number}/receive")
def receive_purchase_order(
    number: PoNumber,
    response: Response,
    conn: Conn,
    user: CurrentUser,
    now: Now,
    key: IdempotencyKey,
) -> dict[str, Any]:
    """The delivery arrived: its grams go into stock."""
    try:
        stored, replayed = service.receive_purchase_order(conn, user.actor, number, key, now)
    except tuple(ERRORS) as exc:
        raise _error(exc) from None
    response.status_code = stored.status
    if replayed:
        response.headers["Idempotent-Replayed"] = "true"
    return stored.body
