"""Two greedy baselines: first-come-first-served (FCFS) and earliest due date (EDD).

One list scheduler, two policies. Jobs are placed one at a time, each task as early as the rules
allow, never moving anything already placed:
  FCFS: jobs in arrival order; each on the machine where it can START earliest.
  EDD:  jobs by due date (rush first on ties, then arrival); each on the machine where it
        FINISHES earliest.
Both obey the same rules as the CP-SAT model: eligible machines, shifts, staff, material
arrival, changeover time between different materials, fixed tasks. A job that cannot fit the
horizon is reported as unscheduled, never silently dropped.
"""

from dataclasses import dataclass
from typing import Literal

from brimline_engine.scheduling.calendar import earliest_machine_start, earliest_manual_start
from brimline_engine.scheduling.config import Durations
from brimline_engine.scheduling.durations import eligible_machines, task_durations
from brimline_engine.scheduling.model import Fixed, Instance, Job, JobPlan, Schedule, Slot, TaskKind

Pick = Literal["start", "finish"]


@dataclass
class _State:
    machine_free: dict[str, int]
    last_material: dict[str, str | None]
    lanes: list[list[tuple[int, int]]]  # each person's busy [start, end) intervals


def _earliest_gap(
    t0: int, duration: int, busy: list[tuple[int, int]], instance: Instance
) -> int | None:
    """Earliest start >= t0 inside a shift where this person is free for `duration` minutes.
    Tasks go into the first free gap, not only after the person's last task (DEFECT_LOG #18)."""
    t = t0
    while True:
        start = earliest_manual_start(t, duration, instance.shifts)
        if start is None:
            return None
        clash = next((e for s, e in busy if s < start + duration and start < e), None)
        if clash is None:
            return start
        t = clash


def _place_manual(
    t0: int, duration: int, lanes: list[list[tuple[int, int]]], instance: Instance
) -> tuple[int, int] | None:
    """(lane, start) of the earliest fit for one person, or None."""
    best: tuple[int, int] | None = None
    for lane, busy in enumerate(lanes):
        start = _earliest_gap(t0, duration, busy, instance)
        if start is not None and (best is None or start < best[1]):
            best = (lane, start)
    return best


def _plan_job(
    job: Job, instance: Instance, state: _State, fixed: Fixed | None, pick: Pick, d: Durations
) -> tuple[JobPlan, list[list[tuple[int, int]]]] | None:
    """The job's plan and the staff lanes after it, without changing `state`; None if it cannot
    fit the horizon."""
    durations = task_durations(job, d)
    lanes = [list(busy) for busy in state.lanes]
    slots: list[Slot] = []
    t = 0

    def manual(kind: TaskKind, after: int) -> int | None:
        placed = _place_manual(after, durations[kind], lanes, instance)
        if placed is None:
            return None
        lane, start = placed
        lanes[lane].append((start, start + durations[kind]))
        slots.append(Slot(kind, start, start + durations[kind]))
        return start + durations[kind]

    if fixed is None and "prep" in durations:
        end = manual("prep", 0)
        if end is None:
            return None
        t = end

    if fixed is not None:
        machine, start = fixed.machine, fixed.start
    else:
        options: list[tuple[tuple[int, str], str, int]] = []
        for m in eligible_machines(job, instance.machines):
            last = state.last_material[m.code]
            gap = d.changeover_minutes if last is not None and last != job.material else 0
            start_at = earliest_machine_start(
                max(t, job.release, state.machine_free[m.code] + gap), instance.shifts
            )
            if start_at is None:
                continue
            key = start_at if pick == "start" else start_at + durations["machine"]
            options.append(((key, m.code), m.code, start_at))
        if not options:
            return None
        _, machine, start = min(options)
    end = start + durations["machine"]
    if end > instance.horizon:
        return None
    slots.append(Slot("machine", start, end))
    t = end

    for kind in ("post", "finish"):
        if kind in durations:
            after = manual(kind, t)
            if after is None:
                return None
            t = after
    return JobPlan(job.id, machine, tuple(slots)), lanes


def list_schedule(
    instance: Instance, order: list[Job], pick: Pick, d: Durations, method: str
) -> Schedule:
    state = _State(
        machine_free={m.code: 0 for m in instance.machines},
        last_material={m.code: None for m in instance.machines},
        lanes=[[] for _ in range(instance.staff)],
    )
    fixed = {f.job_id: f for f in instance.fixed}
    # Fixed tasks are already on their machines, so they are placed before anything else.
    ordered = [j for j in order if j.id in fixed] + [j for j in order if j.id not in fixed]
    plans: list[JobPlan] = []
    unscheduled: list[str] = []
    for job in ordered:
        result = _plan_job(job, instance, state, fixed.get(job.id), pick, d)
        if result is None:
            unscheduled.append(job.id)
            continue
        plan, lanes = result
        machine_slot = plan.slot("machine")
        assert machine_slot is not None
        state.lanes = lanes
        state.machine_free[plan.machine] = machine_slot.end
        state.last_material[plan.machine] = job.material
        plans.append(plan)
    return Schedule(method, tuple(plans), tuple(unscheduled))


def fcfs(instance: Instance, d: Durations) -> Schedule:
    return list_schedule(
        instance, sorted(instance.jobs, key=lambda j: j.arrival), "start", d, "fcfs"
    )


def edd(instance: Instance, d: Durations) -> Schedule:
    order = sorted(instance.jobs, key=lambda j: (j.due, not j.rush, j.arrival))
    return list_schedule(instance, order, "finish", d, "edd")
