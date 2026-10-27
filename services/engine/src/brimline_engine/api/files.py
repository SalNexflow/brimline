"""File routes (M7). The rules live in brimline_engine.files.service; these only translate.

An upload is the raw file as the request body (application/octet-stream) with the target in
the query string, so no multipart library is needed."""

from datetime import date, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Body, HTTPException, Path, Query, Response

from brimline_engine.api.deps import Conn, CurrentUser, IdempotencyKey, Now
from brimline_engine.dates import shop_today
from brimline_engine.files import service as f
from brimline_engine.files.config import files_config
from brimline_engine.idempotency import IdempotencyConflictError, StoredResponse
from brimline_engine.shop_config import load_shop_config

router = APIRouter(tags=["files"])

ERRORS: dict[type[Exception], int] = {
    f.NotFoundError: 404,
    f.ForbiddenError: 403,
    f.ConflictError: 409,
    f.InvalidError: 422,
    IdempotencyConflictError: 409,
}
FileNumber = Annotated[str, Path(pattern=r"^F-[0-9]{4,10}$")]


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


def _today(now: datetime) -> date:
    return shop_today(now, load_shop_config().shop.time_zone)


@router.post("/files", status_code=201, response_model=f.FileOut)
def upload_file(
    data: Annotated[bytes, Body(media_type="application/octet-stream")],
    filename: Annotated[str, Query(min_length=1, max_length=200)],
    line: Annotated[int, Query(ge=1, le=50)],
    response: Response,
    conn: Conn,
    user: CurrentUser,
    now: Now,
    key: IdempotencyKey,
    quote: Annotated[str | None, Query(pattern=r"^Q-[0-9]{4,10}$")] = None,
    order: Annotated[str | None, Query(pattern=r"^BL-[0-9]{4,10}$")] = None,
    unit: Annotated[str, Query(max_length=20)] = "millimeter",
) -> dict[str, Any]:
    """Check a model file and fill the planning fields it can (quote line or job)."""
    try:
        stored, replayed = f.upload(
            conn,
            user.actor,
            f.Target(quote_number=quote, order_number=order, line=line),
            filename,
            unit,
            data,
            key,
            _today(now),
            files_config(),
        )
    except tuple(ERRORS) as exc:
        raise _http_error(exc) from None
    return _write(response, stored, replayed)


@router.get("/files/jobs")
def job_files(conn: Conn, user: CurrentUser) -> dict[str, dict[str, str]]:
    """The latest file of each job, for the board."""
    try:
        return f.latest_job_files(conn, user.actor)
    except tuple(ERRORS) as exc:
        raise _http_error(exc) from None


@router.get("/files/{file_number}")
def read_file(file_number: FileNumber, conn: Conn, user: CurrentUser) -> f.FileOut:
    try:
        return f.get_file(conn, user.actor, file_number)
    except tuple(ERRORS) as exc:
        raise _http_error(exc) from None


@router.post("/files/{file_number}/overrides", response_model=f.FileOut)
def override_warning(
    file_number: FileNumber,
    body: f.OverrideIn,
    response: Response,
    conn: Conn,
    user: CurrentUser,
    now: Now,
    key: IdempotencyKey,
) -> dict[str, Any]:
    """Accept a warning with a reason (logged). A failed check cannot be accepted."""
    try:
        stored, replayed = f.override(
            conn, user.actor, file_number, body, key, _today(now), files_config()
        )
    except tuple(ERRORS) as exc:
        raise _http_error(exc) from None
    return _write(response, stored, replayed)
