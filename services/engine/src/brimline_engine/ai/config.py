"""config/models.toml, validated. Model names and prices come only from here (hard rule 8)."""

import tomllib
from datetime import date
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

from brimline_engine.settings import REPO_ROOT

MODELS_CONFIG_PATH = REPO_ROOT / "config" / "models.toml"

Effort = Literal["low", "medium", "high", "xhigh", "max"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ModelPrice(_Strict):
    input_usd_per_mtok: Decimal
    output_usd_per_mtok: Decimal
    cache_read_usd_per_mtok: Decimal
    cache_write_usd_per_mtok: Decimal


class TaskConfig(_Strict):
    model: str
    effort: Effort
    max_tokens: int
    prompt_version: str


class ModelsConfig(_Strict):
    checked: date
    source: str
    prices: dict[str, ModelPrice]
    tasks: dict[str, TaskConfig]

    def task(self, name: str, model_override: str | None = None) -> TaskConfig:
        task = self.tasks[name]
        if model_override is not None:
            task = task.model_copy(update={"model": model_override})
        if task.model not in self.prices:
            raise ValueError(f"no price configured for model {task.model}")
        return task


def load_models_config(path: Path = MODELS_CONFIG_PATH) -> ModelsConfig:
    with path.open("rb") as f:
        return ModelsConfig.model_validate(tomllib.load(f))


@lru_cache
def models_config() -> ModelsConfig:
    return load_models_config()
