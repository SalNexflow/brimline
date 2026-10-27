"""How long each task takes, and which machines can do a job. Pure functions.

The print-time formula is deliberately simple (setup + quantity x minutes per part + cool-down);
a slicer could replace it later. This is stated in the README's limits.
"""

from brimline_engine.scheduling.config import Durations
from brimline_engine.scheduling.model import Fixed, Job, Machine, TaskKind


def task_durations(job: Job, d: Durations) -> dict[TaskKind, int]:
    """Durations of the job's tasks in order; tasks of zero length are left out."""
    durations: dict[TaskKind, int] = {
        "prep": d.prep_minutes,
        "machine": d.setup_minutes
        + job.quantity * job.minutes_per_part
        + d.cool_down_minutes.get(job.process, 0),
        "post": job.quantity * job.post_minutes_per_part,
        "finish": d.finish_base_minutes + job.quantity * d.finish_minutes_per_part,
    }
    return {kind: minutes for kind, minutes in durations.items() if minutes > 0}


def job_durations(job: Job, d: Durations, fixed: Fixed | None) -> dict[TaskKind, int]:
    """As task_durations, for a job whose machine task may be fixed: then its prep is done, and
    its machine task lasts as long as it really did (or is expected to), if that is known."""
    durations = task_durations(job, d)
    if fixed is not None:
        durations.pop("prep", None)
        if fixed.end is not None:
            durations["machine"] = fixed.end - fixed.start
    return durations


def fits(job: Job, machine: Machine) -> bool:
    """Right process, supported material, and the part fits the build volume in some
    orientation (both sides sorted, so a part may be turned)."""
    return (
        job.process == machine.process
        and job.material in machine.materials
        and all(p <= b for p, b in zip(sorted(job.part_mm), sorted(machine.build_mm), strict=True))
    )


def eligible_machines(job: Job, machines: tuple[Machine, ...]) -> list[Machine]:
    return [m for m in machines if fits(job, m)]
