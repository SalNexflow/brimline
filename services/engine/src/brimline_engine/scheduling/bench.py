"""Scheduler benchmark: FCFS, EDD and CP-SAT on seeded instances. Writes eval/results/BENCH.md.

    uv run python -m brimline_engine.scheduling.bench                 # everything (slow: 25 CP-SAT runs)
    uv run python -m brimline_engine.scheduling.bench --quick         # small smoke run
    uv run python -m brimline_engine.scheduling.bench --recheck       # re-check saved plans only

Three parts:
  1. main:     sizes 20/40/80 x seeds 1-5; FCFS, EDD, CP-SAT (simple model, EDD hint)
  2. (removed) simple vs circuit: the circuit model lost at 80 jobs and was removed (D49);
     the comparison is in D49 and in bench.json at commit 45a15e6
  3. sweep:    CP-SAT simple at 5 s, 20 s and 60 s on the 80-job instances
Metrics come from scheduling/metrics.py (scheduler-side code). Every plan is then saved
(bench_plans.json.gz) and re-checked by the independent checker, which recomputes the metrics
from raw inputs; the run fails if it finds a broken rule or a number that disagrees.
"""

import argparse
import gzip
import json
import sys
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean
from typing import Any

from brimline_engine.checker import load_rules
from brimline_engine.checker.rescore import PLANS_FORMAT, ok, rescore
from brimline_engine.scheduling.baselines import edd, fcfs
from brimline_engine.scheduling.config import SchedulerConfig, scheduler_config
from brimline_engine.scheduling.cpsat import solve
from brimline_engine.scheduling.export import instance_doc, schedule_doc
from brimline_engine.scheduling.generator import generate
from brimline_engine.scheduling.metrics import evaluate
from brimline_engine.scheduling.model import Instance, Schedule
from brimline_engine.settings import REPO_ROOT
from brimline_engine.shop_config import load_shop_config

RESULTS = REPO_ROOT / "eval" / "results"


def _record(
    instance: Instance, schedule: Schedule, cfg: SchedulerConfig, **extra: object
) -> dict[str, Any]:
    metrics = evaluate(instance, schedule, cfg.weights)
    return {
        "instance": instance.name,
        "jobs": len(instance.jobs),
        "method": schedule.method,
        **asdict(metrics),
        "unscheduled_ids": list(schedule.unscheduled),
        "info": schedule.info,
        **extra,
    }


def run(
    sizes: list[int],
    seeds: list[int],
    main_time: float,
    sweep_times: list[float],
    sweep_size: int,
    cfg: SchedulerConfig,
) -> dict[str, Any]:
    shop = load_shop_config()
    main: list[dict[str, Any]] = []
    variants: list[dict[str, Any]] = []
    sweep: list[dict[str, Any]] = []
    instances: dict[str, Any] = {}
    plans: list[dict[str, Any]] = []

    def keep(section: str, inst: Instance, schedule: Schedule, limit: float) -> None:
        plans.append(
            {
                "section": section,
                "instance": inst.name,
                "method": schedule.method,
                "time_limit": limit,
                "plan": schedule_doc(schedule),
            }
        )

    for n in sizes:
        for seed in seeds:
            inst = generate(seed, n, shop, cfg)
            instances[inst.name] = instance_doc(inst)
            base_fcfs = fcfs(inst, cfg.durations)
            base_edd = edd(inst, cfg.durations)
            simple = solve(inst, cfg, hint=base_edd, deterministic_time=main_time)
            for schedule in (base_fcfs, base_edd, simple):
                main.append(_record(inst, schedule, cfg, time_limit=main_time))
                keep("main", inst, schedule, main_time)
            print(f"{inst.name}: done main", flush=True)
            if n == sweep_size:
                for limit in sweep_times:
                    schedule = (
                        simple
                        if limit == main_time
                        else solve(inst, cfg, hint=base_edd, deterministic_time=limit)
                    )
                    sweep.append(_record(inst, schedule, cfg, time_limit=limit))
                    keep("sweep", inst, schedule, limit)
                print(f"{inst.name}: done sweep", flush=True)
    return {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "config_checked": cfg.checked.isoformat(),
        "solver": cfg.solver.model_dump(),
        "weights": cfg.weights.model_dump(),
        "sizes": sizes,
        "seeds": seeds,
        "main_time": main_time,
        "sweep_size": sweep_size,
        "sweep_times": sweep_times,
        "main": main,
        "variants": variants,
        "sweep": sweep,
        "plans": {"format": PLANS_FORMAT, "instances": instances, "runs": plans},
    }


def _hours(minutes: float) -> str:
    return f"{minutes / 60:.1f}"


def _verdict(a: int, b: int) -> str:
    return "win" if a < b else "tie" if a == b else "LOSS"


def _status(info: dict[str, Any]) -> str:
    """The solver status, said honestly: the simple model's OPTIMAL is for its stand-in
    objective, and a run that found nothing says it fell back to the hint."""
    status = str(info.get("status", ""))
    if status == "OPTIMAL" and info.get("objective") == "stand-in changeovers":
        status = "OPTIMAL (stand-in)"
    if info.get("fallback"):
        status += f", fell back to {info['fallback']}"
    return status


def _checker_lines(c: dict[str, Any] | None) -> list[str]:
    if c is None:
        return []
    applied = sum(m["applied"] for m in c["mutations"].values())
    caught = sum(m["caught"] for m in c["mutations"].values())
    lines = [
        "## Independent checker",
        "",
        "`brimline_engine/checker` imports nothing from the scheduler (enforced by a test). It reads each saved",
        "plan (`bench_plans.json.gz`) with the raw instance and `config/scheduler.toml`, recomputes durations,",
        "shift windows and metrics itself, and checks every rule in `docs/SCHEDULE_RULES.md`.",
        "",
        f"- Plans checked: {c['plans_checked']} (FCFS, EDD and CP-SAT, including the time sweep);"
        f" valid: {c['plans_valid']}; rule violations: {len(c['violations'])}.",
        f"- Metric disagreements with the scheduler's numbers above: {len(c['metric_disagreements'])}.",
        f"- Unscheduled jobs flagged suspicious (a warning, not a violation): {c['warnings']}.",
        f"- Mutation test on these plans: {caught} of {applied} corrupted plans caught"
        f" ({sum(m['applied'] > 0 for m in c['mutations'].values())} kinds of corruption applied;"
        " a kind that needs fixed tasks or stock cannot apply here, because bench instances have"
        " neither; those are tested in `tests/test_checker_mutations.py`, and the stock kinds also"
        " in `make shortage-bench`).",
        "",
        "| Corruption | Expected rule | Applied | Caught |",
        "|---|---|---|---|",
    ]
    for name, m in c["mutations"].items():
        lines.append(f"| {name} | `{m['code']}` | {m['applied']} | {m['caught']} |")
    lines.append("")
    for row in c["metric_disagreements"] + c["violations"] + c["mutations_missed"]:
        lines.append(f"- FINDING: {row}")
    if c["metric_disagreements"] or c["violations"] or c["mutations_missed"]:
        lines.append("")
    return lines


def write_bench_md(data: dict[str, Any], path: Path) -> None:
    main = data["main"]
    methods = ["fcfs", "edd", "cpsat-simple"]
    lines = [
        "# Scheduler benchmark",
        "",
        "> Generated by `make bench` from `eval/results/bench.json`. Do not edit by hand.",
        "> These metrics come from the scheduler's own code (`scheduling/metrics.py`). Every plan is also",
        "> re-checked and re-scored by the independent checker (see *Independent checker* below).",
        "",
        f"Generated {data['generated_at']}. Config `config/scheduler.toml` (checked {data['config_checked']}).",
        f"CP-SAT: seed {data['solver']['random_seed']}, {data['solver']['workers']} worker, deterministic time limit "
        f"{data['main_time']:g} s (CP-SAT's machine-independent work measure, roughly seconds).",
        "**CP-SAT is hinted with the EDD schedule** (`AddHint`, with a value for every model variable), so it",
        "starts from the greedy answer. If it finds no solution within the limit it returns the EDD schedule and",
        "the status column says so. Instances are seeded (`scheduling/generator.py`) on the shop's six machines.",
        "",
        "Weights (objective, lower is better): "
        + ", ".join(f"{k} {v}" for k, v in data["weights"].items())
        + ". Lateness and the late flag of rush jobs count `rush_multiplier` times.",
        "",
        "## Averages per size",
        "",
        "Means over the seeds. Lateness and finish time in hours. *Late or unscheduled* counts jobs that did not",
        "fit at all as late, so dropping a job never improves a column; lateness is over scheduled jobs only.",
        "",
        "| Jobs | Method | Late jobs | Late or unscheduled | Total lateness (h) | Changeovers | Utilisation | Finish time (h) | Unscheduled | Objective | Solve (wall s) |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for n in data["sizes"]:
        for method in methods:
            rows = [r for r in main if r["jobs"] == n and r["method"] == method]
            if not rows:
                continue
            solve_s = mean(float(r["info"].get("wall_seconds", 0.0)) for r in rows)
            lines.append(
                f"| {n} | {method} | {mean(r['late_jobs'] for r in rows):.1f} | {mean(r['late_or_unscheduled'] for r in rows):.1f}"
                f" | {_hours(mean(r['total_lateness_minutes'] for r in rows))}"
                f" | {mean(r['changeovers'] for r in rows):.1f} | {mean(r['utilisation'] for r in rows):.1%}"
                f" | {_hours(mean(r['finish_time'] for r in rows))} | {mean(r['unscheduled'] for r in rows):.1f}"
                f" | {mean(r['objective'] for r in rows):,.0f} | {solve_s:.1f} |"
            )
    lines += [
        "",
        "## Per instance: weighted objective and CP-SAT verdict",
        "",
        "A *win* means a lower objective than the baseline on that instance; *LOSS* is shown in capitals.",
        "",
        "| Instance | FCFS | EDD | CP-SAT | vs FCFS | vs EDD | CP-SAT status | Late or unscheduled F/E/C | Changeovers F/E/C | Unscheduled F/E/C |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    wins = {"fcfs": [0, 0, 0], "edd": [0, 0, 0]}
    for name in dict.fromkeys(r["instance"] for r in main):
        by = {r["method"]: r for r in main if r["instance"] == name}
        f, e, c = by["fcfs"], by["edd"], by["cpsat-simple"]
        for key, other in (("fcfs", f), ("edd", e)):
            wins[key][
                ["win", "tie", "LOSS"].index(_verdict(c["objective"], other["objective"]))
            ] += 1
        lines.append(
            f"| {name} | {f['objective']:,} | {e['objective']:,} | {c['objective']:,} | {_verdict(c['objective'], f['objective'])}"
            f" | {_verdict(c['objective'], e['objective'])} | {_status(c['info'])}"
            f" | {f['late_or_unscheduled']}/{e['late_or_unscheduled']}/{c['late_or_unscheduled']}"
            f" | {f['changeovers']}/{e['changeovers']}/{c['changeovers']}"
            f" | {f['unscheduled']}/{e['unscheduled']}/{c['unscheduled']} |"
        )
    lines += [
        "",
        f"CP-SAT vs FCFS: {wins['fcfs'][0]} wins, {wins['fcfs'][1]} ties, {wins['fcfs'][2]} losses. "
        f"CP-SAT vs EDD: {wins['edd'][0]} wins, {wins['edd'][1]} ties, {wins['edd'][2]} losses.",
        "",
    ]
    if data["variants"]:
        lines += [
            f"## Changeover model: simple vs circuit ({data['sweep_size']} jobs, {data['main_time']:g} s each)",
            "",
            "Both scored by the same metrics code. *simple* separates different materials pairwise and counts",
            "distinct materials per machine; *circuit* sequences each machine with `AddCircuit` and counts",
            "changeovers exactly.",
            "",
            "| Instance | Model | Objective | Late jobs | Lateness (h) | Changeovers | Unscheduled | Status | Solve (wall s) |",
            "|---|---|---|---|---|---|---|---|---|",
        ]
        for r in data["variants"]:
            lines.append(
                f"| {r['instance']} | {r['info']['variant']} | {r['objective']:,} | {r['late_jobs']} | {_hours(r['total_lateness_minutes'])}"
                f" | {r['changeovers']} | {r['unscheduled']} | {_status(r['info'])} | {r['info']['wall_seconds']} |"
            )
        lines.append("")
    if data["sweep"]:
        lines += [
            f"## Time limit sweep (CP-SAT simple, {data['sweep_size']} jobs)",
            "",
            "*Optimal runs* are optimal for the simple model's stand-in objective, not proven optimal for the",
            "real changeover count.",
            "",
            "| Time limit (s) | Mean objective | Mean late jobs | Mean lateness (h) | Mean changeovers | Optimal runs (stand-in) | Mean solve (wall s) |",
            "|---|---|---|---|---|---|---|",
        ]
        for limit in data["sweep_times"]:
            rows = [r for r in data["sweep"] if r["time_limit"] == limit]
            lines.append(
                f"| {limit:g} | {mean(r['objective'] for r in rows):,.0f} | {mean(r['late_jobs'] for r in rows):.1f}"
                f" | {_hours(mean(r['total_lateness_minutes'] for r in rows))} | {mean(r['changeovers'] for r in rows):.1f}"
                f" | {sum(r['info']['status'] == 'OPTIMAL' for r in rows)} of {len(rows)}"
                f" | {mean(float(r['info']['wall_seconds']) for r in rows):.1f} |"
            )
        lines.append("")
    lines += _checker_lines(data.get("checker"))
    lines += [
        "## Limits",
        "",
        "- Synthetic instances; durations come from a simple formula, not a slicer.",
        "- One machine per job (a large job is never split across printers).",
        "- Wall-clock solve times depend on this computer; the deterministic limit keeps the schedules and",
        "  metrics repeatable (bench.json also holds timestamps and wall times, which differ between runs).",
        "- Utilisation = machine-task minutes, including cool-down on the machine, divided by all six machines",
        "  (including the lightly loaded CNC mill) times the finish time. It is comparable between methods, not",
        "  an absolute measure of how busy the shop is.",
        "- At 80 jobs CP-SAT stops at FEASIBLE, far from proven optimal, and the result depends on the",
        "  order the model is built in: before DEFECT_LOG #30 was fixed, the same instance gave visibly",
        "  different objectives. Treat a single 80-job number as one sample, and the win/loss count as",
        "  the robust result.",
        "- The checker proves a plan obeys the rules and recomputes its numbers; it does not prove a plan is",
        "  optimal, or that an unscheduled job could not have fitted (it only flags suspicious ones).",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8", newline="\n")


def _finish(data: dict[str, Any], bundle: dict[str, Any], out: Path) -> int:
    """Check every plan, write bench.json and BENCH.md, and fail if the checker disagrees."""
    data["checker"] = rescore(bundle, data, load_rules())
    (out / "bench.json").write_text(
        json.dumps(data, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    write_bench_md(data, out / "BENCH.md")
    print(f"Wrote {out / 'BENCH.md'}")
    if not ok(data["checker"]):
        print("The independent checker disagrees with this run: see BENCH.md", file=sys.stderr)
        return 1
    return 0


def _recheck(out: Path) -> int:
    """No solving: re-run the checker on the saved plans (for example after a checker change)."""
    data = json.loads((out / "bench.json").read_text(encoding="utf-8"))
    with gzip.open(out / "bench_plans.json.gz", "rt", encoding="utf-8") as f:
        bundle = json.load(f)
    return _finish(data, bundle, out)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m brimline_engine.scheduling.bench")
    parser.add_argument(
        "--quick", action="store_true", help="20 jobs, 2 seeds, 2 s limits (smoke run)"
    )
    parser.add_argument(
        "--recheck", action="store_true", help="re-check the saved plans only, no solving"
    )
    # A smoke run must never overwrite the real results, so --quick writes to its own folder.
    parser.add_argument("--out", type=Path, default=None, help="default eval/results")
    args = parser.parse_args(argv)
    if args.out is None:
        args.out = RESULTS / "quick" if args.quick else RESULTS
    if args.recheck:
        return _recheck(args.out)
    cfg = scheduler_config()
    main_time = cfg.solver.deterministic_time_seconds
    if args.quick:
        data = run([20], [1, 2], 2.0, [1.0, 2.0], 20, cfg)
    else:
        data = run([20, 40, 80], [1, 2, 3, 4, 5], main_time, [5.0, main_time, 60.0], 80, cfg)
    args.out.mkdir(parents=True, exist_ok=True)
    bundle = data.pop("plans")
    # mtime=0 keeps the file byte-identical between identical runs
    with gzip.GzipFile(args.out / "bench_plans.json.gz", "wb", mtime=0) as f:
        f.write(json.dumps(bundle, separators=(",", ":")).encode("utf-8"))
    return _finish(data, bundle, args.out)


if __name__ == "__main__":
    sys.exit(main())
