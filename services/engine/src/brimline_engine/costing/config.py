"""config/costing.toml, typed."""

import tomllib
from datetime import date
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from brimline_engine.settings import REPO_ROOT

COSTING_CONFIG_PATH = REPO_ROOT / "config" / "costing.toml"


class FlagRule(BaseModel):
    model_config = ConfigDict(extra="forbid")
    threshold_ratio: float = Field(gt=1)
    min_jobs: int = Field(ge=1)
    alpha: float = Field(gt=0, lt=1)


class Scenario(BaseModel):
    model_config = ConfigDict(extra="forbid")
    time_noise_sigma: float = Field(ge=0)
    grams_noise_sigma: float = Field(ge=0)
    failure_chance: float = Field(ge=0, lt=1)
    failed_share_min: float = Field(gt=0, le=1)
    failed_share_max: float = Field(gt=0, le=1)
    max_attempts: int = Field(ge=1)
    demo_biased_material: str
    demo_bias: float = Field(gt=0)
    demo_jobs_per_material: int = Field(ge=1)
    demo_seed: int


class CostingConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    checked: date
    flag: FlagRule
    failure_reasons: list[str]
    scenario: Scenario


@lru_cache
def costing_config(path: Path = COSTING_CONFIG_PATH) -> CostingConfig:
    with path.open("rb") as f:
        return CostingConfig.model_validate(tomllib.load(f))
