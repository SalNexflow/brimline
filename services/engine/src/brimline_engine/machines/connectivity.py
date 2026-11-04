"""Connectivity (M12b): is each machine answering, and how fast? (config/connectivity.toml)

The engine polls every machine with one read-only status call, records each result in machine_polls,
and code derives the connection state from those rows. Nothing here changes a machine, and nothing a
machine says is acted on: its text is stored as plain text and shown labelled.

A machine fault (a failed or offline state, or a start the machine refused) is kept apart from the
connection: a machine that answers every poll but refuses to start is connected, with a fault (D197).
"""

import logging
import statistics
import threading
import time
import tomllib
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Literal

import psycopg
from pydantic import BaseModel, ConfigDict, Field

from brimline_engine.machines.model import Adapter, AdapterError
from brimline_engine.settings import REPO_ROOT
from brimline_engine.text import plain_text

log = logging.getLogger(__name__)

CONNECTIVITY_CONFIG_PATH = REPO_ROOT / "config" / "connectivity.toml"
ConnectionState = Literal["connected", "slow", "unreachable", "no_data"]


class ConnectivityConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    checked: date
    poll_seconds: float = Field(gt=0)
    demo_poll_seconds: float = Field(gt=0)
    slow_ms: int = Field(gt=0)
    slow_window: int = Field(ge=1)
    unreachable_after: int = Field(ge=1)
    stale_seconds: int = Field(gt=0)
    uptime_minutes: int = Field(gt=0)
    history_polls: int = Field(ge=1, le=200)
    keep_minutes: int = Field(gt=0)
    test_every_seconds: int = Field(ge=0)


@lru_cache
def connectivity_config(path: Path = CONNECTIVITY_CONFIG_PATH) -> ConnectivityConfig:
    with path.open("rb") as f:
        return ConnectivityConfig.model_validate(tomllib.load(f))


# --- Deriving the state (pure) -----------------------------------------------------------------


@dataclass(frozen=True)
class Poll:
    at: datetime
    ok: bool
    response_ms: int


def derive_state(polls: Sequence[Poll], now: datetime, cfg: ConnectivityConfig) -> ConnectionState:
    """The connection state from recorded polls, newest first (the recent history, at most
    `history_polls`): one missed answer after good ones is a blip, but a machine with no answer
    at all in its history is unreachable."""
    if not polls or now - polls[0].at > timedelta(seconds=cfg.stale_seconds):
        return "no_data"
    latest = polls[: cfg.unreachable_after]
    if not any(p.ok for p in polls):  # it has never answered (review of M12b: not "connected")
        return "unreachable"
    if len(latest) == cfg.unreachable_after and not any(p.ok for p in latest):
        return "unreachable"
    answered = [p.response_ms for p in polls if p.ok][: cfg.slow_window]
    if answered and statistics.median(answered) >= cfg.slow_ms:
        return "slow"
    return "connected"


def is_slow(response_ms: int, cfg: ConnectivityConfig) -> bool:
    return response_ms >= cfg.slow_ms


# --- Asking a machine --------------------------------------------------------------------------


@dataclass(frozen=True)
class ProbeResult:
    ok: bool
    response_ms: int
    state: str | None
    error_kind: str | None  # timeout | refused | unsupported | protocol | other
    error: str  # what Brimline saw
    machine_says: str  # the machine's own text: untrusted


def probe(adapter: Adapter, clock: Callable[[], float] = time.monotonic) -> ProbeResult:
    """One read-only status call. Never raises: an adapter bug is a failed poll, not a stopped loop."""
    started = clock()
    kind: str | None
    state: str | None
    try:
        s = adapter.get_status()
    except AdapterError as e:
        kind, error, state, says, ok = e.kind, e.detail, None, "", False
    except Exception as e:  # one machine's bug must not stop the others (#97)
        kind, error, state, says, ok = "other", f"unexpected {type(e).__name__}", None, "", False
    else:
        kind, error, state, says, ok = None, "", s.state, s.message, True
    ms = max(0, round((clock() - started) * 1000))
    return ProbeResult(ok, ms, state, kind, plain_text(error), plain_text(says))


def record(
    conn: psycopg.Connection,
    machine: str,
    result: ProbeResult,
    at: datetime,
    tested_by: int | None = None,
) -> None:
    conn.execute(
        "INSERT INTO machine_polls (machine_code, at, source, ok, response_ms, state, error_kind,"
        " error, machine_says, tested_by) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (
            machine,
            at,
            "poll" if tested_by is None else "test",
            result.ok,
            result.response_ms,
            result.state,
            result.error_kind,
            result.error,
            result.machine_says,
            tested_by,
        ),
    )


def prune(conn: psycopg.Connection, now: datetime, cfg: ConnectivityConfig) -> None:
    conn.execute(
        "DELETE FROM machine_polls WHERE at < %s", (now - timedelta(minutes=cfg.keep_minutes),)
    )


def poll_round(
    conn: psycopg.Connection,
    adapters: dict[str, Adapter],
    now: datetime,
    cfg: ConnectivityConfig,
    pool: ThreadPoolExecutor,
) -> list[str]:
    """Ask every machine at once, record each answer, delete old rows. Each machine and the pruning
    are separate: one failing never stops the others (as the watcher learnt, DEFECT_LOG #97).
    Returns the machines whose result could not be recorded."""
    results = dict(zip(adapters, pool.map(probe, adapters.values()), strict=True))
    failed = []
    for code, result in results.items():
        try:
            with conn.transaction():
                record(conn, code, result, now)
        except Exception:  # keep recording the others
            log.exception("recording the poll of %s failed", code)
            failed.append(code)
    try:
        with conn.transaction():
            prune(conn, now, cfg)
    except Exception:  # old rows can wait for the next round
        log.exception("deleting old polls failed")
    return failed


# --- Reading what was recorded ------------------------------------------------------------------


@dataclass(frozen=True)
class HistoryItem:
    at: datetime
    source: str
    ok: bool
    response_ms: int
    slow: bool


@dataclass(frozen=True)
class Summary:
    state: ConnectionState
    last_ok_at: datetime | None
    last_response_ms: int | None  # of the latest answered poll
    last_error: str  # what Brimline saw at the latest failed poll ("" if none in the window)
    last_error_at: datetime | None
    answered: int  # uptime: answered polls / polls taken in the last `uptime_minutes`
    taken: int
    fault: str  # a machine fault, apart from the connection ("" if none)
    machine_says: str  # the machine's own text with that fault: untrusted
    history: list[HistoryItem]  # newest first


def summarize(
    conn: psycopg.Connection, codes: Sequence[str], now: datetime, cfg: ConnectivityConfig
) -> dict[str, Summary]:
    """Each machine's connection from its recorded polls. Counted in SQL, so a page that refreshes
    every few seconds reads a few rows per machine, not an hour of polls."""
    kept = now - timedelta(minutes=cfg.keep_minutes)
    recent: dict[str, list[tuple[datetime, str, bool, int, str | None, str]]] = {
        c: [] for c in codes
    }
    for code, at, source, ok, ms, state, says in conn.execute(
        "SELECT machine_code, at, source, ok, response_ms, state, machine_says FROM ("
        "  SELECT *, row_number() OVER (PARTITION BY machine_code ORDER BY at DESC, id DESC) AS n"
        "  FROM machine_polls WHERE at > %s AND at <= %s) p"
        " WHERE n <= %s ORDER BY machine_code, at DESC, id DESC",
        (kept, now, cfg.history_polls),
    ).fetchall():
        if code in recent:
            recent[code].append((at, source, ok, ms, state, says))
    counts = {
        code: (int(answered), int(taken))
        for code, answered, taken in conn.execute(
            "SELECT machine_code, count(*) FILTER (WHERE ok), count(*) FROM machine_polls"
            " WHERE at > %s AND at <= %s GROUP BY machine_code",
            (now - timedelta(minutes=cfg.uptime_minutes), now),
        ).fetchall()
    }
    last_ok = {
        code: (at, ms)
        for code, at, ms in conn.execute(
            "SELECT DISTINCT ON (machine_code) machine_code, at, response_ms FROM machine_polls"
            " WHERE ok AND at > %s AND at <= %s ORDER BY machine_code, at DESC, id DESC",
            (kept, now),
        ).fetchall()
    }
    last_error = {
        code: (at, f"{kind}: {error}" if error else str(kind))
        for code, at, kind, error in conn.execute(
            "SELECT DISTINCT ON (machine_code) machine_code, at, error_kind, error FROM machine_polls"
            " WHERE NOT ok AND at > %s AND at <= %s ORDER BY machine_code, at DESC, id DESC",
            (kept, now),
        ).fetchall()
    }
    out = {}
    for code in codes:
        rows = recent[code]
        fault, says = _fault(conn, code, rows)
        out[code] = Summary(
            state=derive_state([Poll(r[0], r[2], r[3]) for r in rows], now, cfg),
            last_ok_at=last_ok.get(code, (None, None))[0],
            last_response_ms=last_ok.get(code, (None, None))[1],
            last_error=last_error.get(code, (None, ""))[1],
            last_error_at=last_error.get(code, (None, ""))[0],
            answered=counts.get(code, (0, 0))[0],
            taken=counts.get(code, (0, 0))[1],
            fault=fault,
            machine_says=says,
            history=[
                HistoryItem(r[0], r[1], r[2], r[3], r[2] and is_slow(r[3], cfg)) for r in rows
            ],
        )
    return out


def _fault(
    conn: psycopg.Connection,
    code: str,
    rows: list[tuple[datetime, str, bool, int, str | None, str]],
) -> tuple[str, str]:
    """A fault of the machine itself, whatever the connection: the latest answer reports a failed or
    offline state, or the latest start sent through dispatch was refused by the machine. A refused
    start stays shown until a start succeeds: it is what happened last, and someone should look."""
    answered = [r for r in rows if r[2]]
    if answered and answered[0][4] in ("failed", "offline"):
        return f"The machine reports it is {answered[0][4]}.", answered[0][5]
    row = conn.execute(
        "SELECT verdict, result FROM dispatch_calls WHERE tool = 'start_task'"
        " AND args->>'machine' = %s AND verdict IN ('allowed', 'machine_refused')"
        " ORDER BY id DESC LIMIT 1",
        (code,),
    ).fetchone()
    if row is not None and row[0] == "machine_refused":
        detail = plain_text(str((row[1] or {}).get("detail", "")), 300)
        return "The last start sent to it was refused.", detail
    return "", ""


def run_loop(stop: threading.Event, interval: float, round_once: Callable[[], object]) -> None:
    """Poll now, then every `interval` seconds until stopped. A failing round is logged and the
    next one runs as usual."""
    while True:
        try:
            round_once()
        except Exception:  # the loop outlives any one round
            log.exception("connectivity round failed")
        if stop.wait(interval):
            return
