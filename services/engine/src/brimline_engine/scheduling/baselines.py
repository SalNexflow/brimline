"""Two greedy baselines: first-come-first-served (FCFS) and earliest due date (EDD).

One list scheduler, two job orders:
  FCFS: jobs in arrival order.
  EDD:  jobs by due date (rush first on ties, then arrival).
Each job's tasks are then placed one after another, each as early as the rules allow, on the
machine where its machine task can start earliest (ties: machine code). Earlier placements are
never moved, but a task may go into any free gap before them: on a machine (respecting the
changeover time to the jobs on both sides) and in a person's day. Without gap filling the
baselines would be a strawman (DEFECT_LOG #18, #19).
Both obey the same rules as the CP-SAT model and the same instance checks (validation.py).
A job that cannot fit the horizon is reported as unscheduled, never silently dropped; a fixed
task keeps blocking its machine even then.
"""

from dataclasses import dataclass

from brimline_engine.scheduling.calendar import earliest_machine_start, earliest_manual_start
from brimline_engine.scheduling.config import Durations
from brimline_engine.scheduling.durations import eligible_machines, job_durations
from brimline_engine.scheduling.model import Fixed, Instance, Job, JobPlan, Schedule, Slot, TaskKind
from brimline_engine.scheduling.validation import check_instance

Busy = list[tuple[int, int, str]]  # (start, end, material) of machine tasks already placed


@dataclass
class _State:
    machines: dict[str, Busy]
    lanes: list[list[tuple[int, int]]]  # each person's busy [start, end) intervals


def _earliest_gap(
    t0: int, duration: int, busy: list[tuple[int, int]], instance: Instance
) -> int | None:
    """Earliest start >= t0 inside a shift where this person is free for `duration` minutes."""
    t = t0
    while True:
        start = earliest_manual_start(t, duration, instance.shifts)
        if start is None:
            return None
        clash = next((e for s, e in busy if s < start + duration and start < e), None)
        if clash is None:
            return start
        t = clash


def _earliest_machine_gap(
    t0: int, duration: int, material: str, busy: Busy, instance: Instance, d: Durations
) -> int | None:
    """Earliest start >= t0 inside a shift where the machine is free for `duration` minutes,
    with the changeover time kept to every job of a different material before and after."""
    t = t0
    while True:
        start = earliest_machine_start(t, instance.shifts)
        if start is None or start + duration > instance.horizon:
            return None
        end = start + duration
        clash = None
        for s, e, other in busy:
            gap = d.changeover_minutes if other != material else 0
            if not (end + gap <= s or start >= e + gap):
                clash = e + gap
                break
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
    job: Job, instance: Instance, state: _State, fixed: Fixed | None, d: Durations
) -> tuple[JobPlan | None, list[list[tuple[int, int]]], tuple[str, int, int] | None]:
    """(plan or None if it cannot fit, staff lanes after it, machine task to block)."""
    durations = job_durations(job, d, fixed)
    lanes = [list(busy) for busy in state.lanes]
    slots: list[Slot] = []
    t = instance.plan_start  # nothing that is not already running starts in the past

    def manual(kind: TaskKind, after: int) -> int | None:
        placed = _place_manual(after, durations[kind], lanes, instance)
        if placed is None:
            return None
        lane, start = placed
        lanes[lane].append((start, start + durations[kind]))
        slots.append(Slot(kind, start, start + durations[kind]))
        return start + durations[kind]

    if fixed is not None:
        machine, start = fixed.machine, fixed.start  # a fact: no checks, prep already done
    else:
        if "prep" in durations:
            end = manual("prep", instance.plan_start)
            if end is None:
                return None, state.lanes, None
            t = end
        options = []
        for m in eligible_machines(job, instance.machines):
            at = _earliest_machine_gap(
                max(t, job.release),
                durations["machine"],
                job.material,
                state.machines[m.code],
                instance,
                d,
            )
            if at is not None:
                options.append((at, m.code))
        if not options:
            return None, state.lanes, None
        start, machine = min(options)
    end = start + durations["machine"]
    block = (machine, start, end)
    slots.append(Slot("machine", start, end))
    t = max(end, instance.plan_start)
    for kind in ("post", "finish"):
        if kind in durations:
            after = manual(kind, t)
            if after is None:
                return None, state.lanes, block if fixed is not None else None
            t = after
    return JobPlan(job.id, machine, tuple(slots)), lanes, block


def list_schedule(instance: Instance, order: list[Job], d: Durations, method: str) -> Schedule:
    check_instance(instance, d)
    state = _State(
        machines={m.code: [] for m in instance.machines}, lanes=[[] for _ in range(instance.staff)]
    )
    fixed = {f.job_id: f for f in instance.fixed}
    # Fixed tasks are already on their machines, so they are placed before anything else.
    ordered = [j for j in order if j.id in fixed] + [j for j in order if j.id not in fixed]
    plans: list[JobPlan] = []
    unscheduled: list[str] = []
    for job in ordered:
        plan, lanes, block = _plan_job(job, instance, state, fixed.get(job.id), d)
        if block is not None:
            state.machines[block[0]].append((block[1], block[2], job.material))
        if plan is None:
            unscheduled.append(job.id)
            continue
        state.lanes = lanes
        plans.append(plan)
    return Schedule(method, tuple(plans), tuple(unscheduled))


def fcfs(instance: Instance, d: Durations) -> Schedule:
    return list_schedule(instance, sorted(instance.jobs, key=lambda j: j.arrival), d, "fcfs")


def edd(instance: Instance, d: Durations) -> Schedule:
    order = sorted(instance.jobs, key=lambda j: (j.due, not j.rush, j.arrival))
    return list_schedule(instance, order, d, "edd")
