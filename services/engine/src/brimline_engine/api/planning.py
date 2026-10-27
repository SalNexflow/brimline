"""Board, planning, approval and operator routes. The rules live in brimline_engine.planning;
these only translate. Writes need an Idempotency-Key and are audit-logged."""

from collections.abc import Callable
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Path, Request, Response
from psycopg_pool import ConnectionPool

from brimline_engine.api.deps import Conn, CurrentUser, IdempotencyKey, Now
from brimline_engine.idempotency import IdempotencyConflictError, StoredResponse
from brimline_engine.planning import queues, runs, schedules
from brimline_engine.scheduling.config import SchedulerConfig, scheduler_config
from brimline_engine.shop_config import load_shop_config

router = APIRouter(tags=["planning"])

ERRORS: dict[type[Exception], int] = {
    runs.NotFoundError: 404,
    runs.ForbiddenError: 403,
    schedules.NotFoundError: 404,
    schedules.ForbiddenError: 403,
    schedules.ConflictError: 409,
    schedules.RefusedError: 422,
    queues.NotFoundError: 404,
    queues.ForbiddenError: 403,
    queues.ConflictError: 409,
    IdempotencyConflictError: 409,
}
MESSAGES = {404: "not found", 403: "not allowed"}


def _http_error(exc: Exception) -> HTTPException:
    status = ERRORS[type(exc)]
    if isinstance(exc, IdempotencyConflictError):
        return HTTPException(409, "this Idempotency-Key was already used for a different request")
    return HTTPException(status, MESSAGES.get(status, str(exc)))


def shop_tz() -> str:
    return load_shop_config().shop.time_zone


def planning_runner(request: Request) -> runs.Runner:
    """Hands a run to the engine's planning worker (one thread). Tests replace this with one
    that runs it at once."""
    pool: ConnectionPool = request.app.state.pool

    def submit(run_id: int, now: datetime) -> None:
        request.app.state.planning_executor.submit(
            runs.execute_run, pool, run_id, now, scheduler_config(), shop_tz()
        )

    return submit


Config = Annotated[SchedulerConfig, Depends(scheduler_config)]
Tz = Annotated[str, Depends(shop_tz)]
Runner = Annotated[Callable[[int, datetime], None], Depends(planning_runner)]
Id = Annotated[int, Path(ge=1)]


def _write(response: Response, stored: StoredResponse, replayed: bool) -> dict[str, Any]:
    response.status_code = stored.status
    if replayed:
        response.headers["Idempotent-Replayed"] = "true"
    body: dict[str, Any] = stored.body
    return body


@router.get("/board")
def get_board(conn: Conn, user: CurrentUser, now: Now, cfg: Config, tz: Tz) -> schedules.BoardOut:
    try:
        return schedules.get_board(conn, user.actor, now, cfg, tz)
    except tuple(ERRORS) as exc:
        raise _http_error(exc) from None


@router.get("/schedules/{schedule_id}")
def get_schedule(
    schedule_id: Id, conn: Conn, user: CurrentUser, now: Now, cfg: Config, tz: Tz
) -> schedules.ScheduleOut:
    try:
        return schedules.get_schedule(conn, user.actor, schedule_id, now, cfg, tz)
    except tuple(ERRORS) as exc:
        raise _http_error(exc) from None


@router.post("/planning-runs", status_code=202)
def start_planning(
    conn: Conn, user: CurrentUser, now: Now, key: IdempotencyKey, runner: Runner
) -> runs.PlanningRun:
    """Plan day. Returns at once with a run to poll; the solve happens in the background."""
    try:
        run, created = runs.start_run(conn, user.actor, key)
    except tuple(ERRORS) as exc:
        raise _http_error(exc) from None
    if created:
        runner(run.id, now)
    return run


@router.get("/planning-runs/{run_id}")
def get_planning_run(run_id: Id, conn: Conn, user: CurrentUser) -> runs.PlanningRun:
    try:
        return runs.get_run(conn, user.actor, run_id)
    except tuple(ERRORS) as exc:
        raise _http_error(exc) from None


@router.post(
    "/schedules/{schedule_id}/approve",
    response_model=schedules.Decision,
    responses={409: {"description": "not a draft"}, 422: {"description": "refused by the rules"}},
)
def approve_schedule(
    schedule_id: Id,
    response: Response,
    conn: Conn,
    user: CurrentUser,
    now: Now,
    key: IdempotencyKey,
    cfg: Config,
    tz: Tz,
) -> dict[str, Any]:
    try:
        stored, replayed = schedules.approve(conn, user.actor, schedule_id, key, now, cfg, tz)
    except tuple(ERRORS) as exc:
        raise _http_error(exc) from None
    return _write(response, stored, replayed)


@router.post(
    "/schedules/{schedule_id}/discard",
    response_model=schedules.Decision,
    responses={409: {"description": "not a draft"}},
)
def discard_schedule(
    schedule_id: Id,
    response: Response,
    conn: Conn,
    user: CurrentUser,
    now: Now,
    key: IdempotencyKey,
) -> dict[str, Any]:
    try:
        stored, replayed = schedules.discard(conn, user.actor, schedule_id, key, now)
    except tuple(ERRORS) as exc:
        raise _http_error(exc) from None
    return _write(response, stored, replayed)


@router.get("/queues")
def get_queues(conn: Conn, user: CurrentUser, tz: Tz) -> queues.QueuesOut:
    try:
        return queues.get_queues(conn, user.actor, tz)
    except tuple(ERRORS) as exc:
        raise _http_error(exc) from None


@router.post(
    "/tasks/{task_id}/{action}",
    responses={409: {"description": "not allowed in the task's current state"}},
)
def act_on_task(
    task_id: Id,
    action: queues.TaskAction,
    response: Response,
    conn: Conn,
    user: CurrentUser,
    now: Now,
    key: IdempotencyKey,
) -> dict[str, Any]:
    try:
        stored, replayed = queues.act(conn, user.actor, task_id, action, key, now)
    except tuple(ERRORS) as exc:
        raise _http_error(exc) from None
    return _write(response, stored, replayed)
