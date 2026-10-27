"""The checker's reading of config/scheduler.toml, and the durations and shift windows it implies.

Reimplemented from docs/SCHEDULE_RULES.md, not imported from the scheduler: if the two ever
read the config differently, the re-scoring of the benchmark shows it.
"""

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from brimline_engine.checker.document import Fixed, Job

# services/engine/src/brimline_engine/checker/rules.py -> repository root
CONFIG_PATH = Path(__file__).resolve().parents[5] / "config" / "scheduler.toml"

DAY = 1440
FIRST_MINUTE = 8 * 60  # minute 0 is Monday 08:00


@dataclass(frozen=True)
class Weights:
    late_job: int
    tardiness_per_minute: int
    changeover: int
    finish_time_per_minute: int
    unscheduled_job: int
    rush_multiplier: int


@dataclass(frozen=True)
class Rules:
    prep: int
    setup: int
    changeover: int
    finish_base: int
    finish_per_part: int
    cool_down: dict[str, int]
    post_process: dict[str, int]  # minutes per part for each post-processing step
    staff: int
    windows: tuple[tuple[int, int], ...]  # staffed [start, end) minutes, sorted
    weights: Weights


def _int(table: dict[str, Any], key: str) -> int:
    value = table[key]
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"scheduler.toml: {key} must be a whole number >= 0, got {value!r}")
    return value


def _clock(hhmm: str) -> int:
    hours, minutes = hhmm.split(":")
    return int(hours) * 60 + int(minutes)


def windows(weekdays: dict[str, list[str]], days: int) -> tuple[tuple[int, int], ...]:
    """Day d (0 = the first Monday) is ISO weekday d % 7 + 1; its hours become one window."""
    out = []
    for d in range(days):
        hours = weekdays.get(str(d % 7 + 1))
        if hours:
            midnight = d * DAY - FIRST_MINUTE
            out.append((midnight + _clock(hours[0]), midnight + _clock(hours[1])))
    return tuple(out)


def rules_from_toml(data: dict[str, Any]) -> Rules:
    d, w, s = data["durations"], data["weights"], data["shifts"]
    return Rules(
        prep=_int(d, "prep_minutes"),
        setup=_int(d, "setup_minutes"),
        changeover=_int(d, "changeover_minutes"),
        finish_base=_int(d, "finish_base_minutes"),
        finish_per_part=_int(d, "finish_minutes_per_part"),
        cool_down={k: _int(d["cool_down_minutes"], k) for k in d["cool_down_minutes"]},
        post_process={
            k: _int(d["post_process_minutes_per_part"], k)
            for k in d.get("post_process_minutes_per_part", {})
        },
        staff=_int(data["staff"], "people_per_shift"),
        windows=windows(s["weekdays"], _int(s, "horizon_days")),
        weights=Weights(
            late_job=_int(w, "late_job"),
            tardiness_per_minute=_int(w, "tardiness_per_minute"),
            changeover=_int(w, "changeover"),
            finish_time_per_minute=_int(w, "finish_time_per_minute"),
            unscheduled_job=_int(w, "unscheduled_job"),
            rush_multiplier=_int(w, "rush_multiplier"),
        ),
    )


def load_rules(path: Path = CONFIG_PATH) -> Rules:
    with path.open("rb") as f:
        return rules_from_toml(tomllib.load(f))


def durations(job: Job, r: Rules, fixed: Fixed | None) -> dict[str, int]:
    """The job's tasks in order with their minutes. A zero-length task does not exist. A job
    whose machine task is fixed (running or done) has no prep left, and its machine task lasts
    from the fixed start to the fixed end when the end is known."""
    formula = r.setup + job.quantity * job.minutes_per_part + r.cool_down.get(job.process, 0)
    minutes = {
        "prep": 0 if fixed is not None else r.prep,
        "machine": fixed.end - fixed.start if fixed and fixed.end is not None else formula,
        "post": job.quantity * job.post_minutes_per_part,
        "finish": r.finish_base + job.quantity * r.finish_per_part,
    }
    return {kind: m for kind, m in minutes.items() if m > 0}
