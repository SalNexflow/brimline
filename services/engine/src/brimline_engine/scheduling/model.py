"""The scheduling problem and its answer, as plain data.

Time is whole minutes from the start of the horizon (Monday 08:00 in the shop).

Each job becomes up to four ordered tasks:
  prep     manual   check the file, slice, load            (needs one person, inside a shift)
  machine  machine  print or machine, then cool-down        (one machine; must START in a shift)
  post     manual   sanding / painting / assembly, if asked (needs one person, inside a shift)
  finish   manual   quality check and packing               (needs one person, inside a shift)
A task with zero duration is left out.
"""

from dataclasses import dataclass, field
from typing import Literal

Process = Literal["fdm", "resin", "cnc"]
TaskKind = Literal["prep", "machine", "post", "finish"]
TASK_ORDER: tuple[TaskKind, ...] = ("prep", "machine", "post", "finish")
MANUAL: frozenset[TaskKind] = frozenset({"prep", "post", "finish"})


@dataclass(frozen=True)
class Machine:
    code: str
    process: Process
    materials: frozenset[str]
    build_mm: tuple[int, int, int]


@dataclass(frozen=True)
class Job:
    id: str
    arrival: int  # order in which the job came in; FCFS uses it
    material: str
    process: Process
    part_mm: tuple[int, int, int]
    quantity: int
    minutes_per_part: int  # machine time per part
    post_minutes_per_part: int  # 0 = no post-processing asked for
    due: int  # minute by which the job should be packed
    rush: bool
    release: int = 0  # minute the material is on hand; the machine task cannot start earlier
    # The post-processing steps asked for (raw input), when known: post_minutes_per_part is then
    # their configured minutes added up, and the checker recomputes that sum. None when the
    # minutes are given directly (generated instances).
    post_processing: tuple[str, ...] | None = None

    def __post_init__(self) -> None:
        # Every job has real machine work; a zero-length machine task would break every method.
        if self.quantity < 1 or self.minutes_per_part < 1:
            raise ValueError(f"job {self.id}: quantity and minutes_per_part must be at least 1")


@dataclass(frozen=True)
class Fixed:
    """A machine task already running or done: it keeps its machine and start. Its prep is
    treated as done. `end` is when it really ended (done) or is expected to (running); without
    it the task lasts its formula duration."""

    job_id: str
    machine: str
    start: int
    end: int | None = None


@dataclass(frozen=True)
class Instance:
    name: str
    horizon: int
    machines: tuple[Machine, ...]
    jobs: tuple[Job, ...]
    shifts: tuple[tuple[int, int], ...]  # staffed [start, end) windows, sorted
    staff: int
    fixed: tuple[Fixed, ...] = ()
    plan_start: int = 0  # the moment of planning: nothing that is not fixed may start earlier


@dataclass(frozen=True)
class Slot:
    kind: TaskKind
    start: int
    end: int


@dataclass(frozen=True)
class JobPlan:
    job_id: str
    machine: str
    slots: tuple[Slot, ...]  # in task order

    def slot(self, kind: TaskKind) -> Slot | None:
        return next((s for s in self.slots if s.kind == kind), None)

    @property
    def completion(self) -> int:
        return self.slots[-1].end


@dataclass(frozen=True)
class Schedule:
    method: str
    plans: tuple[JobPlan, ...]
    unscheduled: tuple[str, ...]  # jobs that do not fit the horizon: reported, never dropped
    info: dict[str, object] = field(default_factory=dict)  # solver status, times, bounds
