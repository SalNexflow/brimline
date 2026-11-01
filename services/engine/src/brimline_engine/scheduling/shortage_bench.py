"""Delivery slips and purchase suggestions (M9). Writes eval/results/shortage.json and SHORTAGE.md.

    uv run python -m brimline_engine.scheduling.shortage_bench           # 5 seeds x 4 slips
    uv run python -m brimline_engine.scheduling.shortage_bench --quick   # 1 seed, short limits

For each seeded 40-job instance (the benchmark's generator), material is limited: each material
has 60 % of its jobs' grams on hand and one delivery with the rest, on a working day 1 to 4
(generator.with_stock). That delivery then slips by 0, 1, 2 or 4 days. Each case is planned by
CP-SAT and by earliest-due-date, both under the stock rule, and each plan goes to the independent
checker (rule R20 included); the run fails if any plan is invalid.

Then the purchase suggestions are computed from the CP-SAT plan exactly as the Materials page
does (materials/shortage.py, config/purchasing.toml), as if ordered at the moment of planning
(Monday 08:00), and added as deliveries at their suggested arrival; CP-SAT plans again. That shows
what following the suggestions changes. Without any material limit is given for reference.
Lateness: late or unscheduled jobs, and total minutes late of scheduled jobs (from the checker).
"""

import argparse
import json
import random
import sys
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean
from typing import Any

from brimline_engine.checker import check_document, load_rules
from brimline_engine.checker.mutations import OPERATORS
from brimline_engine.materials.config import purchasing_config
from brimline_engine.materials.shortage import for_document
from brimline_engine.planning.clock import minute_at_or_after
from brimline_engine.scheduling.baselines import edd
from brimline_engine.scheduling.config import SchedulerConfig, scheduler_config
from brimline_engine.scheduling.cpsat import solve
from brimline_engine.scheduling.export import document
from brimline_engine.scheduling.generator import generate, with_stock
from brimline_engine.scheduling.model import Delivery, Instance, Schedule
from brimline_engine.settings import REPO_ROOT
from brimline_engine.shop_config import load_shop_config

RESULTS = REPO_ROOT / "eval" / "results"
SLIP_DAYS = (0, 1, 2, 4)
COVER = 0.6
TZ = "Europe/Berlin"
# Minute 0 of every instance: a Monday 08:00 in the shop, after the clock change (CET, UTC+1).
ANCHOR = datetime(2026, 11, 2, 7, 0, tzinfo=UTC)
STOCK_OPERATORS = ("stock_reduced", "delivery_removed", "delivery_one_minute_late")


def _measure(inst: Instance, s: Schedule) -> dict[str, Any]:
    result = check_document(document(inst, s), load_rules())
    assert result.metrics is not None or not result.valid
    m = result.metrics
    return {
        "valid": result.valid,
        "violations": sorted(result.codes()),
        "late_or_unscheduled": None if m is None else m.late_or_unscheduled,
        "unscheduled": None if m is None else m.unscheduled,
        "lateness_minutes": None if m is None else m.total_lateness_minutes,
    }


def _with_suggestions(inst: Instance, s: Schedule) -> tuple[Instance, list[dict[str, Any]]]:
    shortages = for_document(
        document(inst, s), ANCHOR, TZ, scheduler_config().durations, purchasing_config(), ANCHOR
    )
    orders = []
    extra = []
    for sh in shortages:
        if sh.suggestion is None:
            continue
        at = minute_at_or_after(sh.suggestion.arrives_at, ANCHOR, TZ)
        extra.append(Delivery(sh.material, at, sh.suggestion.grams))
        orders.append(
            {
                "material": sh.material,
                "grams": sh.suggestion.grams,
                "arrives_minute": at,
                "in_time": sh.suggestion.in_time,
                "affected_jobs": len(sh.affected),
            }
        )
    return replace(inst, deliveries=inst.deliveries + tuple(extra)), orders


def _mutations(inst: Instance, s: Schedule, seed: int) -> dict[str, list[int]]:
    """Each stock mutation once on this plan: [applied, caught]."""
    rules = load_rules()
    doc = document(inst, s)
    rng = random.Random(seed)
    out: dict[str, list[int]] = {}
    for name in STOCK_OPERATORS:
        code, op = OPERATORS[name]
        m = op(doc, rng, rules)
        applied = m is not None
        caught = applied and code in check_document(m, rules).codes()
        out[name] = [int(applied), int(caught)]
    return out


def run(seeds: list[int], n_jobs: int, limit: float, cfg: SchedulerConfig) -> dict[str, Any]:
    shop = load_shop_config()
    rows = []
    mutations: dict[str, list[int]] = {name: [0, 0] for name in STOCK_OPERATORS}
    for seed in seeds:
        base = generate(seed, n_jobs, shop, cfg)
        free = solve(base, cfg, hint=edd(base, cfg.durations), deterministic_time=limit)
        unlimited = _measure(base, free)
        for days in SLIP_DAYS:
            inst = with_stock(base, seed, COVER, slip=days * 1440)
            greedy = edd(inst, cfg.durations)
            best = solve(inst, cfg, hint=greedy, deterministic_time=limit)
            after_inst, orders = _with_suggestions(inst, best)
            after = solve(
                after_inst, cfg, hint=edd(after_inst, cfg.durations), deterministic_time=limit
            )
            for name, (a, c) in _mutations(inst, best, seed * 10 + days).items():
                mutations[name][0] += a
                mutations[name][1] += c
            row: dict[str, Any] = {
                "seed": seed,
                "slip_days": days,
                "unlimited": unlimited,
                "edd": _measure(inst, greedy),
                "cpsat": _measure(inst, best),
                "cpsat_with_suggestions": _measure(after_inst, after),
                "suggested_orders": orders,
            }
            rows.append(row)
            print(f"  seed {seed}, slip {days} d: {row['cpsat']['late_or_unscheduled']} late or"
                  f" unscheduled -> {row['cpsat_with_suggestions']['late_or_unscheduled']}"
                  f" with {len(orders)} suggested order(s)")  # fmt: skip
    return {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "seeds": seeds,
        "jobs": n_jobs,
        "cover": COVER,
        "solver_limit_seconds": limit,
        "rows": rows,
        "stock_mutations": mutations,
    }


def summary(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Means per slip, over seeds."""
    out = []
    for days in SLIP_DAYS:
        rows = [r for r in data["rows"] if r["slip_days"] == days]
        if not rows:
            continue

        def avg(key: str, field: str, rows: list[dict[str, Any]] = rows) -> float:
            return float(mean(r[key][field] for r in rows))

        out.append(
            {
                "slip_days": days,
                "unlimited_late": avg("unlimited", "late_or_unscheduled"),
                "edd_late": avg("edd", "late_or_unscheduled"),
                "cpsat_late": avg("cpsat", "late_or_unscheduled"),
                "after_late": avg("cpsat_with_suggestions", "late_or_unscheduled"),
                "cpsat_hours": avg("cpsat", "lateness_minutes") / 60,
                "after_hours": avg("cpsat_with_suggestions", "lateness_minutes") / 60,
                "orders": mean(len(r["suggested_orders"]) for r in rows),
                "orders_in_time": sum(o["in_time"] for r in rows for o in r["suggested_orders"]),
                "orders_total": sum(len(r["suggested_orders"]) for r in rows),
            }
        )
    return out


def write_md(data: dict[str, Any], path: Path) -> None:
    valid = sum(
        r[k]["valid"] for r in data["rows"] for k in ("edd", "cpsat", "cpsat_with_suggestions")
    )
    lines = [
        "# Delivery slips and purchase suggestions (M9)",
        "",
        f"Generated {data['generated_at']} by `make shortage-bench`. {len(data['seeds'])} seeded"
        f" {data['jobs']}-job instances; {round(data['cover'] * 100)} % of each material's grams"
        " on hand, one delivery with the rest; CP-SAT limit"
        f" {data['solver_limit_seconds']} s. Method: `scheduling/shortage_bench.py`.",
        "",
        "Means over seeds. Late = late or unscheduled jobs; hours = total lateness of scheduled jobs.",
        "",
        "| Delivery slip | No material limit (CP-SAT) | EDD | CP-SAT | CP-SAT + suggested orders"
        " | Hours late: CP-SAT / + orders | Orders suggested (in time) |",
        "|---|---|---|---|---|---|---|",
    ]
    for s in summary(data):
        lines.append(
            f"| {s['slip_days']} d | {s['unlimited_late']:.1f} | {s['edd_late']:.1f} |"
            f" {s['cpsat_late']:.1f} | {s['after_late']:.1f} |"
            f" {s['cpsat_hours']:.1f} / {s['after_hours']:.1f} |"
            f" {s['orders']:.1f} ({s['orders_in_time']} of {s['orders_total']}) |"
        )
    m = data["stock_mutations"]
    lines += [
        "",
        f"Every plan was checked by the independent checker, rule R20 included: {valid} of"
        f" {3 * len(data['rows'])} valid.",
        "",
        "Stock mutations on the CP-SAT plans (applied / caught): "
        + ", ".join(f"{k} {v[0]}/{v[1]}" for k, v in m.items())
        + ".",
        "",
        "Orders are suggested as if placed at the moment of planning; one that cannot arrive"
        ' before the first short need is "not in time" (the page then says order today).',
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8", newline="\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m brimline_engine.scheduling.shortage_bench")
    parser.add_argument(
        "--quick", action="store_true", help="1 seed, 2 s limits, into eval/results/quick"
    )
    args = parser.parse_args(argv)
    cfg = scheduler_config()
    out = RESULTS / "quick" if args.quick else RESULTS
    data = run([1], 40, 2.0, cfg) if args.quick else run([1, 2, 3, 4, 5], 40, 5.0, cfg)
    out.mkdir(parents=True, exist_ok=True)
    (out / "shortage.json").write_text(
        json.dumps(data, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    write_md(data, out / "SHORTAGE.md")
    print(f"Wrote {out / 'SHORTAGE.md'}")
    bad = [
        (r["seed"], r["slip_days"], k)
        for r in data["rows"]
        for k in ("edd", "cpsat", "cpsat_with_suggestions")
        if not r[k]["valid"]
    ]
    if bad:
        print(f"Plans failed the independent checker: {bad}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
