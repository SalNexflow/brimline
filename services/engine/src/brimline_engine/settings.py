"""Runtime settings from environment variables and the repo-root .env (see .env.example)."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# src/brimline_engine/settings.py -> repo root is four folders up.
REPO_ROOT = Path(__file__).resolve().parents[4]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=REPO_ROOT / ".env", extra="ignore")

    # The engine's runtime connection uses the limited app role (brimline_app).
    database_url: str
    # The owner role runs migrations and the seed. Only the CLI and tests need it.
    database_owner_url: str | None = None

    session_secret: SecretStr = Field(min_length=32)
    session_ttl_minutes: int = Field(default=480, gt=0, le=7 * 24 * 60)
    # Off unless explicitly enabled, so a deployment cannot ship demo login by accident.
    demo_login: bool = False
    # Which model client to use: live, fake (tests), off (everything by hand), record (live, and
    # every reply written to the recording file), replay (recorded replies only; M11).
    ai_mode: Literal["live", "fake", "off", "record", "replay"] = "off"
    # The hosted public demo (M11, config/demo.toml): spend limits, a shorter solver run,
    # storage caps, smaller uploads. Off locally and in the gate.
    demo_mode: bool = False
    # When set, every request except /health must carry it (X-Engine-Key): only the web can
    # call the engine, and only then is the visitor id it passes on (X-Visitor) believed.
    engine_web_key: SecretStr | None = None
    # Read by the DeepSeek client. (The Claude client finds ANTHROPIC_API_KEY itself.)
    deepseek_api_key: SecretStr | None = None

    @field_validator("session_secret")
    @classmethod
    def secret_is_not_the_placeholder(cls, value: SecretStr) -> SecretStr:
        if value.get_secret_value().startswith("replace-me"):
            raise ValueError("SESSION_SECRET is still the .env.example placeholder; run make setup")
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]  # values come from the environment
