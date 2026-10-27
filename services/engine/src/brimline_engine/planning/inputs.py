"""Build the scheduler's instance from the database at a moment in time.

- Jobs still to do (not done, not cancelled) with everything the scheduler needs; a job that
  lacks something is listed as unplannable with what is missing, never guessed.
- Work already running or done in the approved schedule becomes fixed, at its real server-clock
  times: a done machine task from its actual start to its actual end; a running one from its
  actual start for its planned length (D77). A print already running longer than that is
  assumed to need `overrun_margin_minutes` more (an estimate, shown as one) until a planner
  says when it will finish (a print_overrun disruption).
- Nothing new may start before now (plan_start, rule R18).
- Disruptions (M6): applied facts (downtimes, material delays) and every pending disruption
  are applied as if approved: downtimes block machines, delays hold back material, rush and
  cancellations change the jobs. A print running on a machine that goes down is lost and
  planned again from the start (config: running_print_lost_when_machine_down). What would
  change is listed in `effects`, for the review and for approval to apply.
- The approved plan, if any, becomes `previous`, so the solver avoids moving work without need.
"""

import hashlib
import json
from dataclasses import dataclass, field
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
from brimline_engine.scheduling.model import Downtime, Fixed, Instance, Job, Machine, Previous

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


@dataclass
class Effects:
    """What approving a plan made from these inputs would change, besides the plan itself.
    Times are ISO strings (absolute), so they can be stored and applied later."""

    lost: list[dict[str, Any]] = field(default_factory=list)  # running prints treated as lost
    cancelled: list[dict[str, Any]] = field(default_factory=list)
    rush: list[dict[str, Any]] = field(default_factory=list)
    downtimes: list[dict[str, Any]] = field(default_factory=list)  # new ones, from disruptions
    delays: list[dict[str, Any]] = field(default_factory=list)
    overruns: list[dict[str, Any]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)  # plain statements of config choices made

    def as_dict(self) -> dict[str, Any]:
        return {k: v for k, v in self.__dict__.items()}


@dataclass(frozen=True)
class Inputs:
    instance: Instance
    anchor: datetime
    refs: dict[str, JobRef]  # by scheduler key
    unplannable: list[dict[str, Any]]  # {"job": key, "part": ..., "missing": [...]}
    fingerprint: str
    effects: Effects = field(default_factory=Effects)
    disruption_ids: tuple[int, ...] = ()
    previous_id: int | None = None  # the approved schedule this re-plans


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


@dataclass
class _Disruptions:
    ids: list[int] = field(default_factory=list)
    record: list[dict[str, Any]] = field(default_factory=list)  # for the fingerprint
    cancelled: set[tuple[str, int | None]] = field(default_factory=set)  # (order, line or all)
    rush: dict[str, int] = field(default_factory=dict)  # order -> disruption id
    # (machine, start, end or None for "until further notice", disruption id or None if applied)
    downtimes: list[tuple[str, datetime, datetime | None, int | None]] = field(default_factory=list)
    delays: dict[str, tuple[datetime, int | None]] = field(default_factory=dict)  # material
    overruns: dict[str, datetime] = field(default_factory=dict)  # machine -> expected end


def _disruptions(conn: psycopg.Connection, now: datetime) -> _Disruptions:
    """Applied facts that still matter, and every pending disruption, as if it were approved."""
    out = _Disruptions()
    for machine, start, end in conn.execute(
        "SELECT m.code, d.starts_at, d.ends_at FROM machine_downtimes d"
        " JOIN machines m ON m.id = d.machine_id WHERE d.ends_at > %s ORDER BY d.id",
        (now,),
    ).fetchall():
        out.downtimes.append((machine, start, end, None))
    for material, available in conn.execute(
        "SELECT mat.code, max(d.available_at) FROM material_delays d"
        " JOIN materials mat ON mat.id = d.material_id WHERE d.available_at > %s"
        " GROUP BY mat.code ORDER BY mat.code",
        (now,),
    ).fetchall():
        out.delays[material] = (available, None)
    for did, events, received in conn.execute(
        "SELECT id, events, received_at FROM disruptions WHERE status = 'pending' ORDER BY id"
    ).fetchall():
        out.ids.append(did)
        out.record.append({"id": did, "events": events})
        for e in events:
            ends = datetime.fromisoformat(e["ends_at"]) if e.get("ends_at") else None
            if e["type"] == "machine_down":
                starts = datetime.fromisoformat(e["starts_at"]) if e.get("starts_at") else received
                out.downtimes.append((e["machine"], starts, ends, did))
            elif e["type"] == "material_delayed" and ends is not None:
                current = out.delays.get(e["material"])
                if current is None or ends > current[0]:
                    out.delays[e["material"]] = (ends, did)
            elif e["type"] == "rush_job":
                out.rush[e["order"]] = did
            elif e["type"] == "cancellation":
                out.cancelled.add((e["order"], e.get("line")))
            elif e["type"] == "print_overrun" and ends is not None:
                out.overruns[e["machine"]] = ends
    return out


def build_inputs(conn: psycopg.Connection, now: datetime, cfg: SchedulerConfig, tz: str) -> Inputs:
    anchor = anchor_for(now, tz)
    horizon = horizon_minutes(cfg.shifts)
    plan_start = minute_at_or_after(now, anchor, tz)
    effects = Effects()
    dis = _disruptions(conn, now)

    def minute(dt: datetime) -> int:
        return minute_at_or_after(dt, anchor, tz)

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
        if (number, None) in dis.cancelled or (number, line_no) in dis.cancelled:
            effects.cancelled.append(
                {
                    "job": key,
                    "order": number,
                    "line": line_no,
                    "whole_order": (number, None) in dis.cancelled,
                }
            )
            continue
        if number in dis.rush and not rush:
            rush = True
            if not any(r["order"] == number for r in effects.rush):
                effects.rush.append({"order": number, "disruption": dis.rush[number]})
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
        delay = dis.delays.get(material)
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
                release=max(0, minute(delay[0])) if delay else 0,
                post_processing=tuple(post),
            )
        )

    # Downtimes in plan minutes; a past part does not matter (nothing new starts before now).
    downs: list[tuple[str, int, int, datetime, datetime | None, int | None]] = []
    for machine, start_dt, end_dt, did in dis.downtimes:
        end = horizon if end_dt is None else minute(end_dt)
        start = max(minute_of(start_dt, anchor, tz), plan_start)
        if end > start:
            downs.append((machine, start, end, start_dt, end_dt, did))
        if did is not None:
            effects.downtimes.append(
                {
                    "machine": machine,
                    "starts_at": start_dt.isoformat(),
                    "ends_at": (end_dt or at_minute(horizon, anchor, tz)).isoformat(),
                    "until_further_notice": end_dt is None,
                    "disruption": did,
                }
            )
    for material, (available, did) in dis.delays.items():
        if did is not None:
            effects.delays.append(
                {"material": material, "available_at": available.isoformat(), "disruption": did}
            )

    planned_keys = {j.id for j in jobs}
    fixed, statuses = _fixed(
        conn,
        anchor,
        now,
        tz,
        cfg,
        {r.job_id: r.key for r in refs.values() if r.key in planned_keys},
        dis.overruns,
        downs,
        effects,
    )
    # A downtime moved to after a print that survives it (config: prints are not lost).
    downtimes = tuple(Downtime(m, s, e) for m, s, e, *_ in downs if e > s)
    previous, previous_id = _previous(conn, anchor, tz, planned_keys - set(fixed))
    instance = Instance(
        name=f"plan-{now.isoformat(timespec='minutes')}",
        horizon=horizon,
        machines=_machines(conn),
        jobs=tuple(jobs),
        shifts=shift_windows(cfg.shifts),
        staff=cfg.staff.people_per_shift,
        fixed=tuple(fixed.values()),
        plan_start=plan_start,
        downtimes=downtimes,
        previous=previous,
    )
    fp = fingerprint(instance, unplannable, statuses, anchor, tz, dis.record)
    return Inputs(instance, anchor, refs, unplannable, fp, effects, tuple(dis.ids), previous_id)


def _fixed(
    conn: psycopg.Connection,
    anchor: datetime,
    now: datetime,
    tz: str,
    cfg: SchedulerConfig,
    refs: dict[int, str],
    overruns: dict[str, datetime],
    downs: list[tuple[str, int, int, datetime, datetime | None, int | None]],
    effects: Effects,
) -> tuple[dict[str, Fixed], dict[str, str]]:
    """Machine tasks running or done in the approved schedule, at their real times, and the
    status of each (for the fingerprint). Updates `downs` and `effects` for running prints."""
    rows = conn.execute(
        "SELECT t.id, t.job_id, m.code, t.status, t.actual_start, t.actual_end, t.planned_start,"
        "       t.planned_end, t.expected_end"
        " FROM tasks t JOIN schedules s ON s.id = t.schedule_id AND s.status = 'approved'"
        " JOIN machines m ON m.id = t.machine_id"
        " WHERE t.kind = 'machine' AND t.status IN ('running', 'done') ORDER BY t.id"
    ).fetchall()
    now_minute = minute_at_or_after(now, anchor, tz)
    out = {}
    statuses = {}
    for task_id, job_id, machine, status, a_start, a_end, p_start, p_end, expected in rows:
        if job_id not in refs:
            continue  # the whole job is done (or cancelled)
        key = refs[job_id]
        start = minute_of(a_start, anchor, tz)
        if status == "done":
            end = minute_at_or_after(a_end, anchor, tz)
        else:
            length = -(-(p_end - p_start) // timedelta(minutes=1))  # whole minutes, rounded up
            if machine in overruns:  # a planner said when it will finish
                end = minute_at_or_after(overruns[machine], anchor, tz)
                effects.overruns.append(
                    {
                        "job": key,
                        "machine": machine,
                        "ends_at": overruns[machine].isoformat(),
                        "estimated": False,
                    }
                )
            elif expected is not None:  # said earlier, and approved
                end = max(minute_at_or_after(expected, anchor, tz), now_minute)
            elif start + length > now_minute:
                end = start + length
            else:  # running over, nobody has said for how long: an estimate
                end = now_minute + cfg.replan.overrun_margin_minutes
                at = at_minute(end, anchor, tz)
                effects.overruns.append(
                    {"job": key, "machine": machine, "ends_at": at.isoformat(), "estimated": True}
                )
                effects.notes.append(
                    f"{key} on {machine} is running past its planned end; assumed to need"
                    f" {cfg.replan.overrun_margin_minutes} more minutes (an estimate, from"
                    " overrun_margin_minutes) until someone says when it will finish."
                )
            hit = [d for d in downs if d[0] == machine and d[1] < end and start < d[2]]
            if hit and cfg.replan.running_print_lost_when_machine_down:
                effects.lost.append({"job": key, "task_id": task_id, "machine": machine})
                effects.notes.append(
                    f"The print of {key} on {machine} is treated as lost and planned again from"
                    " the start, because its machine goes down while it runs"
                    " (running_print_lost_when_machine_down = true)."
                )
                statuses[key] = "lost"
                continue
            for i, d in enumerate(downs):
                if d in hit:  # the print survives: the machine goes down when it ends
                    downs[i] = (d[0], max(d[1], end), d[2], *d[3:])
                    effects.notes.append(
                        f"The print of {key} on {machine} is assumed to finish before its machine"
                        " goes down (running_print_lost_when_machine_down = false)."
                    )
        out[key] = Fixed(key, machine, start, max(end, start + 1))
        statuses[key] = status
    return out, statuses


def _previous(
    conn: psycopg.Connection, anchor: datetime, tz: str, movable: set[str]
) -> tuple[tuple[Previous, ...], int | None]:
    """Where the approved plan had each job that can still move, in this plan's minutes."""
    row = conn.execute(
        "SELECT id, anchor, document FROM schedules WHERE status = 'approved'"
    ).fetchone()
    if row is None:
        return (), None
    sid, old_anchor, doc = row
    out = []
    for pj in doc["plan"]["jobs"]:
        if pj["job_id"] not in movable:
            continue
        machine_task = next((t for t in pj["tasks"] if t["kind"] == "machine"), None)
        if machine_task is None:
            continue

        def here(m: int) -> int:
            return minute_of(at_minute(m, old_anchor, tz), anchor, tz)

        out.append(
            Previous(
                pj["job_id"],
                pj["machine"],
                here(machine_task["start"]),
                here(max(t["end"] for t in pj["tasks"])),
            )
        )
    return tuple(out), int(sid)


def fingerprint(
    instance: Instance,
    unplannable: list[dict[str, Any]],
    statuses: dict[str, str],
    anchor: datetime,
    tz: str,
    disruptions: list[dict[str, Any]],
) -> str:
    """What a plan was made from. Approval compares it with the inputs now: if a job, a machine,
    the shifts, the state of the work, a downtime, a material delay or the set of pending
    disruptions changed, the plan is stale. Times are absolute, so a new week's minute 0 does
    not by itself make a plan stale; the moment of planning and the expected end of running
    work are left out, since both move with the clock (approval checks separately that the plan
    does not start in the past)."""

    def absolute(minute: int) -> str:
        return at_minute(minute, anchor, tz).isoformat()

    data = {
        "jobs": [
            job_doc(j) | {"due": absolute(j.due), "release": absolute(j.release)}
            for j in instance.jobs
        ],
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
        "lost": sorted(k for k, v in statuses.items() if v == "lost"),
        "downtimes": [{"machine": d.machine, "end": absolute(d.end)} for d in instance.downtimes],
        "disruptions": disruptions,
        "unplannable": unplannable,
        "shifts": [[absolute(lo), absolute(hi)] for lo, hi in instance.shifts],
        "staff": instance.staff,
    }
    canonical = json.dumps(data, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()
