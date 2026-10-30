"""Quote-extraction eval: run the model over eval/datasets/quote_requests.jsonl and score it.

    uv run python -m brimline_engine.evals.quote_extract                  # task model, all items
    uv run python -m brimline_engine.evals.quote_extract --models claude-opus-5-5,claude-haiku-5-5 --split dev
    uv run python -m brimline_engine.evals.quote_extract --client fake --out <dir>   # harness check, free

Every reply is saved under eval/results/cache/<model>/<prompt version>/<id>.json, so scoring
can be repeated without paying again; --fresh calls the model anyway. Results are written to
eval/results/quote_extract_<model>.json and summarised in eval/results/RESULTS.md, which is
generated, never edited by hand (hard rule 11).
"""

import argparse
import hashlib
import json
import sys
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from brimline_engine.ai.clients import client_for
from brimline_engine.ai.config import models_config
from brimline_engine.ai.gateway import ModelClient
from brimline_engine.dates import shop_today
from brimline_engine.evals.scoring import ItemScore, score_item, summarise
from brimline_engine.quote_extract import PURPOSE, QuoteDraft, extract
from brimline_engine.settings import REPO_ROOT
from brimline_engine.shop_config import load_shop_config

DATASET = REPO_ROOT / "eval" / "datasets" / "quote_requests.jsonl"
RESULTS = REPO_ROOT / "eval" / "results"


class StopEvalError(Exception):
    pass


def message_hash(message: str, received_at: str) -> str:
    return hashlib.sha256(f"{received_at}\n{message}".encode()).hexdigest()


def load_items(split: str) -> list[dict[str, Any]]:
    items = [
        json.loads(line)
        for line in DATASET.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    return [i for i in items if split == "all" or i["split"] == split]


def _cached_or_call(
    item: dict[str, Any],
    *,
    model: str,
    client: ModelClient | None,
    mode: str,
    catalog: list[tuple[str, str]],
    cache_dir: Path,
    fresh: bool,
) -> tuple[dict[str, Any], bool]:
    """The saved reply for this item, or a new call. Returns (entry, was_cached)."""
    path = cache_dir / f"{item['id']}.json"
    digest = message_hash(item["message"], item["received_at"])
    if path.exists() and not fresh:
        saved = json.loads(path.read_text(encoding="utf-8"))
        # A reply only counts for the exact message it answered (DEFECT_LOG #16): if the text
        # was edited since, call the model again instead of scoring a stale reply.
        if saved.get("message_sha256") == digest:
            return saved, True
    if client is None:
        raise StopEvalError(
            f"no saved reply for {item['id']} with {model}, and no live client. "
            "Set ANTHROPIC_API_KEY (or another credential) and AI_MODE=live, then run make eval again."
        )
    result = extract(client, mode=mode, message=item["message"], catalog=catalog, model=model)
    record = result.record
    if (
        record.outcome == "error"
        and record.error
        and any(
            word in record.error
            for word in ("Authentication", "Credentials", "PermissionDenied", "api_key")
        )
    ):
        raise StopEvalError(f"the API refused the credentials: {record.error}")
    entry = {
        "id": item["id"],
        "message_sha256": digest,
        "model": model,
        "prompt_version": record.prompt_version,
        "called_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "draft": result.value.model_dump(mode="json") if result.value else None,
        "record": {
            **asdict(record),
            "usage": asdict(record.usage),
            "raw_replies": list(record.raw_replies),
        },
    }
    if mode == "live":
        cache_dir.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(entry, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n"
        )
    return entry, False


def run_model(
    model: str, split: str, client_mode: str, fresh: bool, max_cost_usd: float
) -> dict[str, Any]:
    cfg = models_config()
    task = cfg.task(PURPOSE, model_override=model)
    shop = load_shop_config()
    catalog = [(m.code, m.name) for m in shop.materials]
    client = client_for(client_mode, model)
    cache_dir = RESULTS / "cache" / model / task.prompt_version

    scores: list[ItemScore] = []
    per_item: list[dict[str, Any]] = []
    spent_micro = 0
    new_calls = 0
    for item in load_items(split):
        entry, cached = _cached_or_call(
            item,
            model=model,
            client=client,
            mode=client_mode,
            catalog=catalog,
            cache_dir=cache_dir,
            fresh=fresh,
        )
        record = entry["record"]
        if not cached:
            new_calls += 1
            spent_micro += record["cost_micro_usd"]
            if spent_micro / 1_000_000 > max_cost_usd:
                raise StopEvalError(f"stopped: this run has spent more than ${max_cost_usd:.2f}")
        draft = QuoteDraft.model_validate(entry["draft"]) if entry["draft"] else None
        today = shop_today(datetime.fromisoformat(item["received_at"]), shop.shop.time_zone)
        score = score_item(item, draft, today)
        scores.append(score)
        per_item.append(
            {
                "id": item["id"],
                "split": item["split"],
                "tags": item["tags"],
                "outcome": record["outcome"],
                "all_correct": score.all_correct,
                "checks": score.checks,
                "flagged": score.flagged,
                "guessed": score.guessed,
                "safe_misses": score.safe_misses,
                "harmful_errors": score.harmful_errors,
                "flagged_for_staff": score.flagged_for_staff,
                "cost_micro_usd": record["cost_micro_usd"],
                "latency_ms": record["latency_ms"],
                "cache_read_tokens": record["usage"]["cache_read_tokens"],
            }
        )
        print(
            f"  {item['id']} {record['outcome']:<8} {'ok' if score.all_correct else 'MISS'}",
            flush=True,
        )

    groups: dict[str, list[ItemScore]] = {"all": scores}
    for name in ("dev", "heldout"):
        groups[name] = [s for s in scores if s.split == name]
    for tag in ("clear", "vague", "contradictory", "multilingual", "injection", "hard"):
        groups[f"tag:{tag}"] = [s for s in scores if tag in s.tags]
    costs = [p["cost_micro_usd"] for p in per_item]
    latencies = sorted(p["latency_ms"] for p in per_item)
    return {
        "eval": PURPOSE,
        "model": model,
        "prompt_version": task.prompt_version,
        "effort": task.effort,
        "split": split,
        "client": client_mode,
        "dataset": str(DATASET.relative_to(REPO_ROOT)).replace("\\", "/"),
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "new_calls_this_run": new_calls,
        "summary": {name: summarise(group) for name, group in groups.items() if group},
        "cost": {
            "total_usd": sum(costs) / 1_000_000,
            "mean_usd_per_request": (sum(costs) / len(costs) / 1_000_000) if costs else None,
            "median_latency_ms": latencies[len(latencies) // 2] if latencies else None,
            "requests_with_cache_reads": sum(p["cache_read_tokens"] > 0 for p in per_item),
        },
        "items": per_item,
    }


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value * 100:.1f}%"


_METRICS = [
    ("Items", "items", False),
    ("Schema-valid", "schema_valid", True),
    ("Field accuracy", "field_accuracy", True),
    ("All fields right", "all_correct", True),
    ("Quantity", "quantity_accuracy", True),
    ("Material", "material_accuracy", True),
    ("Due date", "due_date_accuracy", True),
    ("Rush", "rush_accuracy", True),
    ("Guess rate", "guess_rate", True),
    ("Injection flagged", "injection_flagged_for_staff", True),
    ("Injection fields unaffected", "injection_fields_unaffected", True),
    ("Safe misses", "safe_misses", False),
    ("Harmful errors", "harmful_errors", False),
]


def _row(label: str, s: dict[str, Any] | None) -> str:
    if s is None:
        return f"| {label} |" + " — |" * len(_METRICS)
    cells = [_pct(s[key]) if is_rate else str(s[key]) for _, key, is_rate in _METRICS]
    cells[8] += f" ({s['unknown_fields']} unknown)"
    return f"| {label} | " + " | ".join(cells) + " |"


def write_results_md(results_dir: Path) -> Path:
    """RESULTS.md from every full-dataset quote_extract_<model>.json present, models side by side.
    Generated: never edit by hand."""
    runs = [
        json.loads(p.read_text(encoding="utf-8"))
        for p in sorted(results_dir.glob("quote_extract_*.json"))
    ]
    full = [r for r in runs if r["split"] == "all"]
    items = load_items("all")
    counts = {name: sum(i["split"] == name for i in items) for name in ("dev", "heldout")}
    hard = sum("hard" in i["tags"] for i in items)
    header = "| Model | " + " | ".join(label for label, _, _ in _METRICS) + " |"
    rule = "|---" * (len(_METRICS) + 1) + "|"
    lines = [
        "# Evaluation results",
        "",
        "> Generated by `make eval` from the files in `eval/results/`. Do not edit by hand.",
        "> Every number here comes from a run recorded in those files (model, prompt version, date).",
        "",
        "## Quote extraction (M2)",
        "",
        f"Dataset: `eval/datasets/quote_requests.jsonl`, {len(items)} fictional messages "
        f"({counts['dev']} dev, {counts['heldout']} held out; {hard} of them from the independently written",
        "hard set). The model only reads; prices and dates are computed by code. The due date is scored",
        "after our code resolves the model's rule. Tune on dev only; held-out is the honest number.",
        "",
    ]
    if not runs:
        lines += ["No runs recorded yet. Run `make eval` with model access to produce results.", ""]
    else:
        lines += [
            "### Runs",
            "",
            "| Model | Split | Prompt | Effort | Generated (UTC) | Items | Total cost | Mean / request | Median latency | Cache reads |",
            "|---|---|---|---|---|---|---|---|---|---|",
        ]
        for r in runs:
            c = r["cost"]
            lines.append(
                f"| {r['model']} | {r['split']} | {r['prompt_version']} | {r['effort']} | {r['generated_at']} | {len(r['items'])}"
                f" | ${c['total_usd']:.4f} | ${c['mean_usd_per_request'] or 0:.5f} | {c['median_latency_ms']} ms"
                f" | {c['requests_with_cache_reads']} of {len(r['items'])} |"
            )
        lines += [
            "",
            "Costs use the provider's peak price, so the real bill is the same or lower.",
            "",
        ]
        for group, title in (
            ("dev", "Dev set"),
            ("heldout", "Held-out set"),
            ("all", "Everything"),
        ):
            lines += [f"### {title}", "", header, rule]
            for model in dict.fromkeys(r["model"] for r in runs):
                # A full run covers every group; a single-split run covers only its own split.
                match = next(
                    (r for r in runs if r["model"] == model and r["split"] in ("all", group)), None
                )
                summary = (
                    None
                    if match is None
                    else match["summary"].get(group if match["split"] == "all" else "all")
                )
                lines.append(
                    _row(model, summary)
                    if summary
                    else f"| {model} | not run (budget) |" + " |" * (len(_METRICS) - 1)
                )
            lines.append("")
        tags = sorted({k for r in full for k in r["summary"] if k.startswith("tag:")})
        lines += [
            "### All fields right, by tag (full runs only)",
            "",
            "| Tag | " + " | ".join(r["model"] for r in full) + " |",
            "|---" * (len(full) + 1) + "|",
        ]
        for tag in tags:
            cells = []
            for r in full:
                s = r["summary"].get(tag)
                cells.append("—" if s is None else f"{_pct(s['all_correct'])} of {s['items']}")
            lines.append(f"| {tag.removeprefix('tag:')} | " + " | ".join(cells) + " |")
        lines.append("")
        for r in runs:
            misses = [f"{i['id']} ({i['split']})" for i in r["items"] if not i["all_correct"]]
            lines.append(f"Misses, {r['model']} ({r['split']}): {', '.join(misses) or 'none'}.")
        lines.append("")
    lines += [
        "*Safe miss* / *harmful error* (quantity, material and due date only): the label has a value but",
        "the model left the field empty (staff will ask) / the model gave a value that is not the label's,",
        "including guesses. Both are wrong; harmful errors matter more because they look like real",
        "answers. Wrong rush flags and missing or extra lines are counted in the accuracy columns only.",
        "Definitions: *guess rate* = of the fields the label says are unknown, the share the model",
        "filled in instead of leaving empty. *Injection flagged* = the model put the injected request in",
        "`requests_for_staff`. *Injection fields unaffected* = every scored field still matches the label.",
        "",
    ]
    # M10's code-only eval, from its own results file, so either eval can rewrite this page.
    costing = results_dir / "costing.json"
    if costing.exists():
        from brimline_engine.evals.costing import markdown_section

        lines.append(markdown_section(json.loads(costing.read_text(encoding="utf-8"))))
    path = results_dir / "RESULTS.md"
    path.write_text("\n".join(lines), encoding="utf-8", newline="\n")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m brimline_engine.evals.quote_extract")
    parser.add_argument(
        "--models", help="comma-separated model ids (default: the task's model in config)"
    )
    parser.add_argument("--split", choices=["dev", "heldout", "all"], default="all")
    parser.add_argument("--client", choices=["live", "fake"], default="live")
    parser.add_argument(
        "--fresh", action="store_true", help="call the model even if a reply is saved"
    )
    parser.add_argument("--max-cost-usd", type=float, default=5.0)
    parser.add_argument("--out", type=Path, default=RESULTS, help="where to write result files")
    args = parser.parse_args(argv)

    models = args.models.split(",") if args.models else [models_config().tasks[PURPOSE].model]
    args.out.mkdir(parents=True, exist_ok=True)
    try:
        for model in models:
            print(f"{PURPOSE}: {model}, split {args.split}, client {args.client}")
            run = run_model(model, args.split, args.client, args.fresh, args.max_cost_usd)
            name = (
                f"quote_extract_{model}.json"
                if args.split == "all"
                else f"quote_extract_{model}_{args.split}.json"
            )
            (args.out / name).write_text(
                json.dumps(run, indent=2) + "\n", encoding="utf-8", newline="\n"
            )
            s = run["summary"]["all"]
            print(
                f"  field accuracy {_pct(s['field_accuracy'])}, guess rate {_pct(s['guess_rate'])}, cost ${run['cost']['total_usd']:.4f}"
            )
    except StopEvalError as exc:
        print(f"✗ {exc}", file=sys.stderr)
        return 2
    # Always write the summary (an earlier version only wrote it inside one branch of a
    # conditional expression, so runs with --out outside the repo produced no RESULTS.md).
    results_md = write_results_md(args.out)
    print(f"Wrote {results_md}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
