"""HTTP entry point. Later milestones add scheduler, checker, and file-checker routes."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI
from psycopg_pool import ConnectionPool
from pydantic import BaseModel

from brimline_engine.api import auth, orders, price_rules, reference
from brimline_engine.settings import get_settings


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Autocommit: each `with conn.transaction()` is then a real transaction, not a savepoint
    # inside an implicit one, so locks and commits happen exactly where the code says.
    pool = ConnectionPool(
        get_settings().database_url, min_size=1, max_size=10, kwargs={"autocommit": True}, open=True
    )
    app.state.pool = pool
    try:
        yield
    finally:
        pool.close()


app = FastAPI(title="Brimline engine", version="0.0.0", lifespan=lifespan)
app.include_router(auth.router)
app.include_router(orders.router)
app.include_router(reference.router)
app.include_router(price_rules.router)


class Health(BaseModel):
    status: Literal["ok"]
    service: Literal["engine"]


@app.get("/health")
def health() -> Health:
    # The web app and CI use this to know the engine is up before calling it.
    return Health(status="ok", service="engine")
