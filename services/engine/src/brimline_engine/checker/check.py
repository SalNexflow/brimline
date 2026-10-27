"""Check a plan against every rule in docs/SCHEDULE_RULES.md and recompute its metrics.

Every violation found is reported (not only the first), with its rule code, so a planner sees
everything wrong at once and the tests can say exactly what should be caught.
"""

from dataclasses import dataclass
from itertools import pairwise

from brimline_engine.checker.document import Document, Fixed, Instance, Job, Plan, PlannedJob
from brimline_engine.checker.rules import Rules, durations

MANUAL = ("prep", "post", "finish")


@dataclass(frozen=True)
class Violation:
    code: str  # the rule's name in docs/SCHEDULE_RULES.md, for example "machine_overlap"
    job: str | None
    detail: str


@dataclass(frozen=True)
class Deadline:
    job: str
    due: int
    completion: int
    tardiness: int
    rush: bool


@dataclass(frozen=True)
class Metrics:
    scheduled: int
    unscheduled: int
    late_jobs: int
    late_or_unscheduled: int
    rush_late_jobs: int
    total_lateness_minutes: int
    changeovers: int
    utilisation: float
    finish_time: int
    objective: int


@dataclass(frozen=True)
class CheckResult:
    valid: bool
    violations: tuple[Violation, ...]
    warnings: tuple[Violation, ...]  # "suspicious_unscheduled": a pointer for a human, not a rule
    deadlines: tuple[Deadline, ...]
    metrics: Metrics | None  # None when the instance itself is impossible

    def codes(self) -> set[str]:
        return {v.code for v in self.violations}


@dataclass(frozen=True)
class _Run:
    """A machine task on a machine's timeline."""

    job: str
    start: int
    end: int
    material: str
    fixed: bool  # a fact from the instance, at exactly its fixed place


def _fits(
    job: Job, machine_process: str, materials: frozenset[str], build: tuple[int, ...]
) -> bool:
    return (
        job.process == machine_process
        and job.material in materials
        and all(p <= b for p, b in zip(sorted(job.part_mm), sorted(build), strict=True))
    )


def _in_one_window(start: int, end: int, r: Rules) -> bool:
    return any(lo <= start and end <= hi for lo, hi in r.windows)


def _starts_in_window(start: int, r: Rules) -> bool:
    return any(lo <= start < hi for lo, hi in r.windows)


def instance_problems(inst: Instance, r: Rules) -> list[Violation]:
    """R17: an impossible instance. The plan cannot be judged against it."""
    out: list[Violation] = []
    jobs: dict[str, Job] = {}
    for j in inst.jobs:
        if j.id in jobs:
            out.append(Violation("bad_instance", j.id, "two jobs share this id"))
        jobs[j.id] = j
        if j.quantity < 1 or j.minutes_per_part < 1:
            out.append(
                Violation("bad_instance", j.id, "quantity and minutes_per_part must be >= 1")
            )
        if j.post_minutes_per_part < 0 or min(j.part_mm) < 1:
            out.append(Violation("bad_instance", j.id, "negative post time or part size below 1"))
        if j.post_processing is not None:
            unknown = [k for k in j.post_processing if k not in r.post_process]
            minutes = sum(r.post_process.get(k, 0) for k in j.post_processing)
            if unknown or minutes != j.post_minutes_per_part:
                out.append(
                    Violation(
                        "bad_instance",
                        j.id,
                        f"post steps {list(j.post_processing)} take {minutes} min per part in"
                        f" the config, the document says {j.post_minutes_per_part}"
                        + (f"; unknown steps {unknown}" if unknown else ""),
                    )
                )
    if inst.horizon < 1:
        out.append(Violation("bad_instance", None, f"horizon {inst.horizon} is not positive"))
    # The plan was made for these shifts and this staff; they must be what the config says, or
    # the checker would judge it against different rules than the scheduler used.
    if inst.shifts is not None and inst.shifts != r.windows:
        out.append(
            Violation("bad_instance", None, "the instance's shifts differ from the config's")
        )
    if inst.staff is not None and inst.staff != r.staff:
        out.append(
            Violation("bad_instance", None, f"instance staff {inst.staff}, config {r.staff}")
        )
    codes = [m.code for m in inst.machines]
    if len(set(codes)) != len(codes):
        out.append(Violation("bad_instance", None, "two machines share a code"))
    fixed_runs: dict[str, list[tuple[int, int, str]]] = {}
    seen: set[str] = set()
    for f in inst.fixed:
        if f.job_id not in jobs:
            out.append(Violation("bad_instance", f.job_id, "fixed task for an unknown job"))
            continue
        if f.machine not in codes:
            out.append(Violation("bad_instance", f.job_id, f"fixed on unknown machine {f.machine}"))
            continue
        if f.job_id in seen:
            out.append(Violation("bad_instance", f.job_id, "two fixed tasks for one job"))
            continue
        seen.add(f.job_id)
        if f.end is not None and f.end <= f.start:
            out.append(
                Violation("bad_instance", f.job_id, f"fixed task ends {f.end}, not after {f.start}")
            )
            continue
        length = durations(jobs[f.job_id], r, f)["machine"]
        fixed_runs.setdefault(f.machine, []).append((f.start, f.start + length, f.job_id))
    for machine, runs in fixed_runs.items():
        runs.sort()
        for (_, end, a), (start, _, b) in pairwise(runs):
            if start < end:
                out.append(
                    Violation("bad_instance", b, f"fixed tasks {a} and {b} overlap on {machine}")
                )
    return out


def _check_job(
    pj: PlannedJob, job: Job, inst: Instance, r: Rules, fx: Fixed | None
) -> list[Violation]:
    out: list[Violation] = []

    def v(code: str, detail: str) -> None:
        out.append(Violation(code, job.id, detail))

    expected = durations(job, r, fx)
    kinds = [t.kind for t in pj.tasks]
    if kinds != list(expected):
        v("wrong_tasks", f"tasks {kinds}, expected {list(expected)}")
    for t in pj.tasks:
        if t.kind in expected and t.end - t.start != expected[t.kind]:
            v("wrong_duration", f"{t.kind} lasts {t.end - t.start}, expected {expected[t.kind]}")
    for a, b in pairwise(pj.tasks):
        if b.start < a.end:
            v("task_order", f"{b.kind} starts {b.start} before {a.kind} ends {a.end}")
    machines = {m.code: m for m in inst.machines}
    machine = machines.get(pj.machine)
    if machine is None:
        v("unknown_machine", f"machine {pj.machine} does not exist")
    for t in pj.tasks:
        is_fact = t.kind == "machine" and fx is not None
        if not is_fact and t.start < inst.plan_start:
            v("before_plan_start", f"{t.kind} starts {t.start}, planning was at {inst.plan_start}")
        if t.kind == "machine":
            if fx is not None:
                if (pj.machine, t.start) != (fx.machine, fx.start):
                    v(
                        "fixed_moved",
                        f"fixed at {(fx.machine, fx.start)}, planned at {(pj.machine, t.start)}",
                    )
            else:
                if machine is not None and not _fits(
                    job, machine.process, machine.materials, machine.build_mm
                ):
                    v("not_eligible", f"{job.process}/{job.material}/{job.part_mm} on {pj.machine}")
                if t.start < job.release:
                    v("before_release", f"starts {t.start}, material on hand at {job.release}")
                if not _starts_in_window(t.start, r):
                    v("machine_off_shift", f"machine task starts {t.start}, outside every shift")
        elif not _in_one_window(t.start, t.end, r):
            v("manual_off_shift", f"{t.kind} {t.start}-{t.end} is not inside one shift")
        if t.end > inst.horizon and not is_fact:
            v("past_horizon", f"{t.kind} ends {t.end}, horizon {inst.horizon}")
    return out


def _timeline_problems(runs: dict[str, list[_Run]], r: Rules) -> list[Violation]:
    out: list[Violation] = []
    for machine, items in runs.items():
        items = sorted(items, key=lambda x: (x.start, x.end))
        latest: _Run | None = None  # the run that ends last among those already passed
        for prev, nxt in pairwise(items):
            if latest is None or prev.end > latest.end:
                latest = prev
            if nxt.start < latest.end:
                out.append(
                    Violation(
                        "machine_overlap",
                        nxt.job,
                        f"{latest.job} {latest.start}-{latest.end} and {nxt.job} "
                        f"{nxt.start}-{nxt.end} on {machine}",
                    )
                )
            elif (
                prev.material != nxt.material
                and not (prev.fixed and nxt.fixed)
                and nxt.start - prev.end < r.changeover
            ):
                out.append(
                    Violation(
                        "changeover",
                        nxt.job,
                        f"{prev.job} ({prev.material}) ends {prev.end}, {nxt.job} ({nxt.material}) "
                        f"starts {nxt.start} on {machine}: gap {nxt.start - prev.end}, "
                        f"needs {r.changeover}",
                    )
                )
    return out


def _staff_problems(manual: list[tuple[int, int, str]], r: Rules) -> list[Violation]:
    # Sweep the start and end minutes; at equal minutes ends come first ([start, end) intervals).
    events = sorted([(s, 1, j) for s, _, j in manual] + [(e, -1, j) for _, e, j in manual])
    out: list[Violation] = []
    running: set[str] = set()
    count = 0
    over = False
    for minute, step, job in events:
        count += step
        if step == 1:
            running.add(job)
        else:
            running.discard(job)
        if count > r.staff and not over:
            names = ", ".join(sorted(running))
            out.append(
                Violation(
                    "staff_overload", job, f"{count} manual tasks at minute {minute}: {names}"
                )
            )
        over = count > r.staff
    return out


def metrics(
    inst: Instance, plans: list[PlannedJob], unscheduled: int, r: Rules
) -> tuple[Metrics, tuple[Deadline, ...]]:
    jobs = {j.id: j for j in inst.jobs}
    fixed = {f.job_id: f for f in inst.fixed}
    w = r.weights
    late = rush_late = lateness = objective = busy = finish = 0
    deadlines = []
    by_machine: dict[str, list[tuple[int, str, bool]]] = {}  # (start, material, fixed)
    for pj in plans:
        job = jobs[pj.job_id]
        if not pj.tasks:
            continue
        completion = max(t.end for t in pj.tasks)
        tardiness = max(0, completion - job.due)
        m = w.rush_multiplier if job.rush else 1
        late += tardiness > 0
        rush_late += tardiness > 0 and job.rush
        lateness += tardiness
        objective += m * (w.late_job * (tardiness > 0) + w.tardiness_per_minute * tardiness)
        finish = max(finish, completion)
        deadlines.append(Deadline(job.id, job.due, completion, tardiness, job.rush))
        for t in pj.tasks:
            if t.kind == "machine":
                busy += max(0, t.end - max(t.start, 0))  # count only time from minute 0
                by_machine.setdefault(pj.machine, []).append(
                    (t.start, job.material, job.id in fixed)
                )
    # A fixed task of an unscheduled job still runs on its machine, so it is part of the
    # material sequence. Two fixed tasks back to back needed no changeover, so they count none.
    planned = {pj.job_id for pj in plans}
    for f in inst.fixed:
        if f.job_id not in planned:
            by_machine.setdefault(f.machine, []).append((f.start, jobs[f.job_id].material, True))
    changes = 0
    for items in by_machine.values():
        items.sort()
        changes += sum(
            1 for (_, a, fa), (_, b, fb) in pairwise(items) if a != b and not (fa and fb)
        )
    objective += w.changeover * changes + w.finish_time_per_minute * finish
    objective += w.unscheduled_job * unscheduled
    capacity = len(inst.machines) * finish
    return (
        Metrics(
            scheduled=len(plans),
            unscheduled=unscheduled,
            late_jobs=late,
            late_or_unscheduled=late + unscheduled,
            rush_late_jobs=rush_late,
            total_lateness_minutes=lateness,
            changeovers=changes,
            utilisation=busy / capacity if capacity else 0.0,
            finish_time=finish,
            objective=objective,
        ),
        tuple(deadlines),
    )


def _earliest_manual(t: int, length: int, r: Rules, horizon: int) -> int | None:
    for lo, hi in r.windows:
        s = max(t, lo)
        if s + length <= hi and s + length <= horizon:
            return s
    return None


def _earliest_machine(
    t: int, length: int, material: str, busy: list[_Run], r: Rules, horizon: int
) -> int | None:
    while True:
        s = next((max(t, lo) for lo, hi in r.windows if t < hi), None)
        if s is None or s + length > horizon:
            return None
        clash = None
        for b in busy:
            gap = r.changeover if b.material != material else 0
            if s < b.end + gap and b.start < s + length + gap:
                clash = b.end + gap
                break
        if clash is None:
            return s
        t = clash


def _witness(
    job: Job,
    inst: Instance,
    r: Rules,
    runs: dict[str, list[_Run]],
    fx: Fixed | None,
) -> str | None:
    """A placement of this one job alone (ignoring staff), or None. See SCHEDULE_RULES.md."""
    d = durations(job, r, fx)
    if fx is not None:
        machine, start = fx.machine, fx.start
    else:
        t = inst.plan_start
        if "prep" in d:
            p = _earliest_manual(inst.plan_start, d["prep"], r, inst.horizon)
            if p is None:
                return None
            t = p + d["prep"]
        if job.release >= inst.horizon:
            return None
        options = []
        for m in inst.machines:
            if _fits(job, m.process, m.materials, m.build_mm):
                s = _earliest_machine(
                    max(t, job.release),
                    d["machine"],
                    job.material,
                    runs.get(m.code, []),
                    r,
                    inst.horizon,
                )
                if s is not None:
                    options.append((s, m.code))
        if not options:
            return None
        start, machine = min(options)
    t = max(start + d["machine"], inst.plan_start)
    for kind in ("post", "finish"):
        if kind in d:
            s = _earliest_manual(t, d[kind], r, inst.horizon)
            if s is None:
                return None
            t = s + d[kind]
    return f"could run on {machine} from {start}, done by {t} (staff not considered)"


def check(doc: Document, r: Rules) -> CheckResult:
    inst, plan = doc.instance, doc.plan
    bad = instance_problems(inst, r)
    if bad:
        return CheckResult(False, tuple(bad), (), (), None)
    return _check_plan(inst, plan, r)


def _check_plan(inst: Instance, plan: Plan, r: Rules) -> CheckResult:
    jobs = {j.id: j for j in inst.jobs}
    fixed = {f.job_id: f for f in inst.fixed}
    out: list[Violation] = []
    seen: set[str] = set()
    planned: list[PlannedJob] = []
    for pj in plan.jobs:
        if pj.job_id not in jobs:
            out.append(Violation("unknown_job", pj.job_id, "planned job is not in the instance"))
        elif pj.job_id in seen:
            out.append(Violation("duplicate_job", pj.job_id, "planned more than once"))
        else:
            seen.add(pj.job_id)
            planned.append(pj)
    unscheduled: list[str] = []
    for job_id in plan.unscheduled:
        if job_id not in jobs:
            out.append(Violation("unknown_job", job_id, "unscheduled job is not in the instance"))
        elif job_id in seen:
            out.append(Violation("duplicate_job", job_id, "both planned and unscheduled, or twice"))
        else:
            seen.add(job_id)
            unscheduled.append(job_id)
    for j in inst.jobs:
        if j.id not in seen:
            out.append(Violation("missing_job", j.id, "neither planned nor listed as unscheduled"))

    runs: dict[str, list[_Run]] = {}
    manual: list[tuple[int, int, str]] = []
    for pj in planned:
        job = jobs[pj.job_id]
        out += _check_job(pj, job, inst, r, fixed.get(job.id))
        for t in pj.tasks:
            if t.kind == "machine":
                fx = fixed.get(job.id)
                fact = fx is not None and (fx.machine, fx.start) == (pj.machine, t.start)
                runs.setdefault(pj.machine, []).append(
                    _Run(job.id, t.start, t.end, job.material, fact)
                )
            else:
                manual.append((t.start, t.end, job.id))
    # A fixed task blocks its machine even when its job is not planned (R13).
    planned_ids = {pj.job_id for pj in planned}
    for f in inst.fixed:
        if f.job_id not in planned_ids:
            job = jobs[f.job_id]
            end = f.start + durations(job, r, f)["machine"]
            runs.setdefault(f.machine, []).append(_Run(job.id, f.start, end, job.material, True))
    out += _timeline_problems(runs, r)
    out += _staff_problems(manual, r)

    warnings = []
    for job_id in unscheduled:
        found = _witness(jobs[job_id], inst, r, runs, fixed.get(job_id))
        if found is not None:
            warnings.append(Violation("suspicious_unscheduled", job_id, found))
    m, deadlines = metrics(inst, planned, len(unscheduled), r)
    return CheckResult(not out, tuple(out), tuple(warnings), deadlines, m)
