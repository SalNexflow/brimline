"""Writes to the append-only audit log. Call inside the same transaction as the change it
records, so the change and its audit row are committed together or not at all."""

from typing import Any

import psycopg
from psycopg.types.json import Jsonb


def record(
    conn: psycopg.Connection,
    *,
    actor_user_id: int | None,
    action: str,
    entity_type: str,
    entity_id: str,
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
    idempotency_key: str | None,
) -> None:
    conn.execute(
        "INSERT INTO audit_log (actor_user_id, action, entity_type, entity_id, before, after, idempotency_key)"
        " VALUES (%s, %s, %s, %s, %s, %s, %s)",
        (
            actor_user_id,
            action,
            entity_type,
            entity_id,
            None if before is None else Jsonb(before),
            None if after is None else Jsonb(after),
            idempotency_key,
        ),
    )
