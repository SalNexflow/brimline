"""Plan day, in the background (D68).

A request only records a planning run and hands its id to one worker thread; the board polls the
run's row for its phase and progress. The worker builds the instance from the database, solves
with CP-SAT (hinted with EDD, full time limit), runs the independent checker on the saved
document, and stores the result as a draft schedule. Only one run is active at a time (a partial
unique index); asking again while one runs returns the running one.
"""

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any, Literal

import psycopg
from ortools.sat.python import cp_model
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool
from pydantic import BaseModel

from brimline_engine import audit, idempotency
from brimline_engine.ai.calls import record_call
from brimline_engine.ai.clients import client_for
from brimline_engine.ai.config import models_config
from brimline_engine.checker import check_document
from brimline_engine.disruption_parse import Event, describe
from brimline_engine.permissions import Actor, can
from brimline_engine.planning.inputs import build_inputs
from brimline_engine.planning.replan import compute_diff, summarize
from brimline_engine.scheduling.baselines import edd
from brimline_engine.scheduling.config import SchedulerConfig
from brimline_engine.scheduling.cpsat import Progress, solve
from brimline_engine.scheduling.export import document
from brimline_engine.settings import get_settings

START_ENDPOINT = "POST /planning-runs"
PROGRESS_EVERY_SECONDS = 0.5  # at most this often a progress write to the database

Runner = Callable[[int, datetime], None]  # (run id, the moment of planning)

log = logging.getLogger(__name__)


class _Shutdown:
    """Lets the engine stop a running search when it shuts down, instead of waiting for it."""

    def __init__(self) -> None:
        self.requested = threading.Event()
        self._lock = threading.Lock()
        self._solver: cp_model.CpSolver | None = None

    def track(self, solver: cp_model.CpSolver | None) -> None:
        with self._lock:
            self._solver = solver
            if solver is not None and self.requested.is_set():
                solver.stop_search()

    def request(self) -> None:
        with self._lock:
            self.requested.set()
            if self._solver is not None:
                self._solver.stop_search()


SHUTDOWN = _Shutdown()


class InterruptedRunError(Exception):
    pass


class ForbiddenError(Exception):
    pass


class NotFoundError(Exception):
    pass


RunStatus = Literal["queued", "running", "done", "failed"]


class PlanningRun(BaseModel):
    id: int
    status: RunStatus
    phase: str
    progress: dict[str, Any]
    error: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    schedule_id: int | None


_COLUMNS = "id, status, phase, progress, error, created_at, started_at, finished_at, schedule_id"


def _run(conn: psycopg.Connection, run_id: int) -> PlanningRun:
    row = conn.execute(f"SELECT {_COLUMNS} FROM planning_runs WHERE id = %s", (run_id,)).fetchone()
    if row is None:
        raise NotFoundError(str(run_id))
    return PlanningRun(**dict(zip(_COLUMNS.split(", "), row, strict=True)))


def get_run(conn: psycopg.Connection, actor: Actor, run_id: int) -> PlanningRun:
    if not can(actor, "schedule.read"):
        raise ForbiddenError("schedule.read")
    return _run(conn, run_id)


def latest_run(conn: psycopg.Connection, actor: Actor) -> PlanningRun | None:
    if not can(actor, "schedule.read"):
        raise ForbiddenError("schedule.read")
    row = conn.execute("SELECT max(id) FROM planning_runs").fetchone()
    return None if row is None or row[0] is None else _run(conn, int(row[0]))


def start_run(conn: psycopg.Connection, actor: Actor, key: str) -> tuple[PlanningRun, bool]:
    """Record a run. Returns (run, created): created is False when one was already active (or
    this is a replay); then nothing new must be started."""
    if not can(actor, "schedule.plan"):
        raise ForbiddenError("schedule.plan")
    with conn.transaction():
        stored = idempotency.claim(
            conn, user_id=actor.user_id, endpoint=START_ENDPOINT, key=key, req_hash="plan-day"
        )
        if stored is not None:
            return _run(conn, int(stored.body["id"])), False
        # The partial unique index allows one active run; ON CONFLICT turns a second into a no-op.
        row = conn.execute(
            "INSERT INTO planning_runs (requested_by) VALUES (%s)"
            " ON CONFLICT ((true)) WHERE status IN ('queued', 'running') DO NOTHING RETURNING id",
            (actor.user_id,),
        ).fetchone()
        created = row is not None
        if row is None:
            row = conn.execute(
                "SELECT id FROM planning_runs WHERE status IN ('queued', 'running')"
            ).fetchone()
            assert row is not None, "the conflicting active run must exist"
        run = _run(conn, int(row[0]))
        idempotency.store(
            conn,
            user_id=actor.user_id,
            endpoint=START_ENDPOINT,
            key=key,
            response=idempotency.StoredResponse(202, run.model_dump(mode="json")),
        )
        return run, created


def recover_interrupted(conn: psycopg.Connection) -> int:
    """At engine start: a run still queued or running was cut off by a restart. Say so instead
    of letting the board wait forever."""
    rows = conn.execute(
        "UPDATE planning_runs SET status = 'failed', phase = 'failed', finished_at = now(),"
        " error = 'the engine restarted while this run was in progress; plan again'"
        " WHERE status IN ('queued', 'running') RETURNING id"
    ).fetchall()
    return len(rows)


def _update(pool: ConnectionPool, run_id: int, **fields: object) -> None:
    sets = ", ".join(f"{name} = %s" for name in fields)
    values = [Jsonb(v) if isinstance(v, dict) else v for v in fields.values()]
    with pool.connection() as conn:
        conn.execute(f"UPDATE planning_runs SET {sets} WHERE id = %s", (*values, run_id))


def execute_run(
    pool: ConnectionPool,
    run_id: int,
    now: datetime,
    cfg: SchedulerConfig,
    tz: str,
    *,
    deterministic_time: float | None = None,
) -> None:
    """The background part. Never raises: a failure is written to the run for the board, and
    if even that fails (the database is gone), it is logged and the next engine start marks the
    run failed (recover_interrupted)."""
    try:
        _execute(pool, run_id, now, cfg, tz, deterministic_time)
    except Exception as exc:  # the board must learn about any failure, so catch everything
        try:
            mark_failed(pool, run_id, str(exc))
        except Exception:
            log.exception("planning run %s failed and could not be marked failed", run_id)


def mark_failed(pool: ConnectionPool, run_id: int, error: str) -> None:
    _update(
        pool,
        run_id,
        status="failed",
        phase="failed",
        error=error[:500],
        finished_at=datetime.now(UTC),
    )


def _execute(
    pool: ConnectionPool,
    run_id: int,
    now: datetime,
    cfg: SchedulerConfig,
    tz: str,
    deterministic_time: float | None,
) -> None:
    started = time.monotonic()
    # The run's own times are real clock times; the plan is made "as of" `now`.
    _update(pool, run_id, status="running", phase="building", started_at=datetime.now(UTC))
    with pool.connection() as conn:
        inputs = build_inputs(conn, now, cfg, tz)
        requested_by = conn.execute(
            "SELECT requested_by FROM planning_runs WHERE id = %s", (run_id,)
        ).fetchone()
    assert requested_by is not None
    inst = inputs.instance

    _update(
        pool,
        run_id,
        phase="solving",
        progress={
            "jobs": len(inst.jobs),
            "unplannable": len(inputs.unplannable),
            # The quality limit, from config: shown on the board instead of a typed-in number.
            "limit_seconds": deterministic_time or cfg.solver.deterministic_time_seconds,
        },
    )
    last = 0.0

    def report(p: Progress) -> None:
        nonlocal last
        if time.monotonic() - last >= PROGRESS_EVERY_SECONDS:
            last = time.monotonic()
            _update(
                pool,
                run_id,
                progress={
                    "jobs": len(inst.jobs),
                    "limit_seconds": deterministic_time or cfg.solver.deterministic_time_seconds,
                    **asdict(p),
                },
            )

    hint = edd(inst, cfg.durations)
    try:
        schedule = solve(
            inst,
            cfg,
            hint=hint,
            deterministic_time=deterministic_time,
            on_progress=report,
            on_start=SHUTDOWN.track,
        )
    finally:
        SHUTDOWN.track(None)
    if SHUTDOWN.requested.is_set():
        raise InterruptedRunError("the engine shut down during planning; plan again")

    _update(pool, run_id, phase="checking")
    doc = document(inst, schedule)
    result = check_document(doc)  # the independent checker, on exactly what is saved

    # What changes against the approved plan, computed by code; then a summary of that only.
    _update(pool, run_id, phase="comparing")
    with pool.connection() as conn:
        before = (
            conn.execute(
                "SELECT document, anchor FROM schedules WHERE id = %s", (inputs.previous_id,)
            ).fetchone()
            if inputs.previous_id is not None
            else None
        )
        events = [
            describe(Event.model_validate(e), tz)
            for (evs,) in conn.execute(
                "SELECT events FROM disruptions WHERE id = ANY(%s) ORDER BY id",
                (list(inputs.disruption_ids),),
            ).fetchall()
            for e in evs
        ]
    diff = compute_diff(
        before=None if before is None else before[0],
        before_anchor=None if before is None else before[1],
        before_check=None if before is None else check_document(before[0]),
        after=doc,
        after_anchor=inputs.anchor,
        after_check=result,
        tz=tz,
        refs=inputs.refs,
        effects=inputs.effects,
        events=events,
    )
    mode = get_settings().ai_mode
    summary_model = models_config().task("replan_summary").model
    summary, call = summarize(client_for(mode, summary_model), mode=mode, diff=diff)

    with pool.connection() as conn, conn.transaction():
        # A new draft replaces an older one: there is only ever one plan waiting for approval.
        for (version,) in conn.execute(
            "UPDATE schedules SET status = 'discarded', decided_by = %s, decided_at = %s"
            " WHERE status = 'draft' RETURNING version",
            (requested_by[0], now),
        ).fetchall():
            audit.record(
                conn,
                actor_user_id=int(requested_by[0]),
                action="schedule.discard",
                entity_type="schedule",
                entity_id=str(version),
                before={"status": "draft"},
                after={"status": "discarded", "reason": "replaced by a newer plan"},
                idempotency_key=None,
            )
        call_id = None if call is None else record_call(conn, call, int(requested_by[0]))
        row = conn.execute(
            "INSERT INTO schedules (run_id, anchor, document, fingerprint, solver_info,"
            " unplannable, created_by, created_at, previous_id, disruption_ids, effects, diff,"
            " summary, summary_ai_call_id)"
            " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"
            " RETURNING id, version",
            (
                run_id,
                inputs.anchor,
                Jsonb(doc),
                inputs.fingerprint,
                Jsonb({"method": schedule.method, **schedule.info}),
                Jsonb(inputs.unplannable),
                requested_by[0],
                now,
                inputs.previous_id,
                list(inputs.disruption_ids),
                Jsonb(inputs.effects.as_dict()),
                Jsonb(diff),
                Jsonb(summary),
                call_id,
            ),
        ).fetchone()
        assert row is not None
        schedule_id, version = int(row[0]), int(row[1])
        audit.record(
            conn,
            actor_user_id=int(requested_by[0]),
            action="schedule.plan",
            entity_type="schedule",
            entity_id=str(version),
            before=None,
            after={
                "status": "draft",
                "jobs": len(inst.jobs),
                "unscheduled": list(schedule.unscheduled),
                "check_valid": result.valid,
            },
            idempotency_key=None,
        )
        conn.execute(
            "UPDATE planning_runs SET status = 'done', phase = 'done', schedule_id = %s,"
            " finished_at = now(), progress = progress || %s WHERE id = %s",
            (
                schedule_id,
                Jsonb(
                    {
                        "check_valid": result.valid,
                        "seconds": round(time.monotonic() - started, 1),
                    }
                ),
                run_id,
            ),
        )
