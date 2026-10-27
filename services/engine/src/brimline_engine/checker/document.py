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
    post_processing: tuple[str, ...] | None  # when given, the checker recomputes post minutes


@dataclass(frozen=True)
class Fixed:
    job_id: str
    machine: str
    start: int
    end: int | None  # when it really ended or is expected to; None: its formula duration


@dataclass(frozen=True)
class Downtime:
    machine: str
    start: int
    end: int


@dataclass(frozen=True)
class Instance:
    name: str
    horizon: int
    machines: tuple[Machine, ...]
    jobs: tuple[Job, ...]
    fixed: tuple[Fixed, ...]
    plan_start: int  # the moment of planning; 0 when the document does not say
    downtimes: tuple[Downtime, ...]  # machines that cannot be used; none when not given
    # The shifts and staff the plan was made for. Optional: when given, the checker compares
    # them with its own reading of config/scheduler.toml instead of trusting them.
    shifts: tuple[tuple[int, int], ...] | None
    staff: int | None


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


def _only(d: object, allowed: set[str], where: str) -> None:
    """Strict: an unknown key is a mistake (a typo, or a field this checker does not know)."""
    extra = set(d) - allowed if isinstance(d, dict) else set()
    if extra:
        raise DocumentError(f"{where}: unknown keys {sorted(extra)}")


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
    _only(d, {"code", "process", "materials", "build_mm"}, where)
    return Machine(
        code=_get(d, "code", str, where),
        process=_get(d, "process", str, where),
        materials=frozenset(_strs(d, "materials", where)),
        build_mm=_ints(d, "build_mm", where),
    )


def _job(d: object, where: str) -> Job:
    _only(d, {f for f in Job.__dataclass_fields__}, where)
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
        post_processing=_strs(d, "post_processing", where)
        if isinstance(d, dict) and d.get("post_processing") is not None
        else None,
    )


def _fixed(d: object, where: str) -> Fixed:
    _only(d, {"job_id", "machine", "start", "end"}, where)
    return Fixed(
        job_id=_get(d, "job_id", str, where),
        machine=_get(d, "machine", str, where),
        start=_get(d, "start", int, where),
        end=_get(d, "end", int, where)
        if isinstance(d, dict) and d.get("end") is not None
        else None,
    )


def _downtime(d: object, where: str) -> Downtime:
    _only(d, {"machine", "start", "end"}, where)
    return Downtime(
        machine=_get(d, "machine", str, where),
        start=_get(d, "start", int, where),
        end=_get(d, "end", int, where),
    )


def _task(d: object, where: str) -> Task:
    _only(d, {"kind", "start", "end"}, where)
    kind = _get(d, "kind", str, where)
    if kind not in KINDS:
        raise DocumentError(f"{where}.kind: unknown task kind {kind!r}")
    return Task(kind, _get(d, "start", int, where), _get(d, "end", int, where))


def _planned(d: object, where: str) -> PlannedJob:
    _only(d, {"job_id", "machine", "tasks"}, where)
    tasks = _get(d, "tasks", list, where)
    return PlannedJob(
        job_id=_get(d, "job_id", str, where),
        machine=_get(d, "machine", str, where),
        tasks=tuple(_task(t, f"{where}.tasks[{i}]") for i, t in enumerate(tasks)),
    )


def _shifts(inst: dict[str, Any]) -> tuple[tuple[int, int], ...] | None:
    if "shifts" not in inst:
        return None
    windows = _get(inst, "shifts", list, "instance")
    out = []
    for w in windows:
        if not (
            isinstance(w, list)
            and len(w) == 2
            and all(isinstance(v, int) and not isinstance(v, bool) for v in w)
        ):
            raise DocumentError(f"instance.shifts: expected [start, end] pairs, got {w!r}")
        out.append((w[0], w[1]))
    return tuple(out)


def parse(doc: object) -> Document:
    _only(doc, {"format", "instance", "plan"}, "document")
    if _get(doc, "format", str, "document") != FORMAT:
        raise DocumentError(f"document: format must be {FORMAT!r}")
    inst = _get(doc, "instance", dict, "document")
    plan = _get(doc, "plan", dict, "document")
    _only(
        inst,
        {
            "name",
            "horizon",
            "machines",
            "jobs",
            "fixed",
            "shifts",
            "staff",
            "plan_start",
            "downtimes",
        },
        "instance",
    )
    _only(plan, {"method", "jobs", "unscheduled"}, "plan")
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
            plan_start=_get(inst, "plan_start", int, "instance") if "plan_start" in inst else 0,
            downtimes=tuple(
                _downtime(d, f"downtimes[{i}]")
                for i, d in enumerate(_get(inst, "downtimes", list, "instance"))
            )
            if "downtimes" in inst
            else (),
            shifts=_shifts(inst),
            staff=_get(inst, "staff", int, "instance") if "staff" in inst else None,
        ),
        plan=Plan(
            method=_get(plan, "method", str, "plan"),
            jobs=tuple(_planned(p, f"plan.jobs[{i}]") for i, p in enumerate(planned)),
            unscheduled=_strs(plan, "unscheduled", "plan"),
        ),
    )
