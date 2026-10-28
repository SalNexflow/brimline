"""Spending limits for the hosted demo, and recorded replies (M11).

  RecordingClient   wraps a live client and writes each reply to the recording file
                    (AI_MODE=record), so a run can be replayed later without a model;
  ReplayClient      answers from that file only (AI_MODE=replay, and the video); a prompt that
                    was never recorded raises ModelUnavailableError, and the app's by-hand
                    path takes over, as with AI off;
  GuardedClient     in demo mode: a live call only while today's spend and this visitor's hourly
                    calls are under config/demo.toml; otherwise the replay client.

Spend is read from ai_calls, the same append-only cost record every call writes, so the limit
holds across restarts and engine copies. The visitor is a hash the web passes on (the engine
accepts it only with the shared web key, see main.py)."""

import hashlib
import json
import tomllib
from contextvars import ContextVar
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Any

import psycopg
from pydantic import BaseModel, ConfigDict, Field

from brimline_engine.ai.config import Effort
from brimline_engine.ai.gateway import (
    ModelClient,
    ModelReply,
    ModelUnavailableError,
    TokenUsage,
    Turn,
)
from brimline_engine.settings import REPO_ROOT

DEMO_CONFIG_PATH = REPO_ROOT / "config" / "demo.toml"

# Set per request by main.py; read when a call is recorded and when limits are checked.
VISITOR: ContextVar[str | None] = ContextVar("visitor", default=None)
# Set when a reply came from the recording instead of a live model, so the page can say so.
REPLAYED: ContextVar[bool] = ContextVar("replayed", default=False)


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Budget(_Strict):
    daily_usd: float = Field(ge=0)
    per_visitor_per_hour: int = Field(ge=0)


class DemoSolver(_Strict):
    deterministic_time_seconds: float = Field(gt=0)


class Storage(_Strict):
    max_database_mb: int = Field(gt=0)
    max_rows: dict[str, int]


class DemoFiles(_Strict):
    max_upload_bytes: int = Field(gt=0)


class Recording(_Strict):
    path: str


class DemoConfig(_Strict):
    checked: date
    budget: Budget
    solver: DemoSolver
    storage: Storage
    files: DemoFiles
    recording: Recording


@lru_cache
def demo_config(path: Path = DEMO_CONFIG_PATH) -> DemoConfig:
    with path.open("rb") as f:
        return DemoConfig.model_validate(tomllib.load(f))


def prompt_key(model: str, system: str, turns: list[Turn]) -> str:
    """The same prompt always gets the same key (pictures included)."""
    h = hashlib.sha256()
    for part in (model, system, *(t.role + "\0" + t.content for t in turns)):
        h.update(part.encode())
        h.update(b"\1")
    for t in turns:
        for png in t.images:
            h.update(hashlib.sha256(png).digest())
    return h.hexdigest()


def load_recording(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    out = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            entry = json.loads(line)
            out[entry["key"]] = entry["text"]
    return out


class ReplayClient:
    def __init__(self, path: Path) -> None:
        self._replies = load_recording(path)

    def call(
        self,
        *,
        model: str,
        system: str,
        turns: list[Turn],
        json_schema: dict[str, Any],
        max_tokens: int,
        effort: Effort,
    ) -> ModelReply:
        text = self._replies.get(prompt_key(model, system, turns))
        if text is None:
            raise ModelUnavailableError("no recorded reply for this prompt (replay mode)")
        REPLAYED.set(True)
        return ModelReply(text=text, stop_reason="end_turn", usage=TokenUsage())


class RecordingClient:
    def __init__(self, inner: ModelClient, path: Path) -> None:
        self._inner, self._path = inner, path

    def call(
        self,
        *,
        model: str,
        system: str,
        turns: list[Turn],
        json_schema: dict[str, Any],
        max_tokens: int,
        effort: Effort,
    ) -> ModelReply:
        reply = self._inner.call(
            model=model, system=system, turns=turns, json_schema=json_schema,
            max_tokens=max_tokens, effort=effort,
        )  # fmt: skip
        if reply.text is not None:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._path.open("a", encoding="utf-8", newline="\n") as f:
                f.write(
                    json.dumps({"key": prompt_key(model, system, turns), "text": reply.text}) + "\n"
                )
        return reply


class Spend(BaseModel):
    today_usd: float
    visitor_calls_last_hour: int


def spend(conn: psycopg.Connection, visitor: str | None) -> Spend:
    today = conn.execute(
        "SELECT coalesce(sum(cost_micro_usd), 0) FROM ai_calls"
        " WHERE created_at >= date_trunc('day', now(), 'UTC')"
    ).fetchone()
    mine = conn.execute(
        "SELECT count(*) FROM ai_calls WHERE visitor = %s AND mode = 'live'"
        " AND created_at > now() - interval '1 hour'",
        (visitor,),
    ).fetchone()
    assert today is not None and mine is not None
    return Spend(today_usd=int(today[0]) / 1_000_000, visitor_calls_last_hour=int(mine[0]))


def over_limit(s: Spend, budget: Budget) -> str | None:
    """Why a live call is not allowed now, in plain words, or None."""
    if s.today_usd >= budget.daily_usd:
        return "the demo's model budget for today is used up"
    if s.visitor_calls_last_hour >= budget.per_visitor_per_hour:
        return "you have used this hour's model calls for the demo"
    return None


class GuardedClient:
    """Live while under the limits, replayed (or by hand) after. Checked on every call."""

    def __init__(
        self, live: ModelClient, replay: ReplayClient, database_url: str, budget: Budget
    ) -> None:
        self._live, self._replay, self._url, self._budget = live, replay, database_url, budget

    def call(
        self,
        *,
        model: str,
        system: str,
        turns: list[Turn],
        json_schema: dict[str, Any],
        max_tokens: int,
        effort: Effort,
    ) -> ModelReply:
        with psycopg.connect(self._url) as conn:
            reason = over_limit(spend(conn, VISITOR.get()), self._budget)
        target: ModelClient = self._replay if reason else self._live
        return target.call(
            model=model, system=system, turns=turns, json_schema=json_schema,
            max_tokens=max_tokens, effort=effort,
        )  # fmt: skip


def visitor_hash(raw: str, key: str) -> str:
    """A visitor id that is not their address: a keyed hash, cut short."""
    return hashlib.sha256((key + "|" + raw).encode()).hexdigest()[:16]
