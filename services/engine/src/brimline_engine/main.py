"""HTTP entry point."""

import hmac
import re
from collections.abc import AsyncIterator, Awaitable, Callable
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from psycopg_pool import ConnectionPool
from pydantic import BaseModel

from brimline_engine.ai.guard import REPLAYED, VISITOR, visitor_hash
from brimline_engine.api import (
    auth,
    disruptions,
    files,
    materials,
    orders,
    planning,
    price_rules,
    quotes,
    reference,
    reports,
    search,
)
from brimline_engine.api.deps import Conn
from brimline_engine.demo import DemoStatus, StorageFullError, check_storage, status
from brimline_engine.planning.runs import SHUTDOWN, recover_interrupted
from brimline_engine.settings import get_settings


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Autocommit: each `with conn.transaction()` is then a real transaction, not a savepoint
    # inside an implicit one, so locks and commits happen exactly where the code says.
    pool = ConnectionPool(
        get_settings().database_url, min_size=1, max_size=10, kwargs={"autocommit": True}, open=True
    )
    app.state.pool = pool
    # Plan day runs here, one at a time, so a long solve never blocks a request (D68).
    app.state.planning_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="planning")
    SHUTDOWN.requested.clear()  # a fresh start (tests start the app more than once)
    with pool.connection() as conn:
        recover_interrupted(conn)
    try:
        yield
    finally:
        # Stop a search in progress, let the run record that, then close the database pool.
        SHUTDOWN.request()
        app.state.planning_executor.shutdown(wait=True, cancel_futures=True)
        pool.close()


app = FastAPI(title="Brimline engine", version="0.0.0", lifespan=lifespan)
app.include_router(auth.router)
app.include_router(orders.router)
app.include_router(reference.router)
app.include_router(price_rules.router)
app.include_router(quotes.router)
app.include_router(planning.router)
app.include_router(disruptions.router)
app.include_router(files.router)
app.include_router(search.router)
app.include_router(reports.router)
app.include_router(materials.router)

CallNext = Callable[[Request], Awaitable[Response]]
WRITES = {"POST", "PUT", "PATCH", "DELETE"}


def _check_size(request: Request) -> None:
    with request.app.state.pool.connection() as conn:
        check_storage(conn, None)


VISITOR_ID = re.compile(r"^[0-9a-f]{16}$")


@app.middleware("http")
async def web_key_and_visitor(request: Request, call_next: CallNext) -> Response:
    """With ENGINE_WEB_KEY set (the hosted demo), only the web may call the engine, and only
    then is its visitor id believed. The visitor id is a keyed hash, never an address."""
    settings = get_settings()
    address = request.client.host if request.client else "unknown"
    key = settings.engine_web_key
    if key is None:
        visitor = visitor_hash(address, settings.session_secret.get_secret_value())
    else:
        sent = request.headers.get("x-engine-key", "")
        # Bytes, so a header with any characters is refused, never a crash (review of M11).
        if request.url.path != "/health" and not hmac.compare_digest(
            sent.encode("utf-8", "replace"), key.get_secret_value().encode("utf-8")
        ):
            return JSONResponse({"detail": "not allowed"}, status_code=401)
        claimed = request.headers.get("x-visitor", "")
        visitor = (
            claimed if VISITOR_ID.match(claimed) else visitor_hash(address, key.get_secret_value())
        )
    if settings.demo_mode and request.method in WRITES:
        # The hosted demo's size cap, before any write route runs (row caps are per route).
        try:
            await run_in_threadpool(_check_size, request)
        except StorageFullError as e:
            return JSONResponse({"detail": str(e)}, status_code=503)
    token, replayed = VISITOR.set(visitor), REPLAYED.set(False)
    try:
        return await call_next(request)
    finally:
        VISITOR.reset(token)
        REPLAYED.reset(replayed)


@app.exception_handler(StorageFullError)
def storage_full(_request: Request, exc: StorageFullError) -> JSONResponse:
    return JSONResponse({"detail": str(exc)}, status_code=503)


@app.get("/demo-status")
def demo_status(conn: Conn) -> DemoStatus:
    """What the hosted demo limits now (all off locally): for the banner and the board label."""
    return status(conn, VISITOR.get())


class Health(BaseModel):
    status: Literal["ok"]
    service: Literal["engine"]


@app.get("/health")
def health() -> Health:
    # The web app and CI use this to know the engine is up before calling it.
    return Health(status="ok", service="engine")
