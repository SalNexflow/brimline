"""Mutation testing for the checker: corrupt a valid plan in one known way and require the
checker to report it with the expected rule code.

Every operator is invalid by construction (a random nudge could leave a plan valid and look
like a miss). Operators work on the JSON document only, so they need nothing from the
scheduler. An operator that does not apply to a plan (no fixed task to move, no pair of
different materials to squeeze) returns None and is not counted.
"""

import copy
import random
from collections.abc import Callable
from itertools import pairwise
from typing import Any

from brimline_engine.checker.rules import Rules

Doc = dict[str, Any]
Operator = Callable[[Doc, random.Random, Rules], Doc | None]
MANUAL = ("prep", "post", "finish")


def _jobs(doc: Doc) -> list[dict[str, Any]]:
    return list(doc["plan"]["jobs"])


def _fixed_ids(doc: Doc) -> set[str]:
    return {f["job_id"] for f in doc["instance"]["fixed"]}


def _task(pj: dict[str, Any], kind: str) -> dict[str, Any] | None:
    return next((t for t in pj["tasks"] if t["kind"] == kind), None)


def _instance_job(doc: Doc, job_id: str) -> dict[str, Any]:
    return next(j for j in doc["instance"]["jobs"] if j["id"] == job_id)


def _pick(
    doc: Doc, rng: random.Random, free_only: bool = False
) -> tuple[Doc, dict[str, Any]] | None:
    """A copy of the document and one planned job in it (not a fixed one if free_only)."""
    out = copy.deepcopy(doc)
    fixed = _fixed_ids(out)
    choices = [pj for pj in _jobs(out) if not (free_only and pj["job_id"] in fixed)]
    return (out, rng.choice(choices)) if choices else None


def shorten_machine(doc: Doc, rng: random.Random, r: Rules) -> Doc | None:
    if (p := _pick(doc, rng)) is None:
        return None
    out, pj = p
    t = _task(pj, "machine")
    assert t is not None
    t["end"] -= 1
    return out


def lengthen_manual(doc: Doc, rng: random.Random, r: Rules) -> Doc | None:
    if (p := _pick(doc, rng)) is None:
        return None
    out, pj = p
    manual = [t for t in pj["tasks"] if t["kind"] in MANUAL]
    if not manual:
        return None
    rng.choice(manual)["end"] += 1
    return out


def drop_job(doc: Doc, rng: random.Random, r: Rules) -> Doc | None:
    if (p := _pick(doc, rng)) is None:
        return None
    out, pj = p
    out["plan"]["jobs"].remove(pj)
    return out


def duplicate_job(doc: Doc, rng: random.Random, r: Rules) -> Doc | None:
    if (p := _pick(doc, rng)) is None:
        return None
    out, pj = p
    out["plan"]["jobs"].append(copy.deepcopy(pj))
    return out


def also_unscheduled(doc: Doc, rng: random.Random, r: Rules) -> Doc | None:
    if (p := _pick(doc, rng)) is None:
        return None
    out, pj = p
    out["plan"]["unscheduled"].append(pj["job_id"])
    return out


def unknown_job(doc: Doc, rng: random.Random, r: Rules) -> Doc | None:
    if (p := _pick(doc, rng)) is None:
        return None
    out, pj = p
    pj["job_id"] += "-NOT-IN-INSTANCE"
    return out


def unknown_machine(doc: Doc, rng: random.Random, r: Rules) -> Doc | None:
    if (p := _pick(doc, rng, free_only=True)) is None:
        return None
    out, pj = p
    pj["machine"] = "NO-SUCH-MACHINE"
    return out


def drop_task(doc: Doc, rng: random.Random, r: Rules) -> Doc | None:
    if (p := _pick(doc, rng)) is None:
        return None
    out, pj = p
    pj["tasks"].pop(rng.randrange(len(pj["tasks"])))
    return out


def reverse_tasks(doc: Doc, rng: random.Random, r: Rules) -> Doc | None:
    if (p := _pick(doc, rng)) is None:
        return None
    out, pj = p
    if len(pj["tasks"]) < 2:
        return None
    pj["tasks"].reverse()
    return out


def prep_after_machine(doc: Doc, rng: random.Random, r: Rules) -> Doc | None:
    if (p := _pick(doc, rng, free_only=True)) is None:
        return None
    out, pj = p
    prep, machine = _task(pj, "prep"), _task(pj, "machine")
    if prep is None or machine is None:
        return None
    length = prep["end"] - prep["start"]
    prep["start"], prep["end"] = machine["end"], machine["end"] + length
    return out


def machine_off_shift(doc: Doc, rng: random.Random, r: Rules) -> Doc | None:
    """Start the machine task at a shift's closing minute, which belongs to no shift."""
    if (p := _pick(doc, rng, free_only=True)) is None:
        return None
    out, pj = p
    t = _task(pj, "machine")
    assert t is not None
    closing = rng.choice(r.windows)[1]
    if any(lo <= closing < hi for lo, hi in r.windows):
        return None
    length = t["end"] - t["start"]
    t["start"], t["end"] = closing, closing + length
    return out


def manual_off_shift(doc: Doc, rng: random.Random, r: Rules) -> Doc | None:
    """Slide a manual task so it runs one minute past its shift's end."""
    if (p := _pick(doc, rng)) is None:
        return None
    out, pj = p
    manual = [t for t in pj["tasks"] if t["kind"] in MANUAL]
    if not manual:
        return None
    t = rng.choice(manual)
    hi = next((h for lo, h in r.windows if lo <= t["start"] < h), None)
    if hi is None:
        return None
    length = t["end"] - t["start"]
    t["start"], t["end"] = hi - length + 1, hi + 1
    return out


def before_release(doc: Doc, rng: random.Random, r: Rules) -> Doc | None:
    if (p := _pick(doc, rng, free_only=True)) is None:
        return None
    out, pj = p
    t = _task(pj, "machine")
    assert t is not None
    _instance_job(out, pj["job_id"])["release"] = t["start"] + 1
    return out


def wrong_process(doc: Doc, rng: random.Random, r: Rules) -> Doc | None:
    if (p := _pick(doc, rng, free_only=True)) is None:
        return None
    out, pj = p
    process = _instance_job(out, pj["job_id"])["process"]
    others = [m["code"] for m in out["instance"]["machines"] if m["process"] != process]
    if not others:
        return None
    pj["machine"] = rng.choice(others)
    return out


def part_too_big(doc: Doc, rng: random.Random, r: Rules) -> Doc | None:
    if (p := _pick(doc, rng, free_only=True)) is None:
        return None
    out, pj = p
    biggest = max(max(m["build_mm"]) for m in out["instance"]["machines"])
    _instance_job(out, pj["job_id"])["part_mm"] = [biggest + 1, 1, 1]
    return out


def material_unsupported(doc: Doc, rng: random.Random, r: Rules) -> Doc | None:
    if (p := _pick(doc, rng, free_only=True)) is None:
        return None
    out, pj = p
    _instance_job(out, pj["job_id"])["material"] = "NOT-A-REAL-MATERIAL"
    return out


def overlap(doc: Doc, rng: random.Random, r: Rules) -> Doc | None:
    """Put one job's machine task at exactly the start of another's, on the same machine."""
    out = copy.deepcopy(doc)
    fixed = _fixed_ids(out)
    jobs = _jobs(out)
    movable = [pj for pj in jobs if pj["job_id"] not in fixed]
    if len(jobs) < 2 or not movable:
        return None
    b = rng.choice(movable)
    a = rng.choice([pj for pj in jobs if pj is not b])
    ta, tb = _task(a, "machine"), _task(b, "machine")
    assert ta is not None and tb is not None
    length = tb["end"] - tb["start"]
    b["machine"], tb["start"], tb["end"] = a["machine"], ta["start"], ta["start"] + length
    return out


def squeeze_changeover(doc: Doc, rng: random.Random, r: Rules) -> Doc | None:
    """Move a job one minute too close to a neighbour of a different material."""
    out = copy.deepcopy(doc)
    fixed = _fixed_ids(out)
    material = {j["id"]: j["material"] for j in out["instance"]["jobs"]}
    by_machine: dict[str, list[tuple[int, int, dict[str, Any]]]] = {}
    for pj in _jobs(out):
        t = _task(pj, "machine")
        assert t is not None
        by_machine.setdefault(pj["machine"], []).append((t["start"], t["end"], pj))
    pairs = []
    for runs in by_machine.values():
        runs.sort(key=lambda x: (x[0], x[1]))
        for (_, end, a), (_, _, b) in pairwise(runs):
            if material[a["job_id"]] != material[b["job_id"]] and b["job_id"] not in fixed:
                pairs.append((end, b))
    if not pairs or r.changeover == 0:
        return None
    end, b = rng.choice(pairs)
    t = _task(b, "machine")
    assert t is not None
    length = t["end"] - t["start"]
    t["start"] = end + r.changeover - 1
    t["end"] = t["start"] + length
    return out


def staff_overload(doc: Doc, rng: random.Random, r: Rules) -> Doc | None:
    """Make one more manual task than there are people start at the same minute."""
    out = copy.deepcopy(doc)
    tasks = [(pj["job_id"], t) for pj in _jobs(out) for t in pj["tasks"] if t["kind"] in MANUAL]
    by_job: dict[str, dict[str, Any]] = {}
    for job_id, t in tasks:
        by_job.setdefault(job_id, t)  # one task per job, so they are different people's work
    if len(by_job) < r.staff + 1:
        return None
    chosen = rng.sample(sorted(by_job), r.staff + 1)
    at = by_job[chosen[0]]["start"]
    for job_id in chosen:
        t = by_job[job_id]
        length = t["end"] - t["start"]
        t["start"], t["end"] = at, at + length
    return out


def move_fixed(doc: Doc, rng: random.Random, r: Rules) -> Doc | None:
    out = copy.deepcopy(doc)
    fixed = _fixed_ids(out)
    planned = [pj for pj in _jobs(out) if pj["job_id"] in fixed]
    if not planned:
        return None
    t = _task(rng.choice(planned), "machine")
    assert t is not None
    t["start"] += 1
    t["end"] += 1
    return out


def shrink_horizon(doc: Doc, rng: random.Random, r: Rules) -> Doc | None:
    out = copy.deepcopy(doc)
    fixed = _fixed_ids(out)
    ends = [
        t["end"]
        for pj in _jobs(out)
        for t in pj["tasks"]
        if not (t["kind"] == "machine" and pj["job_id"] in fixed)
    ]
    if not ends:
        return None
    out["instance"]["horizon"] = max(ends) - 1
    return out


OPERATORS: dict[str, tuple[str, Operator]] = {
    "shorten_machine": ("wrong_duration", shorten_machine),
    "lengthen_manual": ("wrong_duration", lengthen_manual),
    "drop_job": ("missing_job", drop_job),
    "duplicate_job": ("duplicate_job", duplicate_job),
    "also_unscheduled": ("duplicate_job", also_unscheduled),
    "unknown_job": ("unknown_job", unknown_job),
    "unknown_machine": ("unknown_machine", unknown_machine),
    "drop_task": ("wrong_tasks", drop_task),
    "reverse_tasks": ("wrong_tasks", reverse_tasks),
    "prep_after_machine": ("task_order", prep_after_machine),
    "machine_off_shift": ("machine_off_shift", machine_off_shift),
    "manual_off_shift": ("manual_off_shift", manual_off_shift),
    "before_release": ("before_release", before_release),
    "wrong_process": ("not_eligible", wrong_process),
    "part_too_big": ("not_eligible", part_too_big),
    "material_unsupported": ("not_eligible", material_unsupported),
    "overlap": ("machine_overlap", overlap),
    "squeeze_changeover": ("changeover", squeeze_changeover),
    "staff_overload": ("staff_overload", staff_overload),
    "move_fixed": ("fixed_moved", move_fixed),
    "shrink_horizon": ("past_horizon", shrink_horizon),
}


def mutants(doc: Doc, r: Rules, seed: int, per_operator: int) -> list[tuple[str, str, Doc]]:
    """(operator, expected code, mutant) for every operator that applies, `per_operator` each."""
    rng = random.Random(seed)
    out = []
    for name, (code, op) in OPERATORS.items():
        for _ in range(per_operator):
            m = op(doc, rng, r)
            if m is not None:
                out.append((name, code, m))
    return out
