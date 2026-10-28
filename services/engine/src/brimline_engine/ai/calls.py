"""Storing model calls (the append-only ai_calls table), shared by every feature that calls a model."""

import psycopg

from brimline_engine.ai.gateway import CallRecord
from brimline_engine.ai.guard import REPLAYED, VISITOR


def record_call(conn: psycopg.Connection, record: CallRecord, user_id: int | None) -> int:
    u = record.usage
    row = conn.execute(
        "INSERT INTO ai_calls (purpose, mode, model, prompt_version, outcome, attempts, input_tokens,"
        " output_tokens, cache_read_tokens, cache_write_tokens, cost_micro_usd, latency_ms, error, created_by,"
        " visitor) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
        (
            record.purpose,
            # A reply replayed from the recording is recorded as such (and costs nothing).
            "replay" if REPLAYED.get() else record.mode,
            record.model,
            record.prompt_version,
            record.outcome,
            record.attempts,
            u.input_tokens,
            u.output_tokens,
            u.cache_read_tokens,
            u.cache_write_tokens,
            record.cost_micro_usd,
            record.latency_ms,
            record.error,
            user_id,
            VISITOR.get(),
        ),
    ).fetchone()
    assert row is not None
    return int(row[0])
