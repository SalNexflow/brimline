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
- Material (M9): the stock on hand, less what running prints are using, and every open purchase
  order as a delivery at its expected time (a delivery already overdue is not counted until a
  person updates it). A material delay moves that material's open deliveries; with none open
  it holds the material back as before. Each job's grams per part come from the job, its file
  or its quote, in that order (materials/grams.py); a job with none cannot be planned.
"""

import hashlib
import json
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Any

import psycopg

from brimline_engine.materials.grams import Grams, job_grams
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
from brimline_engine.scheduling.model import (
    Delivery,
    Downtime,
    Fixed,
    Instance,
    Job,
    Machine,
    Previous,
)

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
    grams: Grams  # grams per part and where the number came from (M9)


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
        " JOIN machines m ON m.id = d.machine_id WHERE d.ends_at IS NULL OR d.ends_at > %s"
        " ORDER BY d.id",
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
    grams = job_grams(conn, [r[0] for r in rows])
    started = {  # jobs whose machine task already runs or ran: they need no grams any more
        int(r[0])
        for r in conn.execute(
            "SELECT DISTINCT t.job_id FROM tasks t"
            " JOIN schedules s ON s.id = t.schedule_id AND s.status = 'approved'"
            " WHERE t.kind = 'machine' AND t.status IN ('running', 'done')"
        ).fetchall()
    }
    with_delivery = {  # materials with an open purchase order: a delay moves the order instead
        str(r[0])
        for r in conn.execute(
            "SELECT DISTINCT m.code FROM purchase_orders p JOIN materials m"
            " ON m.id = p.material_id WHERE p.status = 'open'"
        ).fetchall()
    }
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
        refs[key] = JobRef(
            key, job_id, number, line_no, part, qty, material, due, rush, grams[job_id]
        )
        missing = []
        if mpp is None:
            missing.append("machine minutes per part")
        if None in (x, y, z):
            missing.append("part size")
        unknown_steps = [p for p in post if p not in post_minutes]
        if unknown_steps:
            missing.append(f"minutes for {', '.join(unknown_steps)} in config/scheduler.toml")
        if grams[job_id].per_part is None and job_id not in started:
            missing.append("grams per part (enter them, or upload the part's file)")
        if missing:
            unplannable.append({"job": key, "part": part, "missing": missing})
            continue
        delay = None if material in with_delivery else dis.delays.get(material)
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
                grams_per_part=grams[job_id].per_part,
            )
        )

    # Downtimes in plan minutes; a past part does not matter (nothing new starts before now).
    downs: list[tuple[str, int, int, datetime, datetime | None, int | None]] = []
    for machine, start_dt, end_dt, did in dis.downtimes:
        end = horizon if end_dt is None else minute(end_dt)
        start = max(minute_of(start_dt, anchor, tz), plan_start)
        if end > start:
            downs.append((machine, start, end, start_dt, end_dt, did))
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
    # A print lost to a breakdown is planned again and needs its grams after all (M9).
    for j in [j for j in jobs if j.grams_per_part is None and j.id not in fixed]:
        jobs.remove(j)
        planned_keys.discard(j.id)
        unplannable.append(
            {"job": j.id, "part": refs[j.id].part_name, "missing": ["grams per part"]}
        )
    # New downtimes to record at approval, after _fixed may have moved one to start when a
    # running print ends. "Until further notice" is stored open (null), not as the horizon.
    for machine, start, _end, start_dt, end_dt, did in downs:
        if did is None:
            continue
        moved = start > max(minute_of(start_dt, anchor, tz), plan_start)
        effects.downtimes.append(
            {
                "machine": machine,
                "starts_at": (at_minute(start, anchor, tz) if moved else start_dt).isoformat(),
                "ends_at": None if end_dt is None else end_dt.isoformat(),
                "disruption": did,
            }
        )
    downtimes = tuple(Downtime(m, s, e) for m, s, e, *_ in downs if e > s)
    stock = _stock(conn, jobs, statuses, effects)
    deliveries = _deliveries(conn, now, dis, effects, minute)
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
        stock=stock,
        deliveries=deliveries,
    )
    fp = fingerprint(instance, unplannable, statuses, anchor, tz, dis.record)
    return Inputs(instance, anchor, refs, unplannable, fp, effects, tuple(dis.ids), previous_id)


def _stock(
    conn: psycopg.Connection, jobs: list[Job], statuses: dict[str, str], effects: Effects
) -> tuple[tuple[str, int], ...]:
    """Grams free for this plan: on hand, less what prints still running are using (they take
    it from the record when they end). A print about to be treated as lost counts too: the
    material in it is gone either way."""
    on_hand = {
        code: int(grams)
        for code, grams in conn.execute(
            "SELECT m.code, s.on_hand_g FROM stock s JOIN materials m ON m.id = s.material_id"
        ).fetchall()
    }
    in_use: dict[str, int] = {}
    for j in jobs:
        if statuses.get(j.id) in ("running", "lost"):
            in_use[j.material] = in_use.get(j.material, 0) + j.grams
    out = []
    for code in sorted(on_hand.keys() | in_use.keys()):
        free = on_hand.get(code, 0) - in_use.get(code, 0)
        if free < 0:
            effects.notes.append(
                f"The stock record of {code} ({on_hand.get(code, 0)} g) is less than the running"
                f" prints use ({in_use[code]} g): planned as 0 g free. A stock count is due."
            )
        out.append((code, max(0, free)))
    return tuple(out)


def _deliveries(
    conn: psycopg.Connection,
    now: datetime,
    dis: "_Disruptions",
    effects: Effects,
    minute: Any,  # noqa: ANN401 - the local datetime -> plan minute function
) -> tuple[Delivery, ...]:
    """Open purchase orders as deliveries. A material delay moves them (never earlier)."""
    out = []
    for number, code, grams, expected in conn.execute(
        "SELECT p.po_number, m.code, p.grams, p.expected_at FROM purchase_orders p"
        " JOIN materials m ON m.id = p.material_id WHERE p.status = 'open' ORDER BY p.id"
    ).fetchall():
        delay = dis.delays.get(code)
        arrives = max(expected, delay[0]) if delay else expected
        if arrives < now:
            effects.notes.append(
                f"{number} ({grams} g {code}) was due {expected:%a %d %b %H:%M} and has not been"
                " received: not counted until someone marks it received or reports a delay."
            )
            continue
        out.append(Delivery(code, minute(arrives), int(grams)))
    return tuple(out)


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
            # Lost only if the machine is down now, while it prints. A downtime that starts
            # later waits for the print instead (review of M6: a print was stopped now for a
            # breakdown planned for later).
            down_now = [d for d in hit if d[1] <= now_minute]
            if down_now and cfg.replan.running_print_lost_when_machine_down:
                effects.lost.append({"job": key, "task_id": task_id, "machine": machine})
                effects.notes.append(
                    f"The print of {key} on {machine} is treated as lost and planned again from"
                    " the start, because its machine goes down while it runs"
                    " (running_print_lost_when_machine_down = true)."
                )
                statuses[key] = "lost"
                continue
            for i, d in enumerate(downs):
                if d not in hit:
                    continue
                downs[i] = (d[0], max(d[1], end), d[2], *d[3:])
                if d in down_now:
                    effects.notes.append(
                        f"The print of {key} on {machine} is assumed to finish before its machine"
                        " goes down (running_print_lost_when_machine_down = false)."
                    )
                else:
                    effects.notes.append(
                        f"{machine} is due to go down at {at_minute(d[1], anchor, tz):%a %d %b %H:%M}"
                        f" while the print of {key} runs until"
                        f" {at_minute(end, anchor, tz):%a %d %b %H:%M}: the downtime starts when"
                        " the print ends. Dismiss the disruption and enter it again if the print"
                        " must stop."
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
        "stock": instance.stock,
        "deliveries": [[d.material, absolute(d.at), d.grams] for d in instance.deliveries],
    }
    canonical = json.dumps(data, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


def effects_key(effects: dict[str, Any]) -> dict[str, Any]:
    """What approval must find unchanged between the draft and now (review of M6): which prints
    are lost, which jobs are cancelled or made rush, the new downtimes and delays, and which
    overruns are estimates. Clock-dependent details (an estimated end) are left out."""
    return {
        "lost": sorted(x["job"] for x in effects.get("lost", [])),
        "cancelled": sorted(x["job"] for x in effects.get("cancelled", [])),
        "rush": sorted(x["order"] for x in effects.get("rush", [])),
        "downtimes": sorted(
            (d["machine"], d["disruption"], d["ends_at"] or "")
            for d in effects.get("downtimes", [])
        ),
        "delays": sorted((d["material"], d["available_at"]) for d in effects.get("delays", [])),
        "overruns": sorted(
            (o["job"], o["estimated"], "" if o["estimated"] else o["ends_at"])
            for o in effects.get("overruns", [])
        ),
    }
