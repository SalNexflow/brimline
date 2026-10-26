"""Scoring a schedule: the five bench metrics and the weighted objective.

Every method (FCFS, EDD, CP-SAT) is scored by this same code, so the comparison is fair. These
numbers come from scheduler-side code; the M4 checker will recompute them independently.

- late jobs: jobs packed after their due minute
- total lateness: sum over jobs of max(0, completion - due), in minutes
- changeovers: on each machine, consecutive jobs (by start) with different materials
- utilisation: machine-task minutes / (machines x finish time)
- finish time: the latest completion of any scheduled job
"""

from dataclasses import dataclass
from itertools import pairwise

from brimline_engine.scheduling.config import Weights
from brimline_engine.scheduling.model import Instance, Schedule


@dataclass(frozen=True)
class Metrics:
    scheduled: int
    unscheduled: int
    late_jobs: int
    rush_late_jobs: int
    total_lateness_minutes: int
    changeovers: int
    utilisation: float
    finish_time: int
    objective: int


def changeovers(instance: Instance, schedule: Schedule) -> int:
    material = {j.id: j.material for j in instance.jobs}
    by_machine: dict[str, list[tuple[int, str]]] = {}
    for plan in schedule.plans:
        slot = plan.slot("machine")
        if slot is not None:
            by_machine.setdefault(plan.machine, []).append((slot.start, material[plan.job_id]))
    count = 0
    for runs in by_machine.values():
        runs.sort()
        count += sum(1 for (_, a), (_, b) in pairwise(runs) if a != b)
    return count


def evaluate(instance: Instance, schedule: Schedule, weights: Weights) -> Metrics:
    jobs = {j.id: j for j in instance.jobs}
    late = rush_late = lateness = weighted = 0
    busy = finish = 0
    for plan in schedule.plans:
        job = jobs[plan.job_id]
        tardiness = max(0, plan.completion - job.due)
        multiplier = weights.rush_multiplier if job.rush else 1
        if tardiness > 0:
            late += 1
            rush_late += job.rush
            weighted += weights.late_job * multiplier
        lateness += tardiness
        weighted += weights.tardiness_per_minute * tardiness * multiplier
        finish = max(finish, plan.completion)
        machine_slot = plan.slot("machine")
        if machine_slot is not None:
            busy += machine_slot.end - machine_slot.start
    changes = changeovers(instance, schedule)
    weighted += weights.changeover * changes
    weighted += weights.finish_time_per_minute * finish
    weighted += weights.unscheduled_job * len(schedule.unscheduled)
    capacity = len(instance.machines) * finish
    return Metrics(
        scheduled=len(schedule.plans),
        unscheduled=len(schedule.unscheduled),
        late_jobs=late,
        rush_late_jobs=rush_late,
        total_lateness_minutes=lateness,
        changeovers=changes,
        utilisation=busy / capacity if capacity else 0.0,
        finish_time=finish,
        objective=weighted,
    )
