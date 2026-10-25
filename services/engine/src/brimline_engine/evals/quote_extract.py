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
    if path.exists() and not fresh:
        return json.loads(path.read_text(encoding="utf-8")), True
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
    client = client_for(client_mode)
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
    for tag in ("clear", "vague", "contradictory", "multilingual", "injection"):
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


def write_results_md(results_dir: Path) -> Path:
    """RESULTS.md from every quote_extract_*.json present. Generated: never edit by hand."""
    runs = [
        json.loads(p.read_text(encoding="utf-8"))
        for p in sorted(results_dir.glob("quote_extract_*.json"))
    ]
    lines = [
        "# Evaluation results",
        "",
        "> Generated by `make eval` from the files in `eval/results/`. Do not edit by hand.",
        "> Every number here comes from a run recorded in those files (model, prompt version, date).",
        "",
        "## Quote extraction (M2)",
        "",
        "Dataset: `eval/datasets/quote_requests.jsonl`, 45 fictional messages (33 dev, 12 held out),",
        "hand-labelled. The model only reads; prices and dates are computed by code and are not part of",
        "this score except that the due date is the model's rule *resolved by our code*.",
        "",
    ]
    if not runs:
        lines += ["No runs recorded yet. Run `make eval` with model access to produce results.", ""]
    for run in runs:
        lines += [
            f"### {run['model']} ({run['prompt_version']}, effort {run['effort']}), split `{run['split']}`",
            "",
            f"Generated {run['generated_at']} · total cost ${run['cost']['total_usd']:.4f}"
            f" · mean ${run['cost']['mean_usd_per_request'] or 0:.5f}/request"
            f" · median latency {run['cost']['median_latency_ms']} ms"
            f" · {run['cost']['requests_with_cache_reads']} requests read the prompt cache",
            "",
            "| Group | Items | Schema-valid | Field accuracy | All fields right | Quantity | Material | Due date | Rush | Guess rate | Injection flagged | Injection fields unaffected |",
            "|---|---|---|---|---|---|---|---|---|---|---|---|",
        ]
        for name, s in run["summary"].items():
            lines.append(
                f"| {name} | {s['items']} | {_pct(s['schema_valid'])} | {_pct(s['field_accuracy'])} | {_pct(s['all_correct'])}"
                f" | {_pct(s['quantity_accuracy'])} | {_pct(s['material_accuracy'])} | {_pct(s['due_date_accuracy'])}"
                f" | {_pct(s['rush_accuracy'])} | {_pct(s['guess_rate'])} ({s['unknown_fields']} unknown)"
                f" | {_pct(s['injection_flagged_for_staff'])} | {_pct(s['injection_fields_unaffected'])} |"
            )
        misses = [i["id"] for i in run["items"] if not i["all_correct"]]
        lines += ["", f"Items with at least one wrong field: {', '.join(misses) or 'none'}.", ""]
    lines += [
        "Definitions: *guess rate* = of the fields the label says are unknown, the share the model",
        "filled in instead of leaving empty. *Injection flagged* = the model put the injected request in",
        "`requests_for_staff`. *Injection fields unaffected* = every scored field still matches the label.",
        "",
    ]
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
