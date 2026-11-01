"""config/machines.toml, typed."""

import tomllib
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from brimline_engine.settings import REPO_ROOT

MACHINES_CONFIG_PATH = REPO_ROOT / "config" / "machines.toml"
Protocol = Literal["octoprint", "moonraker", "prusalink", "bambu", "formlabs", "grbl"]


class Sim(BaseModel):
    model_config = ConfigDict(extra="forbid")
    host: str
    speed: float = Field(gt=0)
    slow_delay_seconds: float = Field(ge=0)
    timeout_seconds: float = Field(gt=0)
    poll_seconds: float = Field(gt=0)


class MachineConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str
    protocol: Protocol
    source: Literal["official", "community"]
    docs: str
    read: date
    port: int = Field(ge=0, le=65535)  # 0: any free port (tests)
    api_key: str | None = None
    username: str | None = None
    password: str | None = None
    serial: str | None = None
    access_code: str | None = None
    printer: str | None = None


class MachinesConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    checked: date
    sim: Sim
    machines: list[MachineConfig]

    def by_code(self) -> dict[str, MachineConfig]:
        return {m.code: m for m in self.machines}


@lru_cache
def machines_config(path: Path = MACHINES_CONFIG_PATH) -> MachinesConfig:
    with path.open("rb") as f:
        return MachinesConfig.model_validate(tomllib.load(f))
