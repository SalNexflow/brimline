"""Build the scheduler's instance from the database at a moment in time.

- Jobs still to do (not done, not cancelled) with everything the scheduler needs; a job that
  lacks something is listed as unplannable with what is missing, never guessed.
- Work already running or done in the approved schedule becomes fixed, at its real server-clock
  times: a done machine task from its actual start to its actual end; a running one from its
  actual start for its planned length, or until now if it is already running longer (D77: a
  task that started late ends late; it cannot have finished in the past).
- Nothing new may start before now (plan_start, rule R18).
"""

import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any

import psycopg

from brimline_engine.planning.clock import (
    anchor_for,
    at_minute,
    due_minute,
    minute_at_or_after,
    minute_of,
)
from brimline_engine.scheduling.calendar import horizon_minutes, shift_windows
from brimline_engine.scheduling.config import SchedulerConfig
from brimline_engine.scheduling.export import job_doc, machine_doc
from brimline_engine.scheduling.model import Fixed, Instance, Job, Machine

DEFAULT_DAY_END = time(17, 0)  # due time on a day without a shift (for example a Sunday)


@dataclass(frozen=True)
class JobRef:
    """What the board shows for a job; `key` is the scheduler's id for it."""

    key: str
    job_id: int
    order_number: str
    line_no: int
    part_name: str
    quantity: int
    material_code: str
    due_date: date
    rush: bool


@dataclass(frozen=True)
class Inputs:
    instance: Instance
    anchor: datetime
    refs: dict[str, JobRef]  # by scheduler key
    unplannable: list[dict[str, Any]]  # {"job": key, "part": ..., "missing": [...]}
    fingerprint: str


def job_key(order_number: str, line_no: int) -> str:
    return f"{order_number}-{line_no}"


def _day_end(due: date, cfg: SchedulerConfig) -> time:
    hours = cfg.shifts.weekdays.get(str(due.isoweekday()))
    return time.fromisoformat(hours[1]) if hours else DEFAULT_DAY_END


def _machines(conn: psycopg.Connection) -> tuple[Machine, ...]:
    rows = conn.execute(
        "SELECT m.code, m.process, m.build_x_mm, m.build_y_mm, m.build_z_mm,"
        "       array_agg(mat.code ORDER BY mat.code)"
        " FROM machines m"
        " JOIN machine_materials mm ON mm.machine_id = m.id"
        " JOIN materials mat ON mat.id = mm.material_id"
        " WHERE m.active GROUP BY m.id ORDER BY m.code"
    ).fetchall()
    return tuple(Machine(r[0], r[1], frozenset(r[5]), (r[2], r[3], r[4])) for r in rows)


def _fixed(
    conn: psycopg.Connection, anchor: datetime, now: datetime, tz: str, refs: dict[int, str]
) -> tuple[dict[str, Fixed], dict[str, str]]:
    """Machine tasks running or done in the approved schedule, at their real times, and the
    status of each (for the fingerprint)."""
    rows = conn.execute(
        "SELECT t.job_id, m.code, t.status, t.actual_start, t.actual_end, t.planned_start,"
        "       t.planned_end"
        " FROM tasks t JOIN schedules s ON s.id = t.schedule_id AND s.status = 'approved'"
        " JOIN machines m ON m.id = t.machine_id"
        " WHERE t.kind = 'machine' AND t.status IN ('running', 'done')"
    ).fetchall()
    out = {}
    statuses = {}
    for job_id, machine, status, a_start, a_end, p_start, p_end in rows:
        if job_id not in refs:
            continue  # the whole job is done
        start = minute_of(a_start, anchor, tz)
        if status == "done":
            end = minute_at_or_after(a_end, anchor, tz)
        else:  # running: its planned length from when it really started, or until now
            length = -(-(p_end - p_start) // timedelta(minutes=1))  # whole minutes, rounded up
            end = max(start + length, minute_at_or_after(now, anchor, tz))
        # A task done within the same minute it started still occupied its machine.
        out[refs[job_id]] = Fixed(refs[job_id], machine, start, max(end, start + 1))
        statuses[refs[job_id]] = status
    return out, statuses


def build_inputs(conn: psycopg.Connection, now: datetime, cfg: SchedulerConfig, tz: str) -> Inputs:
    anchor = anchor_for(now, tz)
    rows = conn.execute(
        "SELECT j.id, o.order_number, j.line_no, j.part_name, j.quantity, mat.code, mat.process,"
        "       j.minutes_per_part, j.part_x_mm, j.part_y_mm, j.part_z_mm, j.post_processing,"
        "       o.due_date, o.rush"
        " FROM jobs j JOIN orders o ON o.id = j.order_id JOIN materials mat ON mat.id = j.material_id"
        " WHERE j.status NOT IN ('done', 'cancelled') AND o.status NOT IN ('done', 'cancelled')"
        " ORDER BY o.created_at, o.id, j.line_no"
    ).fetchall()
    post_minutes = cfg.durations.post_process_minutes_per_part
    jobs: list[Job] = []
    refs: dict[str, JobRef] = {}
    unplannable: list[dict[str, Any]] = []
    for arrival, row in enumerate(rows, start=1):
        (job_id, number, line_no, part, qty, material, process, mpp, x, y, z, post, due, rush) = row
        key = job_key(number, line_no)
        refs[key] = JobRef(key, job_id, number, line_no, part, qty, material, due, rush)
        missing = []
        if mpp is None:
            missing.append("machine minutes per part")
        if None in (x, y, z):
            missing.append("part size")
        unknown_steps = [p for p in post if p not in post_minutes]
        if unknown_steps:
            missing.append(f"minutes for {', '.join(unknown_steps)} in config/scheduler.toml")
        if missing:
            unplannable.append({"job": key, "part": part, "missing": missing})
            continue
        jobs.append(
            Job(
                id=key,
                arrival=arrival,
                material=material,
                process=process,
                part_mm=(x, y, z),
                quantity=qty,
                minutes_per_part=mpp,
                post_minutes_per_part=sum(post_minutes[p] for p in post),
                due=due_minute(due, _day_end(due, cfg), anchor, tz),
                rush=rush,
                release=0,  # material deliveries arrive with M6; today stock is assumed on hand
                post_processing=tuple(post),
            )
        )
    planned_keys = {j.id for j in jobs}
    fixed, statuses = _fixed(
        conn, anchor, now, tz, {r.job_id: r.key for r in refs.values() if r.key in planned_keys}
    )
    machines = _machines(conn)
    instance = Instance(
        name=f"plan-{now.isoformat(timespec='minutes')}",
        horizon=horizon_minutes(cfg.shifts),
        machines=machines,
        jobs=tuple(jobs),
        shifts=shift_windows(cfg.shifts),
        staff=cfg.staff.people_per_shift,
        fixed=tuple(fixed.values()),
        plan_start=minute_at_or_after(now, anchor, tz),
    )
    return Inputs(
        instance,
        anchor,
        refs,
        unplannable,
        fingerprint(instance, unplannable, statuses, anchor, tz),
    )


def fingerprint(
    instance: Instance,
    unplannable: list[dict[str, Any]],
    statuses: dict[str, str],
    anchor: datetime,
    tz: str,
) -> str:
    """What a plan was made from. Approval compares it with the inputs now: if a job, a machine,
    the shifts or the state of the work (a task started or finished) changed, the plan is stale.
    Times are absolute, so a new week's minute 0 does not by itself make a plan stale; the
    moment of planning and the expected end of running work are left out, since both move with
    the clock (approval checks separately that the plan does not start in the past)."""

    def absolute(minute: int) -> str:
        return at_minute(minute, anchor, tz).isoformat()

    data = {
        "jobs": [job_doc(j) | {"due": absolute(j.due)} for j in instance.jobs],
        "machines": [machine_doc(m) for m in instance.machines],
        "fixed": [
            {
                "job_id": f.job_id,
                "machine": f.machine,
                "start": absolute(f.start),
                "status": statuses.get(f.job_id),
            }
            for f in instance.fixed
        ],
        "unplannable": unplannable,
        "shifts": [[absolute(lo), absolute(hi)] for lo, hi in instance.shifts],
        "staff": instance.staff,
    }
    canonical = json.dumps(data, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()
