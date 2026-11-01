"""config/purchasing.toml, typed."""

import tomllib
from datetime import date, time
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from brimline_engine.settings import REPO_ROOT

PURCHASING_CONFIG_PATH = REPO_ROOT / "config" / "purchasing.toml"


class Supply(BaseModel):
    model_config = ConfigDict(extra="forbid")
    supplier: str = Field(min_length=1, max_length=100)
    lead_time_days: int = Field(ge=0, le=90)
    pack_grams: int = Field(gt=0)
    safety_stock_g: int = Field(ge=0)


class PurchasingConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    checked: date
    delivery_time: time
    materials: dict[str, Supply]


@lru_cache
def purchasing_config(path: Path = PURCHASING_CONFIG_PATH) -> PurchasingConfig:
    with path.open("rb") as f:
        return PurchasingConfig.model_validate(tomllib.load(f))
