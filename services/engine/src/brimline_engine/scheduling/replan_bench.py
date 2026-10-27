"""Scripted re-planning scenarios: lateness versus jobs moved (M6). Writes eval/results/REPLAN.md.

    uv run python -m brimline_engine.scheduling.replan_bench           # 3 seeds x 5 scenarios x 3 weights
    uv run python -m brimline_engine.scheduling.replan_bench --quick   # 1 seed, short limits

For each seeded 40-job instance: CP-SAT makes the approved plan from minute 0. At "now" (minute
240, Monday 12:00) every machine task that has started is fixed (running or done, at its planned
times). Then one disruption happens, the same rules the app uses are applied (a print running on a
machine that goes down is lost), and the rest is re-solved three times: with no re-planning costs
(a full re-solve), with the configured costs, and with four times those costs. Each re-plan is
validated by the independent checker; the run fails if any is invalid.

Jobs moved: jobs whose machine or machine start differ from the approved plan. Slip: minutes
jobs finish later than the approved plan said. Lateness: over scheduled jobs, against due dates.
"""

import argparse
import json
import sys
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean
from typing import Any

from brimline_engine.checker import check_document
from brimline_engine.scheduling.baselines import edd
from brimline_engine.scheduling.config import SchedulerConfig, scheduler_config
from brimline_engine.scheduling.cpsat import solve
from brimline_engine.scheduling.export import document
from brimline_engine.scheduling.generator import generate
from brimline_engine.scheduling.model import Downtime, Fixed, Instance, Previous, Schedule
from brimline_engine.settings import REPO_ROOT
from brimline_engine.shop_config import load_shop_config

RESULTS = REPO_ROOT / "eval" / "results"
NOW = 240  # Monday 12:00
SCENARIOS = ("machine_down", "material_delayed", "rush_job", "cancellation", "print_overrun")
WEIGHTS = (("none", 0), ("configured", 1), ("4x", 4))


def _machine_slot(s: Schedule, job_id: str) -> tuple[str, int, int] | None:
    plan = next((p for p in s.plans if p.job_id == job_id), None)
    slot = plan.slot("machine") if plan else None
    return None if plan is None or slot is None else (plan.machine, slot.start, slot.end)


def _state_at_now(inst: Instance, approved: Schedule) -> tuple[list[Fixed], list[Previous]]:
    fixed, previous = [], []
    for p in approved.plans:
        slot = p.slot("machine")
        assert slot is not None
        if slot.start < NOW:
            fixed.append(Fixed(p.job_id, p.machine, slot.start, slot.end))
        else:
            previous.append(Previous(p.job_id, p.machine, slot.start, p.completion))
    return fixed, previous


def _disrupt(
    scenario: str, inst: Instance, fixed: list[Fixed], cfg: SchedulerConfig
) -> tuple[Instance, list[Fixed], str]:
    """Apply one disruption the way the app does. Returns the instance, the fixed work, and
    a description."""
    jobs = list(inst.jobs)
    downtimes: list[Downtime] = []
    fixed_ids = {f.job_id for f in fixed}
    running = [f for f in fixed if f.end is not None and f.end > NOW]
    if scenario == "machine_down":
        # The machine with most planned work goes down for four hours from now.
        busiest = max(inst.machines, key=lambda m: sum(f.machine == m.code for f in fixed))
        down = Downtime(busiest.code, NOW, NOW + 240)
        downtimes.append(down)
        lost = [f for f in running if f.machine == busiest.code]
        if cfg.replan.running_print_lost_when_machine_down:
            fixed = [f for f in fixed if f not in lost]
        what = f"{busiest.code} down for 4 h; {len(lost)} running print(s) lost"
    elif scenario == "material_delayed":
        counts: dict[str, int] = {}
        for j in jobs:
            if j.id not in fixed_ids:
                counts[j.material] = counts.get(j.material, 0) + 1
        material = max(sorted(counts), key=lambda m: counts[m])
        jobs = [
            replace(j, release=NOW + 1440)
            if j.material == material and j.id not in fixed_ids
            else j
            for j in jobs
        ]
        what = f"{material} delayed by a day ({counts[material]} jobs)"
    elif scenario == "rush_job":
        candidates = [j for j in jobs if j.id not in fixed_ids and not j.rush]
        urgent = max(candidates, key=lambda j: (j.due, j.id))
        jobs = [replace(j, rush=True, due=NOW + 1440) if j.id == urgent.id else j for j in jobs]
        what = f"{urgent.id} becomes a rush job due tomorrow"
    elif scenario == "cancellation":
        not_started = sorted(j.id for j in jobs if j.id not in fixed_ids)
        gone = set(not_started[:2])
        jobs = [j for j in jobs if j.id not in gone]
        what = f"{', '.join(sorted(gone))} cancelled"
    else:  # print_overrun: the running print with the latest end needs 3 more hours
        late_print = max(running, key=lambda f: (f.end or 0, f.job_id))
        fixed = [replace(f, end=(f.end or 0) + 180) if f is late_print else f for f in fixed]
        what = f"the print of {late_print.job_id} on {late_print.machine} runs 3 h over"
    new = Instance(
        inst.name,
        inst.horizon,
        inst.machines,
        tuple(jobs),
        inst.shifts,
        inst.staff,
        tuple(fixed),
        plan_start=NOW,
        downtimes=tuple(downtimes),
    )
    return new, fixed, what


def _moved(new: Schedule, previous: list[Previous]) -> tuple[int, int]:
    moved = slip = 0
    for p in previous:
        now = _machine_slot(new, p.job_id)
        plan = next((x for x in new.plans if x.job_id == p.job_id), None)
        if now is None or plan is None:
            moved += 1
            continue
        if (now[0], now[1]) != (p.machine, p.start):
            moved += 1
        slip += max(0, plan.completion - p.completion)
    return moved, slip


def run(seeds: list[int], n_jobs: int, limit: float, cfg: SchedulerConfig) -> dict[str, Any]:
    shop = load_shop_config()
    rows = []
    for seed in seeds:
        base = generate(seed, n_jobs, shop, cfg)
        approved = solve(base, cfg, hint=edd(base, cfg.durations), deterministic_time=limit)
        fixed, previous = _state_at_now(base, approved)
        for scenario in SCENARIOS:
            inst, fixed_now, what = _disrupt(scenario, base, fixed, cfg)
            alive = {j.id for j in inst.jobs}
            fixed_ids = {f.job_id for f in fixed_now}
            prev = [p for p in previous if p.job_id in alive and p.job_id not in fixed_ids]
            for label, factor in WEIGHTS:
                weighted = cfg.model_copy(
                    update={
                        "replan": cfg.replan.model_copy(
                            update={
                                "moved_job": cfg.replan.moved_job * factor,
                                "slip_per_minute": cfg.replan.slip_per_minute * factor,
                            }
                        )
                    }
                )
                with_prev = replace(inst, previous=tuple(prev))
                s = solve(
                    with_prev,
                    weighted,
                    hint=edd(with_prev, cfg.durations),
                    deterministic_time=limit,
                )
                check = check_document(document(with_prev, s))
                moved, slip = _moved(s, prev)
                m = check.metrics
                rows.append(
                    {
                        "seed": seed,
                        "scenario": scenario,
                        "what": what,
                        "costs": label,
                        "valid": check.valid,
                        "violations": [v.code for v in check.violations],
                        "jobs_movable": len(prev),
                        "jobs_moved": moved,
                        "slip_minutes": slip,
                        "late_or_unscheduled": None if m is None else m.late_or_unscheduled,
                        "lateness_minutes": None if m is None else m.total_lateness_minutes,
                        "status": s.info.get("status"),
                    }
                )
                print(
                    f"seed {seed} {scenario} {label}: moved {moved}, valid {check.valid}",
                    flush=True,
                )
    return {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "n_jobs": n_jobs,
        "limit_seconds": limit,
        "now_minute": NOW,
        "replan_config": cfg.replan.model_dump(),
        "rows": rows,
    }


def write_md(data: dict[str, Any], path: Path) -> None:
    rows = data["rows"]
    lines = [
        "# Re-planning: lateness versus jobs moved",
        "",
        "> Generated by `make replan-bench`. Do not edit by hand.",
        "",
        f"Generated {data['generated_at']}. {data['n_jobs']}-job seeded instances; the approved plan is",
        f"CP-SAT from minute 0; at minute {data['now_minute']} (Monday 12:00) one disruption happens and the",
        f"rest is re-solved ({data['limit_seconds']:g} s deterministic limit) with no re-planning costs, the",
        f"configured costs ({data['replan_config']['moved_job']} per moved job,"
        f" {data['replan_config']['slip_per_minute']} per minute of slip), and four times those.",
        "Every re-plan was validated by the independent checker.",
        "",
        "## Means over the seeds",
        "",
        "| Scenario | Re-planning costs | Jobs moved | Slip (h) | Late or unscheduled | Lateness (h) | Checker |",
        "|---|---|---|---|---|---|---|",
    ]
    for scenario in SCENARIOS:
        for label, _ in WEIGHTS:
            sel = [r for r in rows if r["scenario"] == scenario and r["costs"] == label]
            if not sel:
                continue
            lines.append(
                f"| {scenario} | {label} | {mean(r['jobs_moved'] for r in sel):.1f}"
                f" of {mean(r['jobs_movable'] for r in sel):.0f}"
                f" | {mean(r['slip_minutes'] for r in sel) / 60:.1f}"
                f" | {mean(r['late_or_unscheduled'] for r in sel):.1f}"
                f" | {mean(r['lateness_minutes'] for r in sel) / 60:.1f}"
                f" | {sum(r['valid'] for r in sel)} of {len(sel)} valid |"
            )
    lines += [
        "",
        "## Each run",
        "",
        "| Seed | Scenario | What happened | Costs | Moved | Late or unscheduled | Lateness (h) | Valid |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        lines.append(
            f"| {r['seed']} | {r['scenario']} | {r['what']} | {r['costs']} | {r['jobs_moved']}"
            f" | {r['late_or_unscheduled']} | {r['lateness_minutes'] / 60:.1f} | {'yes' if r['valid'] else 'NO'} |"
        )
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8", newline="\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m brimline_engine.scheduling.replan_bench")
    parser.add_argument(
        "--quick", action="store_true", help="1 seed, 2 s limits, into eval/results/quick"
    )
    args = parser.parse_args(argv)
    cfg = scheduler_config()
    out = RESULTS / "quick" if args.quick else RESULTS
    data = run([1], 40, 2.0, cfg) if args.quick else run([1, 2, 3], 40, 5.0, cfg)
    out.mkdir(parents=True, exist_ok=True)
    (out / "replan.json").write_text(
        json.dumps(data, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    write_md(data, out / "REPLAN.md")
    print(f"Wrote {out / 'REPLAN.md'}")
    if not all(r["valid"] for r in data["rows"]):
        print("A re-plan failed the independent checker: see REPLAN.md", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
