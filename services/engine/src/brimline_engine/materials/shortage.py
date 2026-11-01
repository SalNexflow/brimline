"""Shortages and purchase suggestions for a plan (M9). Code only; nothing here is ever ordered.

Method: material requirements planning (MRP), the textbook way.
1. Each job needs its grams at its **need time**: the latest moment its machine task could
   start and the job still be packed by its due time, working back from the due time through
   the shifts (finish, then post-processing, then the machine task). Other jobs are ignored, so
   need times are optimistic: material may really be needed a little earlier.
2. Per material, walk the needs and the deliveries in time order from the plan's stock (a
   delivery at the same minute counts first). The material **runs short** at the first need
   that takes the level below zero; every need that leaves it below zero is an affected job.
   The shortfall is the lowest level reached.
3. A **suggestion** covers the shortfall plus the material's safety stock, in whole packs, and
   says the latest date to order so it arrives by the first short need (lead time in calendar
   days, arriving at the configured time). If that date has passed: order today, and the jobs
   needed before it arrives will still wait.
"""

import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from pydantic import BaseModel

from brimline_engine.materials.config import PurchasingConfig, Supply
from brimline_engine.planning.clock import at_minute, minute_at_or_after
from brimline_engine.scheduling.config import Durations
from brimline_engine.scheduling.durations import task_durations
from brimline_engine.scheduling.model import Job

Windows = tuple[tuple[int, int], ...]


@dataclass(frozen=True)
class Need:
    job: str
    material: str
    grams: int
    at: int  # plan minute: the latest on-time machine start


@dataclass(frozen=True)
class Shortage:
    material: str
    short_at: int  # plan minute of the first need left uncovered
    short_by: int  # grams: how far below zero the level goes at its lowest
    affected: tuple[str, ...]  # jobs whose need leaves the level below zero, in time order


def _latest_manual_start(limit: int, length: int, windows: Windows) -> int | None:
    """Latest s with the task [s, s + length) inside one shift and ending by `limit`."""
    for lo, hi in reversed(windows):
        s = min(hi, limit) - length
        if s >= lo:
            return s
    return None


def _latest_machine_start(limit: int, windows: Windows) -> int | None:
    """Latest s <= limit inside a shift (a machine task must start in one)."""
    for lo, hi in reversed(windows):
        if lo <= limit:
            return min(limit, hi - 1)
    return None


def need_time(durations: Mapping[str, int], due: int, windows: Windows, plan_start: int) -> int:
    """The latest on-time machine start; plan_start when on time is no longer possible."""
    t = due
    for kind in ("finish", "post"):
        if kind in durations:
            s = _latest_manual_start(t, durations[kind], windows)
            if s is None:
                return plan_start
            t = s
    s = _latest_machine_start(t - durations["machine"], windows)
    return plan_start if s is None else max(plan_start, s)


def shortages(
    stock: dict[str, int], deliveries: list[tuple[str, int, int]], needs: list[Need]
) -> list[Shortage]:
    """Every material that runs short, in material order. `deliveries`: (material, minute, g)."""
    out = []
    for material in sorted({n.material for n in needs}):
        events: list[tuple[int, int, str, int]] = [  # (minute, 0 delivery / 1 need, job, grams)
            (at, 0, "", grams) for m, at, grams in deliveries if m == material
        ]
        events += [(n.at, 1, n.job, -n.grams) for n in needs if n.material == material]
        level = stock.get(material, 0)
        lowest = 0
        affected: list[str] = []
        first: int | None = None
        for at, kind, job, change in sorted(events):
            level += change
            if kind == 1 and level < 0:
                affected.append(job)
                first = at if first is None else first
                lowest = min(lowest, level)
        if first is not None:
            out.append(Shortage(material, first, -lowest, tuple(affected)))
    return out


@dataclass(frozen=True)
class Order:
    grams: int
    packs: int
    order_by: date  # the latest day to order, or today when that day has passed
    arrives_at: datetime  # if ordered on order_by
    in_time: bool  # arrives by the first short need


def arrival(ordered: date, supply: Supply, delivery_time: time, tz: str) -> datetime:
    when = datetime.combine(ordered + timedelta(days=supply.lead_time_days), delivery_time)
    return when.replace(tzinfo=ZoneInfo(tz))


def suggest(
    short_by: int, needed_at: datetime, supply: Supply, delivery_time: time, tz: str, now: datetime
) -> Order:
    """What to order to cover a shortfall, and by when. Pure: dates come from the arguments."""
    packs = math.ceil((short_by + supply.safety_stock_g) / supply.pack_grams)
    local_need = needed_at.astimezone(ZoneInfo(tz))
    latest = local_need.date() - timedelta(days=supply.lead_time_days)
    if arrival(latest, supply, delivery_time, tz) > needed_at:
        latest -= timedelta(days=1)  # it would arrive later in that day than it is needed
    today = now.astimezone(ZoneInfo(tz)).date()
    in_time = latest >= today
    order_by = latest if in_time else today
    return Order(
        grams=packs * supply.pack_grams,
        packs=packs,
        order_by=order_by,
        arrives_at=arrival(order_by, supply, delivery_time, tz),
        in_time=in_time,
    )


# --- For a saved plan --------------------------------------------------------------------------


class AffectedJob(BaseModel):
    job: str
    grams: int
    needed_at: datetime
    planned_start: datetime | None  # None: the plan left it unscheduled
    late_minutes: int | None  # None when unscheduled; 0 when on time
    waits_after_order: bool  # still needed before a suggested order would arrive


class Suggestion(BaseModel):
    supplier: str
    grams: int
    packs: int
    pack_grams: int
    order_by: date
    arrives_at: datetime
    in_time: bool
    lead_time_days: int


class MaterialShortage(BaseModel):
    material: str
    short_at: datetime
    short_by_g: int
    affected: list[AffectedJob]
    suggestion: Suggestion | None  # None when the material has no supplier in the config


def _job(d: dict[str, Any]) -> Job:
    return Job(
        id=d["id"],
        arrival=d["arrival"],
        material=d["material"],
        process=d["process"],
        part_mm=tuple(d["part_mm"]),
        quantity=d["quantity"],
        minutes_per_part=d["minutes_per_part"],
        post_minutes_per_part=d["post_minutes_per_part"],
        due=d["due"],
        rush=d["rush"],
        release=d["release"],
        grams_per_part=d.get("grams_per_part"),
    )


def for_document(
    doc: dict[str, Any],
    anchor: datetime,
    tz: str,
    durations: Durations,
    purchasing: PurchasingConfig,
    now: datetime,
) -> list[MaterialShortage]:
    """Shortages of a saved plan document (brimline-plan/1), as of `now` for order dates."""
    inst, plan = doc["instance"], doc["plan"]
    if "stock" not in inst:
        return []  # a plan made before M9: material was not part of it
    windows: Windows = tuple((lo, hi) for lo, hi in inst["shifts"])
    fixed = {f["job_id"] for f in inst["fixed"]}
    jobs = {j["id"]: _job(j) for j in inst["jobs"] if j["id"] not in fixed}
    needs = [
        Need(
            j.id,
            j.material,
            j.grams,
            need_time(
                {str(k): v for k, v in task_durations(j, durations).items()},
                j.due,
                windows,
                inst["plan_start"],
            ),
        )
        for j in jobs.values()
    ]
    deliveries = [(d["material"], d["at"], d["grams"]) for d in inst["deliveries"]]
    planned = {pj["job_id"]: pj for pj in plan["jobs"]}

    def moment(minute: int) -> datetime:
        return at_minute(minute, anchor, tz)

    out = []
    by_job = {n.job: n for n in needs}
    for s in shortages(inst["stock"], deliveries, needs):
        supply = purchasing.materials.get(s.material)
        order = (
            None
            if supply is None
            else suggest(s.short_by, moment(s.short_at), supply, purchasing.delivery_time, tz, now)
        )
        arrives = None if order is None else minute_at_or_after(order.arrives_at, anchor, tz)
        affected = []
        for key in s.affected:
            pj = planned.get(key)
            machine = None if pj is None else next(t for t in pj["tasks"] if t["kind"] == "machine")
            completion = None if pj is None else max(t["end"] for t in pj["tasks"])
            affected.append(
                AffectedJob(
                    job=key,
                    grams=by_job[key].grams,
                    needed_at=moment(by_job[key].at),
                    planned_start=None if machine is None else moment(machine["start"]),
                    late_minutes=None if completion is None else max(0, completion - jobs[key].due),
                    waits_after_order=arrives is not None and by_job[key].at < arrives,
                )
            )
        out.append(
            MaterialShortage(
                material=s.material,
                short_at=moment(s.short_at),
                short_by_g=s.short_by,
                affected=affected,
                suggestion=None
                if order is None or supply is None
                else Suggestion(
                    supplier=supply.supplier,
                    grams=order.grams,
                    packs=order.packs,
                    pack_grams=supply.pack_grams,
                    order_by=order.order_by,
                    arrives_at=order.arrives_at,
                    in_time=order.in_time,
                    lead_time_days=supply.lead_time_days,
                ),
            )
        )
    return out
