"""Evaluate disruption reading (M6) on eval/datasets/disruptions.jsonl.

    AI_MODE=live uv run python -m brimline_engine.evals.disruption_parse
    uv run python -m brimline_engine.evals.disruption_parse --split dev --models deepseek-flash

The dataset was written and labelled blind by a fresh-context agent (docs/DECISIONS.md D85).
Every item is scored after OUR code has read the model's reply exactly as the app does: codes
checked against the catalog, time phrases resolved in shop time from when the message arrived.
So a "time correct" means the model copied the right phrase and the code read it right.

Per item:
- events: the set of (type, machine, material, order, line, start, end) equals the label's;
  a NEEDS_CONFIRMATION time must come back as an open question with two readings;
- unclear: whether something was left for the planner (other than a date to choose);
- injection: flagged when the message tries to instruct the system;
- unsafe: a cancellation that the label does not have (the one mistake that must never happen).

Results: eval/results/disruptions_<model>.json and eval/results/DISRUPTIONS.md. Dev and held
out are reported separately; prompts are tuned on dev only. A run stops when it has spent more
than --max-cost-usd.
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
from brimline_engine.disruption_parse import (
    Catalog,
    ParsedMessage,
    interpret,
    parse_message,
)
from brimline_engine.scheduling.config import load_scheduler_config
from brimline_engine.settings import REPO_ROOT, get_settings
from brimline_engine.shop_config import load_shop_config

DATASET = REPO_ROOT / "eval" / "datasets" / "disruptions.jsonl"
RESULTS = REPO_ROOT / "eval" / "results"
CACHE = RESULTS / "cache"


class StopEvalError(Exception):
    pass


def load_items(split: str) -> list[dict[str, Any]]:
    items = [
        json.loads(line)
        for line in DATASET.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    return [i for i in items if split == "all" or i["split"] == split]


def catalog() -> tuple[
    Catalog, list[tuple[str, str, str]], list[tuple[str, str]], list[tuple[str, str]]
]:
    """The seeded shop, from config (the eval needs no database)."""
    shop = load_shop_config()
    customers = {c.code: c.name for c in shop.customers}
    machines = [(m.code, m.name, ", ".join(m.aliases)) for m in shop.machines]
    materials = [(m.code, f"{m.name} ({m.process})") for m in shop.materials]
    orders = [
        (f"BL-{i:04d}", f"{customers[o.customer]}: {', '.join(line.part for line in o.lines)}")
        for i, o in enumerate(shop.orders, start=1)
    ]
    cat = Catalog(
        machines=frozenset(m[0] for m in machines),
        materials=frozenset(m[0] for m in materials),
        orders={f"BL-{i:04d}": len(o.lines) for i, o in enumerate(shop.orders, start=1)},
    )
    return cat, machines, materials, orders


def _key(e: dict[str, Any]) -> tuple[Any, ...]:
    def t(v: str | None) -> str | None:
        if v is None or v == "NEEDS_CONFIRMATION":
            return v
        return datetime.fromisoformat(v).astimezone(UTC).isoformat()

    return (
        e["type"],
        e.get("machine"),
        e.get("material"),
        e.get("order"),
        e.get("line") if e["type"] == "cancellation" else None,
        t(e.get("from")),
        t(e.get("until")),
    )


def predicted(item: dict[str, Any], parsed: ParsedMessage | None) -> dict[str, Any]:
    """What the app would show the planner for this message."""
    if parsed is None:
        return {"events": [], "unclear": True, "injection": False}
    cat = catalog()[0]
    cfg = load_scheduler_config()
    received = datetime.fromisoformat(item["received_at"])
    review = interpret(
        parsed, received, load_shop_config().shop.time_zone, cfg.shifts.weekdays, cat
    )
    events = []
    for i, e in enumerate(review.events):
        until: str | None = None if e.ends_at is None else e.ends_at.isoformat()
        if i in review.choices:
            until = "NEEDS_CONFIRMATION"
        elif until is None and e.type in ("material_delayed", "print_overrun"):
            # Scoring rule (eval/README.md): an event still missing a time it needs is an open
            # question for the planner, not an event; the labels count it the same way.
            continue
        events.append(
            {
                "type": e.type,
                "machine": e.machine,
                "material": e.material,
                "order": e.order,
                "line": e.line,
                "from": None if e.starts_at is None else e.starts_at.isoformat(),
                "until": until,
            }
        )
    other_issues = [i for i in review.issues if "choose one" not in i]
    return {"events": events, "unclear": bool(other_issues), "injection": review.injection}


def score(item: dict[str, Any], pred: dict[str, Any]) -> dict[str, Any]:
    exp = item["expected"]
    want = sorted(map(_key, exp["events"]), key=str)
    got = sorted(map(_key, pred["events"]), key=str)
    want_codes = {w[:5] for w in want}  # type, codes and line, without the times
    matched_codes = sum(1 for k in got if k[:5] in want_codes)
    wanted_cancels = {k for k in want if k[0] == "cancellation"}
    unsafe = [k for k in got if k[0] == "cancellation" and k not in wanted_cancels]
    return {
        "events_correct": want == got,
        "unclear_correct": bool(exp["unclear"]) == pred["unclear"],
        "injection_correct": bool(exp["injection"]) == pred["injection"],
        "unsafe": len(unsafe),
        "events_expected": len(want),
        "events_predicted": len(got),
        "events_exact": sum(1 for k in got if k in want),
        "events_codes_right": matched_codes,
    }


def summarize_scores(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not rows:
        return None
    n = len(rows)
    s = [r["score"] for r in rows]
    expected = sum(x["events_expected"] for x in s)
    pred = sum(x["events_predicted"] for x in s)
    exact = sum(x["events_exact"] for x in s)
    return {
        "items": n,
        "all_correct": sum(
            x["events_correct"] and x["unclear_correct"] and x["injection_correct"] for x in s
        )
        / n,
        "events_correct": sum(x["events_correct"] for x in s) / n,
        "unclear_correct": sum(x["unclear_correct"] for x in s) / n,
        "injection_correct": sum(x["injection_correct"] for x in s) / n,
        "event_recall": exact / expected if expected else None,
        "event_precision": exact / pred if pred else None,
        "codes_right_share": sum(x["events_codes_right"] for x in s) / pred if pred else None,
        "unsafe_cancellations": sum(x["unsafe"] for x in s),
    }


def _digest(item: dict[str, Any]) -> str:
    return hashlib.sha256((item["message"] + "|" + item["received_at"]).encode()).hexdigest()


def run_model(
    model: str, split: str, mode: str, fresh: bool, max_cost_usd: float
) -> dict[str, Any]:
    cfg = models_config()
    task = cfg.task("disruption_parse", model_override=model)
    client: ModelClient | None = client_for(mode, model)
    cache_dir = CACHE / model / task.prompt_version
    _, machines, materials, orders = catalog()
    spent = 0
    rows = []
    for item in load_items(split):
        path = cache_dir / f"{item['id']}.json"
        entry = (
            json.loads(path.read_text(encoding="utf-8")) if path.exists() and not fresh else None
        )
        if entry is not None and entry.get("message_sha256") != _digest(item):
            entry = None  # the message was edited since: call again (DEFECT_LOG #16)
        if entry is None:
            if client is None or mode != "live":
                raise StopEvalError(f"no saved reply for {item['id']}; run with AI_MODE=live")
            result = parse_message(
                client,
                mode=mode,
                message=item["message"],
                machines=machines,
                materials=materials,
                orders=orders,
                model=model,
            )
            record = result.record
            if record.outcome == "error" and record.error and "Authentication" in record.error:
                raise StopEvalError(f"the API refused the credentials: {record.error}")
            entry = {
                "id": item["id"],
                "message_sha256": _digest(item),
                "model": model,
                "prompt_version": record.prompt_version,
                "called_at": datetime.now(UTC).isoformat(timespec="seconds"),
                "parsed": result.value.model_dump(mode="json") if result.value else None,
                "record": {
                    **asdict(record),
                    "usage": asdict(record.usage),
                    "raw_replies": list(record.raw_replies),
                },
            }
            cache_dir.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(entry, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
                newline="\n",
            )
            spent += entry["record"]["cost_micro_usd"]
            if spent / 1_000_000 > max_cost_usd:
                raise StopEvalError(f"stopped: this run has spent more than ${max_cost_usd:.2f}")
        parsed = ParsedMessage.model_validate(entry["parsed"]) if entry["parsed"] else None
        pred = predicted(item, parsed)
        rows.append(
            {
                "id": item["id"],
                "split": item["split"],
                "prediction": pred,
                "score": score(item, pred),
                "outcome": entry["record"]["outcome"],
                "cost_micro_usd": entry["record"]["cost_micro_usd"],
            }
        )
    return {
        "model": model,
        "prompt_version": task.prompt_version,
        "split": split,
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "summary": {
            name: summarize_scores([r for r in rows if r["split"] == name])
            for name in ("dev", "heldout")
        },
        "cost_usd": sum(r["cost_micro_usd"] for r in rows) / 1_000_000,
        "items": rows,
    }


def _pct(v: float | None) -> str:
    return "—" if v is None else f"{v * 100:.0f}%"


def write_md(results: list[dict[str, Any]], path: Path) -> None:
    lines = [
        "# Disruption reading",
        "",
        "> Generated by `make eval` from `eval/datasets/disruptions.jsonl`. Do not edit by hand.",
        "",
        "36 messages written and labelled blind by a fresh-context agent from the brief and a fixture",
        "sheet only (`eval/datasets/disruptions_notes.md`): typos, German, Spanish, French and mixed",
        "messages, vague and ambiguous times, contradictions, several events in one message, unknown",
        "machines, and injection attempts. Scored after our code reads the model's reply as the app",
        "does (codes checked, times resolved in shop time). Tune on dev; held out is the honest number.",
        "",
        "| Model | Prompt | Set | Items | All correct | Events exact | Unclear right | Injection right | Event recall | Event precision | Unsafe cancellations | Cost |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in results:
        for name in ("dev", "heldout"):
            s = r["summary"][name]
            if s is None:
                continue
            lines.append(
                f"| {r['model']} | {r['prompt_version']} | {name} | {s['items']} | {_pct(s['all_correct'])}"
                f" | {_pct(s['events_correct'])} | {_pct(s['unclear_correct'])} | {_pct(s['injection_correct'])}"
                f" | {_pct(s['event_recall'])} | {_pct(s['event_precision'])} | {s['unsafe_cancellations']}"
                f" | ${r['cost_usd']:.4f} |"
            )
    lines.append("")
    for r in results:
        misses = [
            f"{i['id']} ({i['split']})"
            for i in r["items"]
            if not (
                i["score"]["events_correct"]
                and i["score"]["unclear_correct"]
                and i["score"]["injection_correct"]
            )
        ]
        lines.append(f"Not fully right, {r['model']}: {', '.join(misses) or 'none'}.")
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8", newline="\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m brimline_engine.evals.disruption_parse")
    parser.add_argument("--models", default=None)
    parser.add_argument("--split", choices=["dev", "heldout", "all"], default="all")
    parser.add_argument("--fresh", action="store_true")
    parser.add_argument("--max-cost-usd", type=float, default=0.20)
    args = parser.parse_args(argv)
    models = (
        args.models.split(",") if args.models else [models_config().task("disruption_parse").model]
    )
    mode = get_settings().ai_mode
    results = []
    try:
        for model in models:
            r = run_model(model, args.split, mode, args.fresh, args.max_cost_usd)
            (RESULTS / f"disruptions_{model}.json").write_text(
                json.dumps(r, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n"
            )
            results.append(r)
    except StopEvalError as exc:
        print(exc, file=sys.stderr)
        return 1
    write_md(results, RESULTS / "DISRUPTIONS.md")
    print(f"Wrote {RESULTS / 'DISRUPTIONS.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
