"""The hosted demo's limits (M11, config/demo.toml), applied only when DEMO_MODE is on.

Locally and in the gate nothing here changes anything: each function returns the normal
config. On the hosted demo: a shorter solver run (labelled on the board), smaller uploads, and
writes refused before the free database fills up."""

from datetime import UTC, datetime

import psycopg
from psycopg import sql
from pydantic import BaseModel

from brimline_engine.ai.guard import demo_config, over_limit, spend
from brimline_engine.demo_clock import shop_time
from brimline_engine.files.config import FilesConfig, files_config
from brimline_engine.scheduling.config import SchedulerConfig, scheduler_config
from brimline_engine.settings import get_settings
from brimline_engine.shop_config import load_shop_config


class StorageFullError(Exception):
    """The demo database is near its size or row cap. The message is shown as is."""


def effective_scheduler_config() -> SchedulerConfig:
    cfg = scheduler_config()
    if not get_settings().demo_mode:
        return cfg
    solver = cfg.solver.model_copy(
        update={"deterministic_time_seconds": demo_config().solver.deterministic_time_seconds}
    )
    return cfg.model_copy(update={"solver": solver})


def effective_files_config() -> FilesConfig:
    cfg = files_config()
    if not get_settings().demo_mode:
        return cfg
    limits = cfg.limits.model_copy(
        update={"max_upload_bytes": demo_config().files.max_upload_bytes}
    )
    return cfg.model_copy(update={"limits": limits})


def check_storage(conn: psycopg.Connection, table: str | None) -> None:
    """Refuse a write that would grow the demo database past its caps. With no table, only the
    size cap (the middleware checks it before every write)."""
    if not get_settings().demo_mode:
        return
    storage = demo_config().storage
    size = conn.execute("SELECT pg_database_size(current_database())").fetchone()
    assert size is not None
    if int(size[0]) > storage.max_database_mb * 1024 * 1024:
        raise StorageFullError("the demo's database is full for today; it resets every night")
    cap = storage.max_rows.get(table) if table else None
    if table is not None and cap is not None:
        # The table name comes from our code, never from a request (fixed list in config).
        row = conn.execute(
            sql.SQL("SELECT count(*) FROM {}").format(sql.Identifier(table))
        ).fetchone()
        assert row is not None
        if int(row[0]) >= cap:
            raise StorageFullError(
                f"the demo holds at most {cap:,} {table.replace('_', ' ')}; it resets every night"
            )


class DemoStatus(BaseModel):
    demo_mode: bool
    solver_seconds: float
    full_solver_seconds: float
    max_upload_bytes: int
    model_limit_reason: str | None  # why live model calls are paused now, if they are
    demo_time: datetime | None  # the shop's pinned clock, when the demo has one ("Demo time")


def status(conn: psycopg.Connection, visitor: str | None) -> DemoStatus:
    settings = get_settings()
    reason = None
    if settings.demo_mode and settings.ai_mode == "live":
        reason = over_limit(spend(conn, visitor), demo_config().budget)
    return DemoStatus(
        demo_mode=settings.demo_mode,
        solver_seconds=effective_scheduler_config().solver.deterministic_time_seconds,
        full_solver_seconds=scheduler_config().solver.deterministic_time_seconds,
        max_upload_bytes=effective_files_config().limits.max_upload_bytes,
        model_limit_reason=reason,
        demo_time=shop_time(
            datetime.now(UTC), settings.demo_clock, load_shop_config().shop.time_zone
        )
        if settings.demo_clock
        else None,
    )
