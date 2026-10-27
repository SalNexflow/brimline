"""The exporter is the only bridge to the checker, so every raw field must reach the JSON
unchanged. The tests walk the dataclass fields, so a field added later fails here until it is
exported or listed below as derived on purpose."""

import json
from dataclasses import fields
from typing import Any

from brimline_engine.checker import parse
from brimline_engine.scheduling.baselines import edd
from brimline_engine.scheduling.config import load_scheduler_config
from brimline_engine.scheduling.export import FORMAT, document
from brimline_engine.scheduling.generator import generate
from brimline_engine.scheduling.model import (
    Downtime,
    Fixed,
    Instance,
    Job,
    JobPlan,
    Machine,
    Slot,
)
from brimline_engine.shop_config import load_shop_config

# `previous` (the approved plan, for re-planning costs) is not a validity input: not exported.
NOT_EXPORTED: set[str] = {"previous"}


def plain(value: object) -> Any:
    """What a field should look like after JSON: tuples become lists, sets sorted lists."""
    if isinstance(value, frozenset):
        return sorted(value)
    if isinstance(value, tuple):
        return [plain(v) for v in value]
    return value


def assert_same(obj: object, doc: dict[str, Any], renames: dict[str, str] | None = None) -> None:
    renames = renames or {}
    for f in fields(obj):  # type: ignore[arg-type]
        assert doc[renames.get(f.name, f.name)] == plain(getattr(obj, f.name)), f.name


def instance_with_everything() -> Instance:
    cfg = load_scheduler_config()
    inst = generate(3, 20, load_shop_config(), cfg)
    # Make sure the fields a generated instance may leave at a default are exercised too.
    first = inst.jobs[0]
    odd = Job(
        first.id,
        99,
        first.material,
        first.process,
        (1, 2, 3),
        7,
        11,
        5,
        -40,
        True,
        321,
        ("sanding",),
    )
    return Instance(
        inst.name,
        inst.horizon,
        inst.machines,
        (odd, *inst.jobs[1:]),
        inst.shifts,
        inst.staff,
        (Fixed(inst.jobs[1].id, inst.machines[0].code, 12, 400),),
        plan_start=5,
        downtimes=(Downtime(inst.machines[1].code, 2000, 2100),),
    )


def test_every_raw_field_reaches_the_json_unchanged() -> None:
    cfg = load_scheduler_config()
    inst = instance_with_everything()
    schedule = edd(inst, cfg.durations)
    doc = json.loads(json.dumps(document(inst, schedule)))

    assert doc["format"] == FORMAT
    d = doc["instance"]
    for f in fields(Instance):
        if f.name in NOT_EXPORTED:
            assert f.name not in d
        elif f.name not in {"machines", "jobs", "fixed", "downtimes"}:
            assert d[f.name] == plain(getattr(inst, f.name)), f.name
    assert len(d["machines"]) == len(inst.machines)
    for m, md in zip(inst.machines, d["machines"], strict=True):
        assert_same(m, md)
    assert len(d["jobs"]) == len(inst.jobs)
    for j, jd in zip(inst.jobs, d["jobs"], strict=True):
        assert_same(j, jd)
    assert len(d["fixed"]) == 1
    assert_same(inst.fixed[0], d["fixed"][0])
    assert len(d["downtimes"]) == 1
    assert_same(inst.downtimes[0], d["downtimes"][0])

    p = doc["plan"]
    assert p["method"] == schedule.method
    assert p["unscheduled"] == list(schedule.unscheduled)
    assert len(p["jobs"]) == len(schedule.plans) > 0
    for plan, pd in zip(schedule.plans, p["jobs"], strict=True):
        assert (pd["job_id"], pd["machine"]) == (plan.job_id, plan.machine)
        assert len(pd["tasks"]) == len(plan.slots)
        for slot, td in zip(plan.slots, pd["tasks"], strict=True):
            assert_same(slot, td)


def test_the_test_knows_every_field() -> None:
    # If a model class grows a field, the round-trip test above must be looked at again.
    assert [f.name for f in fields(Machine)] == ["code", "process", "materials", "build_mm"]
    assert [f.name for f in fields(Fixed)] == ["job_id", "machine", "start", "end"]
    assert [f.name for f in fields(JobPlan)] == ["job_id", "machine", "slots"]
    assert [f.name for f in fields(Slot)] == ["kind", "start", "end"]
    assert len(fields(Job)) == 12


def test_the_checker_reads_back_exactly_what_was_exported() -> None:
    # The other half of the bridge: the checker's parser must not drop or change a field.
    cfg = load_scheduler_config()
    inst = instance_with_everything()
    schedule = edd(inst, cfg.durations)
    parsed = parse(json.loads(json.dumps(document(inst, schedule))))
    for f in fields(Instance):
        if f.name not in NOT_EXPORTED | {"machines", "jobs", "fixed", "downtimes"}:
            assert getattr(parsed.instance, f.name) == getattr(inst, f.name), f.name
    for ours, theirs in [
        *zip(inst.machines, parsed.instance.machines, strict=True),
        *zip(inst.jobs, parsed.instance.jobs, strict=True),
        *zip(inst.fixed, parsed.instance.fixed, strict=True),
        *zip(inst.downtimes, parsed.instance.downtimes, strict=True),
    ]:
        for f in fields(ours):  # type: ignore[arg-type]
            assert getattr(theirs, f.name) == getattr(ours, f.name), f.name
    assert parsed.plan.method == schedule.method
    assert parsed.plan.unscheduled == schedule.unscheduled
    for plan, back in zip(schedule.plans, parsed.plan.jobs, strict=True):
        assert (back.job_id, back.machine) == (plan.job_id, plan.machine)
        assert [(t.kind, t.start, t.end) for t in back.tasks] == [
            (s.kind, s.start, s.end) for s in plan.slots
        ]
