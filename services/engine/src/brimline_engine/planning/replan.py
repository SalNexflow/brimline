"""What a re-plan changes, computed by code, and a plain-language summary of it (M6).

The diff compares the approved plan with the new one job by job: which jobs move (another
machine or another start), which become late or stop being late, and the totals. Lateness on
both sides comes from the independent checker's deadline report, not from the scheduler.

The summary is the only text a model writes about a re-plan, and it sees nothing but the diff.
Before it is shown, code checks it: every order, job, machine and number it mentions must
appear in the diff. If anything does not, it is thrown away and a summary written by code from
the same diff is shown instead (labelled as such).
"""

import json
import re
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import anthropic
from pydantic import BaseModel, ConfigDict, Field

from brimline_engine.ai.config import ModelsConfig, models_config
from brimline_engine.ai.gateway import CallRecord, ModelClient, run_structured
from brimline_engine.checker import CheckResult
from brimline_engine.planning.clock import at_minute
from brimline_engine.planning.inputs import Effects, JobRef

PURPOSE = "replan_summary"
MAX_LISTED = 25  # moved jobs listed in the diff (the totals count all of them)


def _local(dt: datetime, tz: str) -> str:
    return dt.astimezone(ZoneInfo(tz)).strftime("%a %d %b %H:%M")


def _machine_runs(doc: dict[str, Any]) -> dict[str, tuple[str, int, int]]:
    """job -> (machine, machine task start, finish) in the document's minutes."""
    out = {}
    for pj in doc["plan"]["jobs"]:
        start = next((t["start"] for t in pj["tasks"] if t["kind"] == "machine"), None)
        if start is not None:
            out[pj["job_id"]] = (pj["machine"], start, max(t["end"] for t in pj["tasks"]))
    return out


def compute_diff(
    *,
    before: dict[str, Any] | None,
    before_anchor: datetime | None,
    before_check: CheckResult | None,
    after: dict[str, Any],
    after_anchor: datetime,
    after_check: CheckResult,
    tz: str,
    refs: dict[str, JobRef],
    effects: Effects,
    events: list[str],
) -> dict[str, Any]:
    late_after = {d.job: d.tardiness for d in after_check.deadlines}
    late_before = (
        {d.job: d.tardiness for d in before_check.deadlines} if before_check is not None else {}
    )
    old = _machine_runs(before) if before is not None and before_anchor is not None else {}
    new = _machine_runs(after)

    def label(job: str) -> dict[str, Any]:
        r = refs.get(job)
        return {"job": job, "part": r.part_name if r else ""}

    moved = []
    for job, (machine, start, finish) in new.items():
        if job not in old or before_anchor is None:
            continue
        o_machine, o_start, o_finish = old[job]
        o_start_at = at_minute(o_start, before_anchor, tz)
        n_start_at = at_minute(start, after_anchor, tz)
        if (o_machine, o_start_at) != (machine, n_start_at):
            moved.append(
                label(job)
                | {
                    "before": {
                        "machine": o_machine,
                        "start": _local(o_start_at, tz),
                        "finish": _local(at_minute(o_finish, before_anchor, tz), tz),
                    },
                    "after": {
                        "machine": machine,
                        "start": _local(n_start_at, tz),
                        "finish": _local(at_minute(finish, after_anchor, tz), tz),
                    },
                    "late_minutes_before": late_before.get(job, 0),
                    "late_minutes_after": late_after.get(job, 0),
                }
            )
    became_late = sorted(j for j, t in late_after.items() if t > 0 and late_before.get(j, 0) == 0)
    no_longer = sorted(j for j, t in late_before.items() if t > 0 and late_after.get(j, 0) == 0)
    unscheduled_before = set(before["plan"]["unscheduled"]) if before is not None else set()
    unscheduled_after = set(after["plan"]["unscheduled"])
    m_after = after_check.metrics
    m_before = before_check.metrics if before_check is not None else None
    return {
        "events": events,
        "totals": {
            "jobs_planned": len(new),
            "jobs_moved": len(moved),
            "late_before": None if m_before is None else m_before.late_jobs,
            "late_after": None if m_after is None else m_after.late_jobs,
            "lateness_minutes_before": None
            if m_before is None
            else m_before.total_lateness_minutes,
            "lateness_minutes_after": None if m_after is None else m_after.total_lateness_minutes,
            "unscheduled_before": len(unscheduled_before),
            "unscheduled_after": len(unscheduled_after),
        },
        "moved": moved[:MAX_LISTED],
        "moved_not_listed": max(0, len(moved) - MAX_LISTED),
        "became_late": [label(j) | {"late_minutes": late_after[j]} for j in became_late],
        "no_longer_late": [label(j) for j in no_longer],
        "newly_unscheduled": sorted(unscheduled_after - unscheduled_before),
        "cancelled": effects.cancelled,
        "lost_prints": [{"job": x["job"], "machine": x["machine"]} for x in effects.lost],
        "overruns": [
            {
                "job": x["job"],
                "machine": x["machine"],
                "until": _local(datetime.fromisoformat(x["ends_at"]), tz),
                "estimated": x["estimated"],
            }
            for x in effects.overruns
        ],
        "notes": effects.notes,
        "warnings": (
            [
                f"This plan cancels {len(effects.cancelled)} jobs: "
                + ", ".join(c["job"] for c in effects.cancelled)
                + ". Check each one before approving."
            ]
            if len(effects.cancelled) >= 2
            else []
        ),
    }


# --- The summary ----------------------------------------------------------------------------


class Summary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str = Field(min_length=1, max_length=600)
    highlights: list[str] = Field(max_length=5)


JSON_SCHEMA: dict[str, Any] = anthropic.transform_schema(Summary)

SYSTEM = """\
You write a short summary of a production re-plan for the shop's planner, who decides whether \
to approve it. Use only the facts in the JSON inside <plan_diff>: the events, the totals, the \
jobs that moved, and the notes. Mention only orders, jobs, machines, times and numbers that \
appear there, exactly as written. Do not guess reasons, do not recommend, do not add anything \
that is not in the diff. Plain English, at most 600 characters, and at most 5 short highlights \
(the most important changes first). If nothing moved, say so."""

IDENTIFIER = re.compile(r"\b[A-Z]{2,}-\d+(?:-\d+)?\b")
NUMBER = re.compile(r"\d+(?:[.,]\d+)?")


def grounding_problems(summary: Summary, diff_text: str) -> list[str]:
    """Anything the summary mentions that the diff does not contain."""
    text = " ".join([summary.summary, *summary.highlights])
    known_ids = set(IDENTIFIER.findall(diff_text))
    known_numbers = set(NUMBER.findall(diff_text))
    problems = [
        f"mentions {x}, not in the diff" for x in IDENTIFIER.findall(text) if x not in known_ids
    ]
    without_ids = IDENTIFIER.sub(" ", text)
    problems += [
        f"says {n}, not in the diff" for n in NUMBER.findall(without_ids) if n not in known_numbers
    ]
    return problems


def code_summary(diff: dict[str, Any]) -> str:
    """The plain summary code writes from the diff when the model's is missing or rejected."""
    t = diff["totals"]
    parts = [f"{t['jobs_moved']} of {t['jobs_planned']} planned jobs move."]
    if t["late_before"] is not None:
        parts.append(
            f"Late jobs: {t['late_before']} before, {t['late_after']} after; total lateness"
            f" {t['lateness_minutes_before']} min before, {t['lateness_minutes_after']} min after."
        )
    if diff["cancelled"]:
        parts.append(f"{len(diff['cancelled'])} job(s) cancelled.")
    if diff["lost_prints"]:
        parts.append(f"{len(diff['lost_prints'])} running print(s) treated as lost.")
    if diff["newly_unscheduled"]:
        parts.append(f"{len(diff['newly_unscheduled'])} job(s) no longer fit the horizon.")
    return " ".join(parts)


def summarize(
    client: ModelClient | None,
    *,
    mode: str,
    diff: dict[str, Any],
    config: ModelsConfig | None = None,
) -> tuple[dict[str, Any], CallRecord | None]:
    """{"text", "highlights", "source": "ai" | "code", "rejected": reasons or None}, and the
    model call's record (None when no model was asked)."""
    fallback: dict[str, Any] = {
        "text": code_summary(diff),
        "highlights": [],
        "source": "code",
        "rejected": None,
    }
    if client is None:
        return fallback, None
    cfg = config or models_config()
    task = cfg.task(PURPOSE)
    diff_text = json.dumps(diff, ensure_ascii=False, sort_keys=True)
    result = run_structured(
        client,
        purpose=PURPOSE,
        mode=mode,
        task=task,
        price=cfg.prices[task.model],
        schema=Summary,
        json_schema=JSON_SCHEMA,
        system=SYSTEM,
        user=f"<plan_diff>{diff_text}</plan_diff>",
    )
    if result.value is None:
        return fallback | {"rejected": [f"no valid reply ({result.record.outcome})"]}, result.record
    problems = grounding_problems(result.value, diff_text)
    if problems:
        return fallback | {"rejected": problems}, result.record
    return {
        "text": result.value.summary,
        "highlights": result.value.highlights,
        "source": "ai",
        "rejected": None,
    }, result.record
