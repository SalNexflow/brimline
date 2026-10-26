"""The bench re-scoring must actually notice disagreements (M4 review finding: it had no tests,
so a comparison that never fired would still have printed "0 disagreements")."""

import copy
import gzip
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from brimline_engine.checker import load_rules
from brimline_engine.checker.rescore import PLANS_FORMAT, ok, rescore
from brimline_engine.scheduling import bench
from brimline_engine.scheduling.baselines import edd, fcfs
from brimline_engine.scheduling.config import load_scheduler_config
from brimline_engine.scheduling.export import instance_doc, schedule_doc
from brimline_engine.scheduling.generator import generate
from brimline_engine.scheduling.metrics import evaluate
from brimline_engine.shop_config import load_shop_config

CFG = load_scheduler_config()
RULES = load_rules()


def honest_run() -> tuple[dict[str, Any], dict[str, Any]]:
    """A plans bundle and bench records for real plans, scored by the scheduler's code. The EDD
    plan is filed a second time under CP-SAT's name so BENCH.md has all three columns."""
    inst = generate(1, 20, load_shop_config(), CFG)
    records, runs = [], []
    plans = {"fcfs": fcfs(inst, CFG.durations), "edd": edd(inst, CFG.durations)}
    plans["cpsat-simple"] = plans["edd"]
    for method, schedule in plans.items():
        records.append(
            {
                "instance": inst.name,
                "jobs": len(inst.jobs),
                "method": method,
                "time_limit": 20.0,
                **asdict(evaluate(inst, schedule, CFG.weights)),
                "unscheduled_ids": list(schedule.unscheduled),
                "info": {"status": "test", "wall_seconds": 0.0},
            }
        )
        runs.append(
            {
                "section": "main",
                "instance": inst.name,
                "method": method,
                "time_limit": 20.0,
                "plan": schedule_doc(schedule),
            }
        )
    bundle = {"format": PLANS_FORMAT, "instances": {inst.name: instance_doc(inst)}, "runs": runs}
    return bundle, {"main": records, "sweep": []}


def test_an_honest_run_agrees() -> None:
    bundle, data = honest_run()
    summary = rescore(bundle, data, RULES, mutations_per_operator=1)
    assert ok(summary)
    assert (summary["plans_checked"], summary["plans_valid"]) == (3, 3)
    assert sum(m["applied"] for m in summary["mutations"].values()) > 0


def test_an_overstated_number_is_a_disagreement() -> None:
    bundle, data = honest_run()
    data["main"][1]["late_jobs"] -= 1 if data["main"][1]["late_jobs"] else -1
    data["main"][0]["objective"] -= 1
    summary = rescore(bundle, data, RULES, mutations_per_operator=0)
    assert not ok(summary)
    assert sorted(d["field"] for d in summary["metric_disagreements"]) == [
        "late_jobs",
        "objective",
    ]


def test_a_record_without_a_plan_or_a_plan_without_a_record_is_a_disagreement() -> None:
    bundle, data = honest_run()
    data["main"].pop()
    summary = rescore(bundle, data, RULES, mutations_per_operator=0)
    assert [d["field"] for d in summary["metric_disagreements"]] == ["record"]
    bundle, data = honest_run()
    bundle["runs"].pop()
    summary = rescore(bundle, data, RULES, mutations_per_operator=0)
    assert [d["field"] for d in summary["metric_disagreements"]] == ["plan"]


def test_a_broken_plan_is_reported() -> None:
    bundle, data = honest_run()
    task = bundle["runs"][0]["plan"]["jobs"][0]["tasks"][-1]
    task["end"] += 1
    summary = rescore(bundle, data, RULES, mutations_per_operator=0)
    assert not ok(summary)
    assert summary["plans_valid"] == 2
    assert {v["code"] for v in summary["violations"]} >= {"wrong_duration"}


def test_the_bench_exits_non_zero_when_the_checker_disagrees(tmp_path: Path) -> None:
    bundle, data = honest_run()
    data.update(
        generated_at="test",
        config_checked="test",
        solver=CFG.solver.model_dump(),
        weights=CFG.weights.model_dump(),
        sizes=[20],
        seeds=[1],
        main_time=20.0,
        sweep_size=20,
        sweep_times=[],
        variants=[],
    )
    with gzip.open(tmp_path / "bench_plans.json.gz", "wt", encoding="utf-8") as f:
        json.dump(bundle, f)
    good = copy.deepcopy(data)
    (tmp_path / "bench.json").write_text(json.dumps(good), encoding="utf-8")
    assert bench.main(["--recheck", "--out", str(tmp_path)]) == 0
    data["main"][0]["changeovers"] += 1
    (tmp_path / "bench.json").write_text(json.dumps(data), encoding="utf-8")
    assert bench.main(["--recheck", "--out", str(tmp_path)]) == 1
    assert "FINDING" in (tmp_path / "BENCH.md").read_text(encoding="utf-8")
