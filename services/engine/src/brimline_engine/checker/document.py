"""The checker's own view of a plan document (format brimline-plan/1), parsed strictly.

These types are deliberately separate from the scheduler's: the checker must not share code or
assumptions with what it checks (docs/SCHEDULE_RULES.md). A document that does not have the
expected shape is rejected with DocumentError; it is never guessed at.
"""

from dataclasses import dataclass
from typing import Any

FORMAT = "brimline-plan/1"
KINDS = ("prep", "machine", "post", "finish")


class DocumentError(ValueError):
    """The document is not a well-formed brimline-plan/1 document."""


@dataclass(frozen=True)
class Machine:
    code: str
    process: str
    materials: frozenset[str]
    build_mm: tuple[int, ...]


@dataclass(frozen=True)
class Job:
    id: str
    arrival: int
    material: str
    process: str
    part_mm: tuple[int, ...]
    quantity: int
    minutes_per_part: int
    post_minutes_per_part: int
    due: int
    rush: bool
    release: int


@dataclass(frozen=True)
class Fixed:
    job_id: str
    machine: str
    start: int


@dataclass(frozen=True)
class Instance:
    name: str
    horizon: int
    machines: tuple[Machine, ...]
    jobs: tuple[Job, ...]
    fixed: tuple[Fixed, ...]


@dataclass(frozen=True)
class Task:
    kind: str
    start: int
    end: int


@dataclass(frozen=True)
class PlannedJob:
    job_id: str
    machine: str
    tasks: tuple[Task, ...]


@dataclass(frozen=True)
class Plan:
    method: str
    jobs: tuple[PlannedJob, ...]
    unscheduled: tuple[str, ...]


@dataclass(frozen=True)
class Document:
    instance: Instance
    plan: Plan


def _get(d: object, key: str, kind: type, where: str) -> Any:  # noqa: ANN401 - type checked below at run time
    if not isinstance(d, dict) or key not in d:
        raise DocumentError(f"{where}: missing '{key}'")
    value = d[key]
    # bool is a subclass of int in Python; a minute must not be `true`.
    if kind is int and (isinstance(value, bool) or not isinstance(value, int)):
        raise DocumentError(f"{where}.{key}: expected a whole number, got {value!r}")
    if kind is not int and not isinstance(value, kind):
        raise DocumentError(f"{where}.{key}: expected {kind.__name__}, got {value!r}")
    return value


def _ints(d: object, key: str, where: str) -> tuple[int, ...]:
    values = _get(d, key, list, where)
    if len(values) != 3 or any(isinstance(v, bool) or not isinstance(v, int) for v in values):
        raise DocumentError(f"{where}.{key}: expected three whole numbers, got {values!r}")
    return tuple(values)


def _strs(d: object, key: str, where: str) -> tuple[str, ...]:
    values = _get(d, key, list, where)
    if any(not isinstance(v, str) for v in values):
        raise DocumentError(f"{where}.{key}: expected a list of text, got {values!r}")
    return tuple(values)


def _machine(d: object, where: str) -> Machine:
    return Machine(
        code=_get(d, "code", str, where),
        process=_get(d, "process", str, where),
        materials=frozenset(_strs(d, "materials", where)),
        build_mm=_ints(d, "build_mm", where),
    )


def _job(d: object, where: str) -> Job:
    return Job(
        id=_get(d, "id", str, where),
        arrival=_get(d, "arrival", int, where),
        material=_get(d, "material", str, where),
        process=_get(d, "process", str, where),
        part_mm=_ints(d, "part_mm", where),
        quantity=_get(d, "quantity", int, where),
        minutes_per_part=_get(d, "minutes_per_part", int, where),
        post_minutes_per_part=_get(d, "post_minutes_per_part", int, where),
        due=_get(d, "due", int, where),
        rush=_get(d, "rush", bool, where),
        release=_get(d, "release", int, where),
    )


def _fixed(d: object, where: str) -> Fixed:
    return Fixed(
        job_id=_get(d, "job_id", str, where),
        machine=_get(d, "machine", str, where),
        start=_get(d, "start", int, where),
    )


def _task(d: object, where: str) -> Task:
    kind = _get(d, "kind", str, where)
    if kind not in KINDS:
        raise DocumentError(f"{where}.kind: unknown task kind {kind!r}")
    return Task(kind, _get(d, "start", int, where), _get(d, "end", int, where))


def _planned(d: object, where: str) -> PlannedJob:
    tasks = _get(d, "tasks", list, where)
    return PlannedJob(
        job_id=_get(d, "job_id", str, where),
        machine=_get(d, "machine", str, where),
        tasks=tuple(_task(t, f"{where}.tasks[{i}]") for i, t in enumerate(tasks)),
    )


def parse(doc: object) -> Document:
    if _get(doc, "format", str, "document") != FORMAT:
        raise DocumentError(f"document: format must be {FORMAT!r}")
    inst = _get(doc, "instance", dict, "document")
    plan = _get(doc, "plan", dict, "document")
    machines = _get(inst, "machines", list, "instance")
    jobs = _get(inst, "jobs", list, "instance")
    fixed = _get(inst, "fixed", list, "instance")
    planned = _get(plan, "jobs", list, "plan")
    return Document(
        instance=Instance(
            name=_get(inst, "name", str, "instance"),
            horizon=_get(inst, "horizon", int, "instance"),
            machines=tuple(_machine(m, f"machines[{i}]") for i, m in enumerate(machines)),
            jobs=tuple(_job(j, f"jobs[{i}]") for i, j in enumerate(jobs)),
            fixed=tuple(_fixed(f, f"fixed[{i}]") for i, f in enumerate(fixed)),
        ),
        plan=Plan(
            method=_get(plan, "method", str, "plan"),
            jobs=tuple(_planned(p, f"plan.jobs[{i}]") for i, p in enumerate(planned)),
            unscheduled=_strs(plan, "unscheduled", "plan"),
        ),
    )
