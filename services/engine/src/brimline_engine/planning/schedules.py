"""Schedules: the board's view of a plan, and approving or discarding it (hard rule 7).

The check badge is always the independent checker run on the saved document, at the time of
reading; nothing the scheduler said about itself is used for it. Approval is enforced here, in
the engine: only a planner, only a draft, only one that passes the checker now, and only if
its inputs have not changed since it was planned. Approval writes the plan's tasks, which is
the only way tasks reach an operator (a database trigger refuses tasks for any other schedule).
"""

from dataclasses import asdict
from datetime import datetime
from typing import Any, Literal

import psycopg
from pydantic import BaseModel

from brimline_engine import audit, idempotency
from brimline_engine.checker import CheckResult, check_document
from brimline_engine.permissions import Actor, can
from brimline_engine.planning.clock import at_minute, minute_at_or_after
from brimline_engine.planning.disruptions import DisruptionOut, list_open
from brimline_engine.planning.inputs import build_inputs, job_key
from brimline_engine.planning.runs import PlanningRun, latest_run
from brimline_engine.scheduling.config import SchedulerConfig

ScheduleStatus = Literal["draft", "approved", "superseded", "discarded"]


class NotFoundError(Exception):
    pass


class ForbiddenError(Exception):
    pass


class ConflictError(Exception):
    """The schedule is not in a state that allows this (409)."""


class RefusedError(Exception):
    """The rules say no: it fails the check, it is stale, or work is in progress (422)."""


# --- Shapes -----------------------------------------------------------------------------------


class CheckIssue(BaseModel):
    code: str
    job: str | None
    detail: str


class CheckOut(BaseModel):
    """The independent checker's verdict on the saved plan, computed when it was read."""

    valid: bool
    violations: list[CheckIssue]
    warnings: list[CheckIssue]
    metrics: dict[str, float] | None


class BoardMachine(BaseModel):
    code: str
    name: str
    process: str


class BoardJob(BaseModel):
    key: str
    order_number: str
    part_name: str
    quantity: int
    material_code: str
    rush: bool
    due: datetime
    completion: datetime | None  # None when unscheduled
    late_minutes: int  # from the checker's deadline report
    unscheduled: bool


class BoardTask(BaseModel):
    task_id: int | None  # set once the plan is approved
    job: str
    kind: str
    machine: str | None  # None for manual work
    start: datetime
    end: datetime
    status: str  # "planned" for a draft; the live status for the approved plan
    actual_start: datetime | None
    actual_end: datetime | None


class TimeWindow(BaseModel):
    start: datetime
    end: datetime


class Unplannable(BaseModel):
    job: str
    part: str
    missing: list[str]


class ScheduleOut(BaseModel):
    id: int
    version: int
    status: ScheduleStatus
    created_at: datetime
    created_by_name: str
    decided_at: datetime | None
    decided_by_name: str | None
    anchor: datetime
    plan_start: datetime
    horizon_end: datetime
    shifts: list[TimeWindow]  # staffed hours over the plan, for shading the board
    stale: bool  # a draft whose inputs changed since it was planned (cannot be approved)
    check: CheckOut
    solver: dict[str, Any]
    machines: list[BoardMachine]
    jobs: list[BoardJob]
    tasks: list[BoardTask]
    unplannable: list[Unplannable]
    can_approve: bool  # for this reader: allowed, a draft, passing, and not stale
    # Re-planning (M6): what changes against the approved plan, computed by code, and the
    # summary written from that diff only (source "ai" or "code").
    diff: dict[str, Any] | None
    summary: dict[str, Any] | None
    disruption_ids: list[int]


class BoardOut(BaseModel):
    time_zone: str  # the shop's; times are UTC, shown in this zone
    draft: ScheduleOut | None
    approved: ScheduleOut | None
    run: PlanningRun | None
    disruptions: list[DisruptionOut]  # waiting for review, or confirmed and not yet applied
    can_plan: bool


class Decision(BaseModel):
    id: int
    version: int
    status: ScheduleStatus


# --- Reading ----------------------------------------------------------------------------------


def _check(doc: dict[str, Any]) -> CheckResult:
    return check_document(doc)


def _check_out(result: CheckResult) -> CheckOut:
    return CheckOut(
        valid=result.valid,
        violations=[CheckIssue(**asdict(v)) for v in result.violations],
        warnings=[CheckIssue(**asdict(v)) for v in result.warnings],
        metrics=None if result.metrics is None else asdict(result.metrics),
    )


_SELECT = (
    "SELECT s.id, s.version, s.status, s.created_at, cu.display_name, s.decided_at,"
    "       du.display_name, s.anchor, s.document, s.fingerprint, s.solver_info, s.unplannable,"
    "       s.diff, s.summary, s.disruption_ids"
    " FROM schedules s JOIN users cu ON cu.id = s.created_by"
    " LEFT JOIN users du ON du.id = s.decided_by"
)


def _schedule_out(
    conn: psycopg.Connection,
    actor: Actor,
    row: tuple[Any, ...],
    now: datetime,
    cfg: SchedulerConfig,
    tz: str,
) -> ScheduleOut:
    sid, version, status, created_at, created_by, decided_at, decided_by, anchor = row[:8]
    doc, fp, solver, unplannable, diff, summary, disruption_ids = row[8:]
    result = _check(doc)
    inst, plan = doc["instance"], doc["plan"]
    stale = status == "draft" and build_inputs(conn, now, cfg, tz).fingerprint != fp

    names: dict[str, str] = dict(conn.execute("SELECT code, name FROM machines").fetchall())
    machines = [
        BoardMachine(code=m["code"], name=names.get(m["code"], m["code"]), process=m["process"])
        for m in inst["machines"]
    ]

    refs = {
        job_key(r[0], r[1]): r
        for r in conn.execute(
            "SELECT o.order_number, j.line_no, j.part_name, j.quantity, mat.code, o.rush"
            " FROM jobs j JOIN orders o ON o.id = j.order_id JOIN materials mat ON mat.id = j.material_id"
            " WHERE (o.order_number || '-' || j.line_no) = ANY(%s)",
            ([j["id"] for j in inst["jobs"]],),
        ).fetchall()
    }
    deadlines = {d.job: d for d in result.deadlines}
    jobs = []
    for j in inst["jobs"]:
        r = refs.get(j["id"])
        d = deadlines.get(j["id"])
        jobs.append(
            BoardJob(
                key=j["id"],
                order_number=r[0] if r else j["id"],
                part_name=r[2] if r else "",
                quantity=j["quantity"],
                material_code=j["material"],
                rush=j["rush"],
                due=at_minute(j["due"], anchor, tz),
                completion=None if d is None else at_minute(d.completion, anchor, tz),
                late_minutes=0 if d is None else d.tardiness,
                unscheduled=j["id"] in plan["unscheduled"],
            )
        )

    live: dict[tuple[str, str], tuple[Any, ...]] = {}
    if status in ("approved", "superseded"):
        for t in conn.execute(
            "SELECT o.order_number, j.line_no, t.kind, t.id, t.status, t.actual_start, t.actual_end"
            " FROM tasks t JOIN jobs j ON j.id = t.job_id JOIN orders o ON o.id = j.order_id"
            " WHERE t.schedule_id = %s",
            (sid,),
        ).fetchall():
            live[(job_key(t[0], t[1]), t[2])] = t[3:]
    tasks = []
    for pj in plan["jobs"]:
        for t in pj["tasks"]:
            lv = live.get((pj["job_id"], t["kind"]))
            tasks.append(
                BoardTask(
                    task_id=None if lv is None else lv[0],
                    job=pj["job_id"],
                    kind=t["kind"],
                    machine=pj["machine"] if t["kind"] == "machine" else None,
                    start=at_minute(t["start"], anchor, tz),
                    end=at_minute(t["end"], anchor, tz),
                    status="planned" if lv is None else lv[1],
                    actual_start=None if lv is None else lv[2],
                    actual_end=None if lv is None else lv[3],
                )
            )
    return ScheduleOut(
        id=sid,
        version=version,
        status=status,
        created_at=created_at,
        created_by_name=created_by,
        decided_at=decided_at,
        decided_by_name=decided_by,
        anchor=anchor,
        plan_start=at_minute(inst.get("plan_start", 0), anchor, tz),
        horizon_end=at_minute(inst["horizon"], anchor, tz),
        shifts=[
            TimeWindow(start=at_minute(lo, anchor, tz), end=at_minute(hi, anchor, tz))
            for lo, hi in inst.get("shifts", [])
        ],
        stale=stale,
        check=_check_out(result),
        solver=solver,
        machines=machines,
        jobs=jobs,
        tasks=tasks,
        unplannable=[Unplannable(**u) for u in unplannable],
        diff=diff,
        summary=summary,
        disruption_ids=list(disruption_ids),
        can_approve=status == "draft"
        and can(actor, "schedule.approve")
        and result.valid
        and not stale,
    )


def get_board(
    conn: psycopg.Connection, actor: Actor, now: datetime, cfg: SchedulerConfig, tz: str
) -> BoardOut:
    if not can(actor, "schedule.read"):
        raise ForbiddenError("schedule.read")
    out: dict[str, ScheduleOut | None] = {"draft": None, "approved": None}
    for status in out:
        row = conn.execute(
            _SELECT + " WHERE s.status = %s ORDER BY s.version DESC LIMIT 1", (status,)
        ).fetchone()
        if row is not None:
            out[status] = _schedule_out(conn, actor, row, now, cfg, tz)
    return BoardOut(
        time_zone=tz,
        draft=out["draft"],
        approved=out["approved"],
        run=latest_run(conn, actor),
        disruptions=list_open(conn, actor) if can(actor, "disruption.report") else [],
        can_plan=can(actor, "schedule.plan"),
    )


def get_schedule(
    conn: psycopg.Connection,
    actor: Actor,
    schedule_id: int,
    now: datetime,
    cfg: SchedulerConfig,
    tz: str,
) -> ScheduleOut:
    if not can(actor, "schedule.read"):
        raise ForbiddenError("schedule.read")
    row = conn.execute(_SELECT + " WHERE s.id = %s", (schedule_id,)).fetchone()
    if row is None:
        raise NotFoundError(str(schedule_id))
    return _schedule_out(conn, actor, row, now, cfg, tz)


# --- Deciding ---------------------------------------------------------------------------------


def _endpoint(schedule_id: int, decision: str) -> str:
    return f"POST /schedules/{schedule_id}/{decision}"


def approve(
    conn: psycopg.Connection,
    actor: Actor,
    schedule_id: int,
    key: str,
    now: datetime,
    cfg: SchedulerConfig,
    tz: str,
) -> tuple[idempotency.StoredResponse, bool]:
    if not can(actor, "schedule.approve"):
        raise ForbiddenError("schedule.approve")
    endpoint = _endpoint(schedule_id, "approve")
    with conn.transaction():
        stored = idempotency.claim(
            conn, user_id=actor.user_id, endpoint=endpoint, key=key, req_hash="approve"
        )
        if stored is not None:
            return stored, True
        # The row lock makes two approvals of one draft take turns: the second sees "approved".
        row = conn.execute(
            "SELECT version, status, document, fingerprint, anchor, effects, disruption_ids"
            " FROM schedules WHERE id = %s FOR UPDATE",
            (schedule_id,),
        ).fetchone()
        if row is None:
            raise NotFoundError(str(schedule_id))
        version, status, doc, fp, anchor, effects, disruption_ids = row
        if status != "draft":
            raise ConflictError(f"schedule {version} is {status}, not a draft")
        result = _check(doc)  # never the stored or reported result: the checker, now
        if not result.valid:
            issues = "; ".join(f"{v.code} ({v.job}): {v.detail}" for v in result.violations[:5])
            raise RefusedError(f"the independent check fails: {issues}")
        if build_inputs(conn, now, cfg, tz).fingerprint != fp:
            raise RefusedError(
                "the plan is stale: jobs or work changed since it was made; plan again"
            )
        # Every task of a non-fixed job must start at or after now: a draft left waiting until
        # its first tasks are in the past is out of date even if nothing else changed.
        fixed_jobs = {f["job_id"] for f in doc["instance"]["fixed"]}
        starts = [
            t["start"]
            for pj in doc["plan"]["jobs"]
            for t in pj["tasks"]
            if not (t["kind"] == "machine" and pj["job_id"] in fixed_jobs)
        ]
        if starts and min(starts) < minute_at_or_after(now, anchor, tz):
            raise RefusedError("the plan starts tasks in the past; plan again")

        # Lock the approved plan before looking at running work: an operator's action holds a
        # share lock on it, so nothing can start between these checks and the hand-over.
        old = conn.execute(
            "SELECT id, version FROM schedules WHERE status = 'approved' FOR UPDATE"
        ).fetchone()
        carried: dict[tuple[int, str], tuple[Any, ...]] = {}
        if old is not None:
            # The disruptions' effects on work in progress, first: a print lost to a machine
            # going down, and running work of a cancelled job, are stopped (marked failed).
            _stop_work(conn, old[0], effects, now)
            planned_keys = {pj["job_id"] for pj in doc["plan"]["jobs"]}
            running = conn.execute(
                "SELECT o.order_number, j.line_no, t.kind, m.code FROM tasks t"
                " JOIN jobs j ON j.id = t.job_id JOIN orders o ON o.id = j.order_id"
                " LEFT JOIN machines m ON m.id = t.machine_id"
                " WHERE t.schedule_id = %s AND t.status = 'running'",
                (old[0],),
            ).fetchall()
            manual = [r for r in running if r[2] != "machine"]
            if manual:
                raise RefusedError(
                    f"{len(manual)} manual task(s) are in progress; finish or fail them first"
                )
            # A running machine task is carried into the new plan as fixed work; one whose job
            # the new plan leaves out (cancelled, or unscheduled) would be orphaned, still
            # printing but in no queue. Refuse instead.
            orphans = [
                f"{job_key(r[0], r[1])} on {r[3]}"
                for r in running
                if job_key(r[0], r[1]) not in planned_keys
            ]
            if orphans:
                raise RefusedError(
                    "running work is not in the new plan: "
                    + ", ".join(orphans)
                    + "; finish or fail it first"
                )
            # Only machine work is carried: it is what the new plan fixed. Manual work that
            # was done is planned again (stated in the README's limits).
            # A planner's word on when an overrunning print finishes is kept with it.
            said = {
                o["job"]: datetime.fromisoformat(o["ends_at"])
                for o in effects.get("overruns", [])
                if not o["estimated"]
            }
            for job_id, kind, t_status, a_start, a_end, expected, number, line in conn.execute(
                "SELECT t.job_id, t.kind, t.status, t.actual_start, t.actual_end, t.expected_end,"
                "       o.order_number, j.line_no"
                " FROM tasks t JOIN jobs j ON j.id = t.job_id JOIN orders o ON o.id = j.order_id"
                " WHERE t.schedule_id = %s AND t.kind = 'machine'"
                " AND t.status IN ('running', 'done')",
                (old[0],),
            ).fetchall():
                if t_status == "running":
                    expected = said.get(job_key(number, line), expected)
                else:
                    expected = None
                carried[(job_id, kind)] = (t_status, a_start, a_end, expected)
            # Cancel the old plan's open tasks while it is still the approved one (the trigger
            # only lets tasks of the approved schedule change), then supersede it.
            conn.execute(
                "UPDATE tasks SET status = 'cancelled' WHERE schedule_id = %s AND status = 'planned'",
                (old[0],),
            )
            conn.execute("UPDATE schedules SET status = 'superseded' WHERE id = %s", (old[0],))
        conn.execute(
            "UPDATE schedules SET status = 'approved', decided_by = %s, decided_at = %s WHERE id = %s",
            (actor.user_id, now, schedule_id),
        )
        _write_tasks(conn, schedule_id, doc, anchor, tz, carried)
        _apply_facts(conn, actor, schedule_id, effects, list(disruption_ids), now, key)

        audit.record(
            conn,
            actor_user_id=actor.user_id,
            action="schedule.approve",
            entity_type="schedule",
            entity_id=str(version),
            before={"status": "draft"},
            after={
                "status": "approved",
                "supersedes": None if old is None else old[1],
                "jobs": len(doc["plan"]["jobs"]),
                "check_valid": True,
            },
            idempotency_key=key,
        )
        response = idempotency.StoredResponse(
            200, Decision(id=schedule_id, version=version, status="approved").model_dump()
        )
        idempotency.store(
            conn, user_id=actor.user_id, endpoint=endpoint, key=key, response=response
        )
        return response, False


def _write_tasks(
    conn: psycopg.Connection,
    schedule_id: int,
    doc: dict[str, Any],
    anchor: datetime,
    tz: str,
    carried: dict[tuple[int, str], tuple[Any, ...]],
) -> None:
    """One row per planned task. Work already running or done keeps its real status and times."""
    ids = {
        job_key(r[1], r[2]): int(r[0])
        for r in conn.execute(
            "SELECT j.id, o.order_number, j.line_no FROM jobs j JOIN orders o ON o.id = j.order_id"
        ).fetchall()
    }
    machine_ids: dict[str, int] = dict(conn.execute("SELECT code, id FROM machines").fetchall())
    planned_jobs = []
    for pj in doc["plan"]["jobs"]:
        job_id = ids[pj["job_id"]]
        planned_jobs.append(job_id)
        for seq, t in enumerate(pj["tasks"], start=1):
            status, a_start, a_end, expected = carried.get(
                (job_id, t["kind"]), ("planned", None, None, None)
            )
            conn.execute(
                "INSERT INTO tasks (schedule_id, job_id, seq, kind, machine_id, planned_start,"
                " planned_end, actual_start, actual_end, status, expected_end)"
                " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    schedule_id,
                    job_id,
                    seq,
                    t["kind"],
                    machine_ids[pj["machine"]] if t["kind"] == "machine" else None,
                    at_minute(t["start"], anchor, tz),
                    at_minute(t["end"], anchor, tz),
                    a_start,
                    a_end,
                    status,
                    expected,
                ),
            )
    conn.execute(
        "UPDATE jobs SET status = 'planned' WHERE id = ANY(%s) AND status IN ('pending', 'failed')",
        (planned_jobs,),
    )


def _job_ids(conn: psycopg.Connection, keys: list[str]) -> list[int]:
    return [
        int(r[0])
        for r in conn.execute(
            "SELECT j.id FROM jobs j JOIN orders o ON o.id = j.order_id"
            " WHERE (o.order_number || '-' || j.line_no) = ANY(%s)",
            (keys,),
        ).fetchall()
    ]


def _stop_work(
    conn: psycopg.Connection, old_id: int, effects: dict[str, Any], now: datetime
) -> None:
    """Running work that the approved disruptions end: lost prints and cancelled jobs' work."""
    lost = [x["task_id"] for x in effects.get("lost", [])]
    cancelled = _job_ids(conn, [c["job"] for c in effects.get("cancelled", [])])
    conn.execute(
        "UPDATE tasks SET status = 'failed', actual_end = greatest(%s, actual_start)"
        " WHERE schedule_id = %s AND status = 'running' AND (id = ANY(%s) OR job_id = ANY(%s))",
        (now, old_id, lost, cancelled),
    )


def _apply_facts(
    conn: psycopg.Connection,
    actor: Actor,
    schedule_id: int,
    effects: dict[str, Any],
    disruption_ids: list[int],
    now: datetime,
    key: str,
) -> None:
    """The approved disruptions become facts, in the same transaction as the approval (D81)."""
    for d in effects.get("downtimes", []):
        conn.execute(
            "INSERT INTO machine_downtimes (machine_id, starts_at, ends_at, disruption_id)"
            " SELECT id, %s, %s, %s FROM machines WHERE code = %s",
            (d["starts_at"], d["ends_at"], d["disruption"], d["machine"]),
        )
    for d in effects.get("delays", []):
        conn.execute(
            "INSERT INTO material_delays (material_id, available_at, disruption_id)"
            " SELECT id, %s, %s FROM materials WHERE code = %s",
            (d["available_at"], d["disruption"], d["material"]),
        )
    for r in effects.get("rush", []):
        conn.execute(
            "UPDATE orders SET rush = true, updated_at = %s WHERE order_number = %s",
            (now, r["order"]),
        )
    cancelled = effects.get("cancelled", [])
    if cancelled:
        conn.execute(
            "UPDATE jobs SET status = 'cancelled' WHERE id = ANY(%s)",
            (_job_ids(conn, [c["job"] for c in cancelled]),),
        )
        whole = sorted({c["order"] for c in cancelled if c["whole_order"]})
        conn.execute(
            "UPDATE orders SET status = 'cancelled', updated_at = %s WHERE order_number = ANY(%s)",
            (now, whole),
        )
    for did in disruption_ids:
        conn.execute(
            "UPDATE disruptions SET status = 'applied', decided_by = %s, decided_at = %s,"
            " applied_in = %s WHERE id = %s AND status = 'pending'",
            (actor.user_id, now, schedule_id, did),
        )
        audit.record(
            conn,
            actor_user_id=actor.user_id,
            action="disruption.apply",
            entity_type="disruption",
            entity_id=str(did),
            before={"status": "pending"},
            after={"status": "applied", "schedule_id": schedule_id},
            idempotency_key=key,
        )


def discard(
    conn: psycopg.Connection, actor: Actor, schedule_id: int, key: str, now: datetime
) -> tuple[idempotency.StoredResponse, bool]:
    if not can(actor, "schedule.approve"):
        raise ForbiddenError("schedule.approve")
    endpoint = _endpoint(schedule_id, "discard")
    with conn.transaction():
        stored = idempotency.claim(
            conn, user_id=actor.user_id, endpoint=endpoint, key=key, req_hash="discard"
        )
        if stored is not None:
            return stored, True
        row = conn.execute(
            "SELECT version, status FROM schedules WHERE id = %s FOR UPDATE", (schedule_id,)
        ).fetchone()
        if row is None:
            raise NotFoundError(str(schedule_id))
        version, status = row
        if status != "draft":
            raise ConflictError(f"schedule {version} is {status}, not a draft")
        conn.execute(
            "UPDATE schedules SET status = 'discarded', decided_by = %s, decided_at = %s WHERE id = %s",
            (actor.user_id, now, schedule_id),
        )
        audit.record(
            conn,
            actor_user_id=actor.user_id,
            action="schedule.discard",
            entity_type="schedule",
            entity_id=str(version),
            before={"status": "draft"},
            after={"status": "discarded"},
            idempotency_key=key,
        )
        response = idempotency.StoredResponse(
            200, Decision(id=schedule_id, version=version, status="discarded").model_dump()
        )
        idempotency.store(
            conn, user_id=actor.user_id, endpoint=endpoint, key=key, response=response
        )
        return response, False
