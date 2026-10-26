"""config/scheduler.toml, validated."""

import tomllib
from datetime import date
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from brimline_engine.settings import REPO_ROOT

SCHEDULER_CONFIG_PATH = REPO_ROOT / "config" / "scheduler.toml"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Durations(_Strict):
    prep_minutes: int = Field(ge=0)
    setup_minutes: int = Field(ge=0)
    changeover_minutes: int = Field(ge=0)
    finish_base_minutes: int = Field(ge=0)
    finish_minutes_per_part: int = Field(ge=0)
    cool_down_minutes: dict[str, int]


class Staff(_Strict):
    people_per_shift: int = Field(ge=1)


class Shifts(_Strict):
    weekdays: dict[str, tuple[str, str]]
    horizon_days: int = Field(ge=1, le=60)


class Weights(_Strict):
    late_job: int = Field(ge=0)
    tardiness_per_minute: int = Field(ge=0)
    changeover: int = Field(ge=0)
    finish_time_per_minute: int = Field(ge=0)
    unscheduled_job: int = Field(ge=0)
    rush_multiplier: int = Field(ge=1)


class Solver(_Strict):
    random_seed: int
    workers: int = Field(ge=1)
    deterministic_time_seconds: float = Field(gt=0)


class SchedulerConfig(_Strict):
    checked: date
    durations: Durations
    staff: Staff
    shifts: Shifts
    weights: Weights
    solver: Solver


def load_scheduler_config(path: Path = SCHEDULER_CONFIG_PATH) -> SchedulerConfig:
    with path.open("rb") as f:
        return SchedulerConfig.model_validate(tomllib.load(f))


@lru_cache
def scheduler_config() -> SchedulerConfig:
    return load_scheduler_config()
