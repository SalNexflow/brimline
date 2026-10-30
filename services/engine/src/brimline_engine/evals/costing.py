"""Eval of the under-quote flag (M10). Code only: no model is called.

For each true bias of TPU-BLACK (1.0 = no bias, the control; 1.10, 1.20, 1.40) and each number of
finished jobs per type (5, 10, 20, 40), 200 synthetic histories (brimline_engine.costing.scenario)
go through the report. Measured:

  - detection rate: share of runs that flag TPU-BLACK (for 1.0 and 1.10 it must stay at 0: a
    type 10 % over is under the 15 % threshold and must not be flagged);
  - false-alarm rate per run, across all job types together: share of runs that flag any type
    that has no bias (every type in the control).

Seeds 0-199 are dev (the rule may be looked at and tuned there only); the numbers reported come
from held-out seeds 10000-10199. Writes eval/results/costing.json; RESULTS.md shows the table.
"""

import json
import sys
from datetime import UTC, datetime

from brimline_engine.costing.config import costing_config
from brimline_engine.costing.report import build
from brimline_engine.costing.scenario import history
from brimline_engine.evals.quote_extract import write_results_md
from brimline_engine.settings import REPO_ROOT
from brimline_engine.shop_config import load_shop_config

RESULTS = REPO_ROOT / "eval" / "results"
BIASED = "TPU-BLACK"
BIASES = (1.0, 1.10, 1.20, 1.40)
SIZES = (5, 10, 20, 40)
RUNS = 200
SPLITS = {"dev": 0, "held_out": 10_000}
END = datetime(2026, 10, 1, tzinfo=UTC)  # fixed, so a run is reproducible


def grid(first_seed: int, runs: int = RUNS) -> list[dict[str, object]]:
    shop, cfg = load_shop_config(), costing_config()
    rows: list[dict[str, object]] = []
    for bias in BIASES:
        for n in SIZES:
            detected = false_alarm = 0
            for seed in range(first_seed, first_seed + runs):
                jobs = history(
                    shop,
                    cfg.scenario,
                    seed=seed,
                    jobs_per_type=n,
                    biased=BIASED if bias != 1.0 else None,
                    bias=bias,
                    end=END,
                )
                flagged = {t.material_code for t in build(jobs, cfg.flag).types if t.flagged}
                detected += BIASED in flagged
                unbiased = flagged if bias == 1.0 else flagged - {BIASED}
                false_alarm += bool(unbiased)
            rows.append(
                {
                    "bias": bias,
                    "jobs_per_type": n,
                    "runs": runs,
                    "detected": detected,
                    "false_alarm_runs": false_alarm,
                }
            )
    return rows


def seeded_scenarios() -> dict[str, list[str]]:
    """The acceptance scenarios: the demo's biased history and the same seed with no bias."""
    shop, cfg = load_shop_config(), costing_config()
    s = cfg.scenario
    out: dict[str, list[str]] = {}
    for name, biased in (("biased", s.demo_biased_material), ("control", None)):
        jobs = history(
            shop,
            s,
            seed=s.demo_seed,
            jobs_per_type=s.demo_jobs_per_material,
            biased=biased,
            bias=s.demo_bias,
            end=END,
        )
        out[name] = [t.material_code for t in build(jobs, cfg.flag).types if t.flagged]
    return out


def main() -> int:
    cfg = costing_config()
    result = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "rule": cfg.flag.model_dump(),
        "scenario": cfg.scenario.model_dump(),
        "biased_type": BIASED,
        "types": len({m for m in load_shop_config().price_rules.material_cents_per_gram}),
        "held_out": grid(SPLITS["held_out"]),
        "seeded": seeded_scenarios(),
        "tuned": False,  # the rule was not changed after looking at dev seeds (DECISIONS D141)
    }
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "costing.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    write_results_md(RESULTS)
    ok = check(result)
    print(markdown_section(result))
    return 0 if ok else 1


def check(result: dict) -> bool:  # type: ignore[type-arg]
    """The acceptance: 1.10 never flagged, control false alarms at most 5 % per run, the seeded
    scenario flags exactly the biased type and its control flags nothing."""
    problems = []
    for r in result["held_out"]:
        if r["bias"] in (1.0, 1.10) and r["detected"]:
            problems.append(
                f"bias {r['bias']} flagged in {r['detected']} runs at n={r['jobs_per_type']}"
            )
        if r["bias"] == 1.0 and r["false_alarm_runs"] / r["runs"] > 0.05:
            problems.append(f"control false alarms {r['false_alarm_runs']}/{r['runs']}")
    if result["seeded"]["biased"] != [BIASED] or result["seeded"]["control"]:
        problems.append(f"seeded scenarios flagged {result['seeded']}")
    for p in problems:
        print("✗", p, file=sys.stderr)
    return not problems


def _rate(k: int, n: int) -> str:
    """k/n as a whole percent, halves rounded up (as the README generator does)."""
    return f"{(200 * k + n) // (2 * n)} %"


def markdown_section(result: dict) -> str:  # type: ignore[type-arg]
    """The RESULTS.md section, from costing.json only."""
    rows = result["held_out"]
    rule = result["rule"]
    sizes = sorted({r["jobs_per_type"] for r in rows})
    biases = sorted({r["bias"] for r in rows})
    cell = {(r["bias"], r["jobs_per_type"]): r for r in rows}
    lines = [
        "## Quoted versus actual: the under-quote flag (M10)",
        "",
        f"Code only, no model. Rule (config/costing.toml): a material is flagged when at least "
        f"{rule['min_jobs']} quoted jobs finished and more of them cost over "
        f"{rule['threshold_ratio']}x their estimate than a one-sided sign test allows at "
        f"alpha {rule['alpha']}. Synthetic histories ({result['types']} materials, noise and "
        f"reprints as in config/costing.toml); {result['biased_type']} truly takes the bias "
        f"times its quote. {rows[0]['runs']} held-out runs per cell (seeds 10000+); the rule was "
        f"{'tuned on dev seeds' if result['tuned'] else 'not tuned'}. Generated {result['generated_at']}.",
        "",
        "### Detection rate (runs that flag the biased type)",
        "",
        "| True bias | " + " | ".join(f"{n} jobs/type" for n in sizes) + " |",
        "|---" * (len(sizes) + 1) + "|",
    ]
    for b in biases:
        label = f"{b:.2f}" + (" (control)" if b == 1.0 else "")
        lines.append(
            f"| {label} | "
            + " | ".join(_rate(cell[(b, n)]["detected"], cell[(b, n)]["runs"]) for n in sizes)
            + " |"
        )
    lines += [
        "",
        "### False alarms per run, all job types together",
        "",
        "| True bias | " + " | ".join(f"{n} jobs/type" for n in sizes) + " |",
        "|---" * (len(sizes) + 1) + "|",
    ]
    for b in biases:
        label = f"{b:.2f}" + (" (control: any type)" if b == 1.0 else " (unbiased types)")
        lines.append(
            f"| {label} | "
            + " | ".join(
                _rate(cell[(b, n)]["false_alarm_runs"], cell[(b, n)]["runs"]) for n in sizes
            )
            + " |"
        )
    seeded = result["seeded"]
    lines += [
        "",
        f"Seeded scenario (the demo's history): flagged {', '.join(seeded['biased']) or 'nothing'}; "
        f"its control (same seed, no bias): flagged {', '.join(seeded['control']) or 'nothing'}.",
        "",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    sys.exit(main())
