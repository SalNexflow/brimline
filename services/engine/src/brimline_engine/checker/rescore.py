"""Re-score the benchmark: check every saved plan and compare the checker's metrics with the
numbers the scheduler reported in bench.json. Any disagreement is a finding (M4).

    uv run python -m brimline_engine.checker.rescore      # eval/results/bench_plans.json.gz + bench.json

Reads only JSON files and config/scheduler.toml; imports nothing from the scheduler.
"""

import gzip
import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any

from brimline_engine.checker.check import check
from brimline_engine.checker.document import FORMAT, parse
from brimline_engine.checker.mutations import OPERATORS, mutants
from brimline_engine.checker.rules import CONFIG_PATH, Rules, load_rules

PLANS_FORMAT = "brimline-bench-plans/1"
RESULTS = CONFIG_PATH.parents[1] / "eval" / "results"
METRICS = (
    "scheduled",
    "unscheduled",
    "late_jobs",
    "late_or_unscheduled",
    "rush_late_jobs",
    "total_lateness_minutes",
    "changeovers",
    "utilisation",
    "finish_time",
    "objective",
)


def _key(section: str, r: dict[str, Any]) -> tuple[str, str, str, float]:
    return (section, r["instance"], r["method"], float(r["time_limit"]))


def rescore(
    bundle: dict[str, Any],
    bench: dict[str, Any],
    rules: Rules,
    mutations_per_operator: int = 2,
) -> dict[str, Any]:
    if bundle.get("format") != PLANS_FORMAT:
        raise ValueError(f"plans file: format must be {PLANS_FORMAT!r}")
    records = {_key(s, r): r for s in ("main", "sweep") for r in bench[s]}
    runs = bundle["runs"]
    disagreements: list[dict[str, Any]] = []
    violations: list[dict[str, Any]] = []
    warnings = 0
    caught = {name: [0, 0] for name in OPERATORS}  # operator -> [applied, caught]
    missed: list[dict[str, Any]] = []
    seen = set()
    for i, run in enumerate(runs):
        key = _key(run["section"], run)
        seen.add(key)
        doc = {
            "format": FORMAT,
            "instance": bundle["instances"][run["instance"]],
            "plan": run["plan"],
        }
        result = check(parse(doc), rules)
        where = {
            "section": run["section"],
            "instance": run["instance"],
            "method": run["method"],
            "time_limit": run["time_limit"],
        }
        violations += [{**where, **asdict(v)} for v in result.violations]
        warnings += len(result.warnings)
        record = records.get(key)
        if record is None:
            disagreements.append({**where, "field": "record", "scheduler": None, "checker": "plan"})
        elif result.metrics is not None:
            mine = asdict(result.metrics)
            for field in METRICS:
                a, b = record[field], mine[field]
                same = abs(a - b) < 1e-9 if field == "utilisation" else a == b
                if not same:
                    disagreements.append({**where, "field": field, "scheduler": a, "checker": b})
            if sorted(record["unscheduled_ids"]) != sorted(run["plan"]["unscheduled"]):
                disagreements.append(
                    {
                        **where,
                        "field": "unscheduled_ids",
                        "scheduler": record["unscheduled_ids"],
                        "checker": run["plan"]["unscheduled"],
                    }
                )
        if result.valid:  # mutating an invalid plan proves nothing
            for name, code, mutant in mutants(
                doc, rules, seed=i, per_operator=mutations_per_operator
            ):
                caught[name][0] += 1
                if code in check(parse(mutant), rules).codes():
                    caught[name][1] += 1
                else:
                    missed.append({**where, "operator": name, "expected": code})
    for key in records.keys() - seen:
        disagreements.append(
            {
                "section": key[0],
                "instance": key[1],
                "method": key[2],
                "time_limit": key[3],
                "field": "plan",
                "scheduler": "record",
                "checker": None,
            }
        )
    valid = len(runs) - len(
        {(v["section"], v["instance"], v["method"], v["time_limit"]) for v in violations}
    )
    return {
        "plans_checked": len(runs),
        "plans_valid": valid,
        "violations": violations,
        "warnings": warnings,
        "metric_disagreements": disagreements,
        "mutations": {
            name: {"code": OPERATORS[name][0], "applied": a, "caught": c}
            for name, (a, c) in caught.items()
        },
        "mutations_missed": missed,
    }


def ok(summary: dict[str, Any]) -> bool:
    return not (
        summary["violations"] or summary["metric_disagreements"] or summary["mutations_missed"]
    )


def read_bundle(path: Path) -> dict[str, Any]:
    with gzip.open(path, "rt", encoding="utf-8") as f:
        data: dict[str, Any] = json.load(f)
    return data


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    folder = Path(args[0]) if args else RESULTS
    bench = json.loads((folder / "bench.json").read_text(encoding="utf-8"))
    summary = rescore(read_bundle(folder / "bench_plans.json.gz"), bench, load_rules())
    print(json.dumps({k: v for k, v in summary.items() if k != "mutations"}, indent=2))
    return 0 if ok(summary) else 1


if __name__ == "__main__":
    sys.exit(main())
