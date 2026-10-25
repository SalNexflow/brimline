"""Idempotent writes, keyed by (user, endpoint, client key). See db/migrations/0003.

Use inside one transaction:
    stored = claim(...)            # None: this request owns the key, go ahead and write
    if stored: return stored       # a replay: return exactly what the first request returned
    ... do the write ...
    store(...)                     # save the response before the transaction commits

If the write fails, the transaction rolls back and the claim disappears with it, so a retry
can succeed. A concurrent request with the same key waits on the primary key until the first
commits, then replays its stored response.
"""

import hashlib
import json
from dataclasses import dataclass
from typing import Any

import psycopg
from psycopg.types.json import Jsonb


class IdempotencyConflictError(Exception):
    """The key was already used by this user on this endpoint with a different request."""


@dataclass(frozen=True)
class StoredResponse:
    status: int
    body: dict[str, Any]


def request_hash(body: dict[str, Any]) -> str:
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


def claim(
    conn: psycopg.Connection, *, user_id: int, endpoint: str, key: str, req_hash: str
) -> StoredResponse | None:
    inserted = conn.execute(
        "INSERT INTO idempotency_keys (user_id, endpoint, key, request_hash) VALUES (%s, %s, %s, %s)"
        " ON CONFLICT DO NOTHING RETURNING 1",
        (user_id, endpoint, key, req_hash),
    ).fetchone()
    if inserted:
        return None

    row = conn.execute(
        "SELECT request_hash, response_status, response_body FROM idempotency_keys"
        " WHERE user_id = %s AND endpoint = %s AND key = %s",
        (user_id, endpoint, key),
    ).fetchone()
    assert row is not None, "conflicting key row must exist after ON CONFLICT"
    stored_hash, status, body = row
    if stored_hash != req_hash:
        raise IdempotencyConflictError(key)
    # The first request stores its response before committing, so a visible row is complete.
    assert status is not None and body is not None
    return StoredResponse(status=int(status), body=body)


def store(
    conn: psycopg.Connection, *, user_id: int, endpoint: str, key: str, response: StoredResponse
) -> None:
    conn.execute(
        "UPDATE idempotency_keys SET response_status = %s, response_body = %s"
        " WHERE user_id = %s AND endpoint = %s AND key = %s",
        (response.status, Jsonb(response.body), user_id, endpoint, key),
    )
