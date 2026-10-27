"""config/files.toml, validated: file-checker limits, thresholds and estimates."""

import tomllib
from datetime import date
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, model_validator

from brimline_engine.settings import REPO_ROOT

FILES_CONFIG_PATH = REPO_ROOT / "config" / "files.toml"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Limits(_Strict):
    max_upload_bytes: int = Field(gt=0)
    max_unzipped_bytes: int = Field(gt=0)
    max_triangles: int = Field(gt=0)
    wall_rays: int = Field(gt=0)
    # Ray-triangle tests allowed per file; big meshes get fewer rays so a check stays quick.
    wall_ray_tests: int = Field(gt=0)


class Scale(_Strict):
    smallest_plausible_mm: float = Field(gt=0)
    largest_plausible_mm: float = Field(gt=0)


class WallLimits(_Strict):
    fail_mm: float = Field(gt=0)
    warn_mm: float = Field(gt=0)

    @model_validator(mode="after")
    def warn_above_fail(self) -> "WallLimits":
        if self.warn_mm < self.fail_mm:
            raise ValueError("warn_mm must not be below fail_mm")
        return self


class Walls(_Strict):
    min_thin_area_mm2: float = Field(ge=0)
    fdm: WallLimits
    resin: WallLimits
    cnc: WallLimits


class Overhangs(_Strict):
    warn_share: float = Field(gt=0, le=1)
    max_from_vertical_deg: dict[str, float]


class LooseParts(_Strict):
    debris_mm3: float = Field(ge=0)


class Estimates(_Strict):
    fdm_fill: float = Field(gt=0, le=1)
    resin_fill: float = Field(gt=0, le=1)
    fdm_mm3_per_minute: float = Field(gt=0)
    fdm_minimum_minutes: int = Field(ge=1)
    resin_layer_mm: float = Field(gt=0)
    resin_seconds_per_layer: float = Field(gt=0)


class AdviceConfig(_Strict):
    enabled: bool


class FilesConfig(_Strict):
    checked: date
    limits: Limits
    scale: Scale
    walls: Walls
    overhangs: Overhangs
    loose_parts: LooseParts
    estimates: Estimates
    density_g_per_cm3: dict[str, float]
    advice: AdviceConfig


def load_files_config(path: Path = FILES_CONFIG_PATH) -> FilesConfig:
    with path.open("rb") as f:
        return FilesConfig.model_validate(tomllib.load(f))


@lru_cache
def files_config() -> FilesConfig:
    return load_files_config()
