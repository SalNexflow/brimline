"""Checks on an instance before any scheduler runs. Shared by every method, so they agree.

Fixed tasks (already running or done) are facts, not choices:
- two fixed tasks on the same machine must not overlap: that cannot have happened, so the
  instance is wrong and we stop with a clear error instead of producing a schedule;
- the changeover gap is NOT required between two fixed tasks: if reality skipped it, reality wins;
- a fixed machine task always blocks its machine, even if the rest of its job cannot fit.
"""

from itertools import pairwise

from brimline_engine.scheduling.config import Durations
from brimline_engine.scheduling.durations import task_durations
from brimline_engine.scheduling.model import Instance


class InstanceError(ValueError):
    """The instance itself is impossible (for example, overlapping fixed tasks)."""


def check_instance(instance: Instance, d: Durations) -> None:
    jobs = {j.id: j for j in instance.jobs}
    machines = {m.code for m in instance.machines}
    by_machine: dict[str, list[tuple[int, int, str]]] = {}
    for fixed in instance.fixed:
        if fixed.job_id not in jobs:
            raise InstanceError(f"fixed task for unknown job {fixed.job_id}")
        if fixed.machine not in machines:
            raise InstanceError(f"fixed task {fixed.job_id} on unknown machine {fixed.machine}")
        duration = task_durations(jobs[fixed.job_id], d)["machine"]
        by_machine.setdefault(fixed.machine, []).append(
            (fixed.start, fixed.start + duration, fixed.job_id)
        )
    for code, tasks in by_machine.items():
        tasks.sort()
        for (_, end, a), (start, _, b) in pairwise(tasks):
            if start < end:
                raise InstanceError(f"fixed tasks {a} and {b} overlap on {code}")
