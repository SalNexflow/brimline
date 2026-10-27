"""Disruption routes (M6). The rules live in brimline_engine.planning.disruptions; these only
translate. Nothing here changes a plan: a confirmed disruption is included in the next plan,
and its effects apply only when a planner approves that plan."""

from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Path, Response

from brimline_engine.ai.clients import client_for
from brimline_engine.ai.config import models_config
from brimline_engine.api.deps import Conn, CurrentSettings, CurrentUser, IdempotencyKey, Now
from brimline_engine.api.planning import Config, Tz
from brimline_engine.idempotency import IdempotencyConflictError, StoredResponse
from brimline_engine.planning import disruptions as d

router = APIRouter(tags=["disruptions"])

ERRORS: dict[type[Exception], int] = {
    d.NotFoundError: 404,
    d.ForbiddenError: 403,
    d.ConflictError: 409,
    d.InvalidError: 422,
    IdempotencyConflictError: 409,
}
Id = Annotated[int, Path(ge=1)]


def _http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, IdempotencyConflictError):
        return HTTPException(409, "this Idempotency-Key was already used for a different request")
    status = ERRORS[type(exc)]
    return HTTPException(status, {404: "not found", 403: "not allowed"}.get(status, str(exc)))


def _write(response: Response, stored: StoredResponse, replayed: bool) -> dict[str, Any]:
    response.status_code = stored.status
    if replayed:
        response.headers["Idempotent-Replayed"] = "true"
    return stored.body


@router.get("/disruptions")
def list_disruptions(conn: Conn, user: CurrentUser) -> list[d.DisruptionOut]:
    try:
        return d.list_open(conn, user.actor)
    except tuple(ERRORS) as exc:
        raise _http_error(exc) from None


@router.post("/disruptions", status_code=201, response_model=d.DisruptionOut)
def read_disruption(
    body: d.MessageIn,
    response: Response,
    conn: Conn,
    user: CurrentUser,
    now: Now,
    key: IdempotencyKey,
    settings: CurrentSettings,
    cfg: Config,
    tz: Tz,
) -> dict[str, Any]:
    """Read a planner's message into events for review. Nothing is planned or changed yet."""
    model = models_config().task("disruption_parse").model
    try:
        stored, replayed = d.read(
            conn,
            user.actor,
            body,
            key,
            now,
            client=client_for(settings.ai_mode, model),
            mode=settings.ai_mode,
            tz=tz,
            shifts=cfg.shifts.weekdays,
        )
    except tuple(ERRORS) as exc:
        raise _http_error(exc) from None
    return _write(response, stored, replayed)


@router.post("/disruptions/by-hand", status_code=201, response_model=d.DisruptionOut)
def enter_disruption(
    body: d.EventsIn,
    response: Response,
    conn: Conn,
    user: CurrentUser,
    now: Now,
    key: IdempotencyKey,
) -> dict[str, Any]:
    try:
        stored, replayed = d.enter(conn, user.actor, body, key, now)
    except tuple(ERRORS) as exc:
        raise _http_error(exc) from None
    return _write(response, stored, replayed)


@router.post("/disruptions/{disruption_id}/confirm", response_model=d.DisruptionOut)
def confirm_disruption(
    disruption_id: Id,
    body: d.EventsIn,
    response: Response,
    conn: Conn,
    user: CurrentUser,
    now: Now,
    key: IdempotencyKey,
) -> dict[str, Any]:
    try:
        stored, replayed = d.confirm(conn, user.actor, disruption_id, body, key, now)
    except tuple(ERRORS) as exc:
        raise _http_error(exc) from None
    return _write(response, stored, replayed)


@router.post("/disruptions/{disruption_id}/dismiss")
def dismiss_disruption(
    disruption_id: Id,
    response: Response,
    conn: Conn,
    user: CurrentUser,
    now: Now,
    key: IdempotencyKey,
) -> dict[str, Any]:
    try:
        stored, replayed = d.dismiss(conn, user.actor, disruption_id, key, now)
    except tuple(ERRORS) as exc:
        raise _http_error(exc) from None
    return _write(response, stored, replayed)
