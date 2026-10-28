"""Evaluate the file checker (M7) against hand-labelled test models.

    uv run python -m brimline_engine.evals.files

Two label sets, both following eval/datasets/files_labelling.md:
- eval/datasets/files/dev: written by the builder (dev only);
- eval/datasets/files/blind: written and labelled blind by a fresh-context agent from the brief
  and the labelling guide only; its own dev half and a held-out half (never tuned on).

Per check: agreement with the label, and the false pass count (labelled fail, checker said pass).
Overall: the false pass rate (a file labelled broken that the checker passed), the share of
broken files shown only as a warning, and false alarms (labelled pass, checker failed).
No model is called: the checker is code only. Writes eval/results/FILES.md and files.json.
"""

import json
import time
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from brimline_engine.files.checks import CHECKS, check_file
from brimline_engine.files.config import files_config
from brimline_engine.settings import REPO_ROOT
from brimline_engine.shop_config import load_shop_config

DATASETS = REPO_ROOT / "eval" / "datasets" / "files"
RESULTS = REPO_ROOT / "eval" / "results"
SETS = (("dev", "builder"), ("blind", "blind agent"))


def load_labels() -> list[dict[str, Any]]:
    items = []
    for folder, author in SETS:
        path = DATASETS / folder / "labels.jsonl"
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                item = json.loads(line)
                item["path"] = str(DATASETS / folder / item["file"])
                item["author"] = author
                items.append(item)
    return items


def run(items: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    cfg = files_config()
    machines = load_shop_config().machines
    out = []
    for item in items:
        path = Path(item["path"])
        started = time.perf_counter()
        report = check_file(path.read_bytes(), path.name, item["process"], machines, cfg)
        seconds = time.perf_counter() - started
        m = report.measurements
        out.append(
            item
            | {
                "got": {c.name: c.status for c in report.checks},
                "got_overall": report.overall,
                "reasons": {c.name: c.reason for c in report.checks if c.status != "pass"},
                "got_size_mm": list(m.size_mm) if m else None,
                "seconds": round(seconds, 3),
            }
        )
    return out


def score(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Agreement and misses for one group of scored rows (pure: tested with hand-made rows)."""
    per_check = {}
    for check in CHECKS:
        agree = sum(r["got"][check] == r["expected"][check] for r in rows)
        labelled_fail = [r for r in rows if r["expected"][check] == "fail"]
        per_check[check] = {
            "agreement": agree,
            "n": len(rows),
            "labelled_fail": len(labelled_fail),
            "false_pass": sum(r["got"][check] == "pass" for r in labelled_fail),
            "fail_as_warn": sum(r["got"][check] == "warn" for r in labelled_fail),
        }
    broken = [r for r in rows if r["overall"] == "fail"]
    labelled_pass = [r for r in rows if r["overall"] == "pass"]
    sized = [r for r in rows if r["size_mm"] is not None and r["got_size_mm"] is not None]
    return {
        "n": len(rows),
        "overall_agreement": sum(r["got_overall"] == r["overall"] for r in rows),
        "broken": len(broken),
        "false_pass": sum(r["got_overall"] == "pass" for r in broken),
        "broken_as_warn": sum(r["got_overall"] == "warn" for r in broken),
        "labelled_pass": len(labelled_pass),
        "false_alarm": sum(r["got_overall"] == "fail" for r in labelled_pass),
        "size_within_0_01_mm": sum(
            all(abs(a - b) <= 0.01 for a, b in zip(r["size_mm"], r["got_size_mm"], strict=True))
            for r in sized
        ),
        "sized": len(sized),
        "per_check": per_check,
        "slowest_seconds": max((r["seconds"] for r in rows), default=0.0),
        "disagreements": [
            {
                "id": r["id"],
                "check": c,
                "label": r["expected"][c],
                "got": r["got"][c],
                "reason": r["reasons"].get(c, ""),
            }
            for r in rows
            for c in CHECKS
            if r["got"][c] != r["expected"][c]
        ],
    }


def groups(rows: Sequence[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    return {
        "dev (builder)": [r for r in rows if r["author"] == "builder"],
        "dev (blind)": [r for r in rows if r["author"] == "blind agent" and r["split"] == "dev"],
        "held out (blind)": [r for r in rows if r["split"] == "held_out"],
    }


def _pct(a: int, b: int) -> str:
    return f"{a}/{b} ({100 * a / b:.0f} %)" if b else "n/a"


def markdown(scores: dict[str, dict[str, Any]], when: str) -> str:
    names = list(scores)
    out = [
        "# File checker evaluation (M7)",
        "",
        f"Written by `make eval` ({when}). Code only: no model is called. Labels follow",
        "`eval/datasets/files_labelling.md`; the blind set was written and labelled by a",
        "fresh-context agent that never saw the checker. Thresholds: `config/files.toml`.",
        "",
        "**False pass** = a file labelled broken (overall fail) that the checker passed. A broken",
        "file shown as a warning is counted apart: staff see it, but it is not a fail.",
        "",
        "| | " + " | ".join(names) + " |",
        "|---|" + "---|" * len(names),
    ]
    rows: list[tuple[str, Callable[[dict[str, Any]], str]]] = [
        ("Models", lambda s: str(s["n"])),
        ("Overall verdict agrees", lambda s: _pct(s["overall_agreement"], s["n"])),
        ("**False pass rate** (broken passed)", lambda s: _pct(s["false_pass"], s["broken"])),
        ("Broken shown only as warning", lambda s: _pct(s["broken_as_warn"], s["broken"])),
        ("False alarm (valid file failed)", lambda s: _pct(s["false_alarm"], s["labelled_pass"])),
        ("Size within 0.01 mm", lambda s: _pct(s["size_within_0_01_mm"], s["sized"])),
        ("Slowest file (s)", lambda s: f"{s['slowest_seconds']:.2f}"),
    ]
    out += [f"| {label} | " + " | ".join(f(scores[n]) for n in names) + " |" for label, f in rows]
    out += [
        "",
        "## Agreement per check",
        "",
        "Agreement, then false passes / files labelled fail for that check.",
        "",
    ]
    out += ["| Check | " + " | ".join(names) + " |", "|---|" + "---|" * len(names)]
    for check in CHECKS:
        cells = []
        for n in names:
            c = scores[n]["per_check"][check]
            miss = (
                f"{c['false_pass']} false pass of {c['labelled_fail']}"
                if c["labelled_fail"]
                else "none labelled fail"
            )
            cells.append(f"{_pct(c['agreement'], c['n'])}; {miss}")
        out.append(f"| {check} | " + " | ".join(cells) + " |")
    out += ["", "## Every disagreement", ""]
    for n in names:
        dis = scores[n]["disagreements"]
        out.append(f"**{n}:** " + ("none." if not dis else ""))
        out += [
            f"- {d['id']} {d['check']}: label {d['label']}, checker {d['got']}. {d['reason']}"
            for d in dis
        ]
        out.append("")
    return "\n".join(out)


def real_models() -> tuple[list[dict[str, Any]], str]:
    """Free-licence real models (eval/datasets/files/real): only the checks a person can judge
    from the picture and the file's size are labelled; the rest are shown, not scored."""
    folder = DATASETS / "real"
    sources = {
        s["id"]: s for s in json.loads((folder / "sources.json").read_text(encoding="utf-8"))
    }
    items = [
        json.loads(line) | {"path": str(folder / json.loads(line)["file"])}
        for line in (folder / "labels.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    cfg = files_config()
    machines = load_shop_config().machines
    rows, agree, labelled = [], 0, 0
    lines = [
        "## Real models (CC0 or public domain)",
        "",
        "Five free-licence files from Wikimedia Commons (`eval/datasets/files/real/sources.json`).",
        "Only checks a person can judge by eye or from the size are labelled; closedness and walls",
        "of organic shapes are not. Shown: every check's result; scored: the labelled ones.",
        "",
        "| Model | Licence | Size (mm) | " + " | ".join(CHECKS) + " | Labelled checks agree |",
        "|---|---|---|" + "---|" * len(CHECKS) + "---|",
    ]
    for item in items:
        path = Path(item["path"])
        report = check_file(path.read_bytes(), path.name, item["process"], machines, cfg)
        got = {c.name: c.status for c in report.checks}
        ok = sum(got[c] == v for c, v in item["expected"].items())
        agree, labelled = agree + ok, labelled + len(item["expected"])
        src = sources[item["id"]]
        size = (
            " x ".join(f"{v:.1f}" for v in report.measurements.size_mm)
            if report.measurements
            else "-"
        )
        cells = [
            f"**{got[c]}**" if c in item["expected"] and got[c] != item["expected"][c] else got[c]
            for c in CHECKS
        ]
        lines.append(
            f"| [{src['name']}]({src['url']}) | {src['licence']} | {size} | "
            + " | ".join(cells)
            + f" | {ok}/{len(item['expected'])} |"
        )
        rows.append(item | {"got": got, "agree": ok})
    lines += [
        "",
        f"Labelled checks that agree: {agree}/{labelled}. A result in **bold** disagrees with its label.",
        "Two of these (the tower and the building site) are most likely modelled in centimetres. The",
        "building site, 3.6 mm across, passes the unit check (a limit of the 3 mm rule); the tower",
        "measures 3.0 mm, on the rule's edge, and the checker warns while the label said pass",
        "(docs/DECISIONS.md D128).",
    ]
    return rows, "\n".join(lines)


def main() -> None:
    rows = run(load_labels())
    scores = {name: score(group) for name, group in groups(rows).items()}
    real_rows, real_md = real_models()
    when = datetime.now(UTC).strftime("%Y-%m-%d")
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "files.json").write_text(
        json.dumps(
            {"date": when, "scores": scores, "rows": rows, "real": real_rows}, indent=1, default=str
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    (RESULTS / "FILES.md").write_text(
        markdown(scores, when) + "\n" + real_md + "\n", encoding="utf-8", newline="\n"
    )
    for name, s in scores.items():
        print(
            f"{name}: overall {s['overall_agreement']}/{s['n']}, false pass {s['false_pass']}/{s['broken']},"
            f" disagreements {len(s['disagreements'])}"
        )


if __name__ == "__main__":
    main()
