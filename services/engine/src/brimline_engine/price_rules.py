"""Dated price-rule versions: load the one in effect on a date, list them, add a new one.

Versions are insert-only (db/migrations/0005): a change is a new version with an effective date.
"""

from datetime import date, datetime
from typing import Literal

import psycopg
from pydantic import BaseModel, ConfigDict, Field

from brimline_engine import audit, idempotency
from brimline_engine.permissions import Actor, can
from brimline_engine.pricing import PriceRules

CREATE_ENDPOINT = "POST /price-rules"

Process = Literal["fdm", "resin", "cnc"]
PostProcess = Literal["sanding", "painting", "assembly"]
PROCESSES: tuple[Process, ...] = ("fdm", "resin", "cnc")
POST_PROCESSES: tuple[PostProcess, ...] = ("sanding", "painting", "assembly")


class ForbiddenError(Exception):
    pass


class InvalidRulesError(Exception):
    pass


Cents = Field(ge=0, le=10_000_000)


class PriceRulesIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    effective_from: date
    setup_cents: int = Cents
    rush_multiplier_percent: int = Field(ge=100, le=500)
    material_cents_per_gram: dict[str, int]
    machine_cents_per_minute: dict[Process, int]
    post_process_cents_per_part: dict[PostProcess, int]
    note: str = Field(default="", max_length=500)


class PriceRulesOut(PriceRulesIn):
    id: int
    created_at: datetime
    created_by_name: str | None


def _rates(
    conn: psycopg.Connection, rule_set_id: int
) -> tuple[dict[str, int], dict[str, int], dict[str, int]]:
    materials = {
        code: cents
        for code, cents in conn.execute(
            "SELECT m.code, r.cents_per_gram FROM price_material_rates r"
            " JOIN materials m ON m.id = r.material_id WHERE r.rule_set_id = %s ORDER BY m.id",
            (rule_set_id,),
        )
    }
    machines = {
        p: c
        for p, c in conn.execute(
            "SELECT process, cents_per_minute FROM price_machine_rates WHERE rule_set_id = %s ORDER BY process",
            (rule_set_id,),
        )
    }
    post = {
        k: c
        for k, c in conn.execute(
            "SELECT kind, cents_per_part FROM price_post_process_rates WHERE rule_set_id = %s ORDER BY kind",
            (rule_set_id,),
        )
    }
    return materials, machines, post


def load_rules(conn: psycopg.Connection, on: date) -> PriceRules | None:
    """The version in effect on `on`: the latest effective_from not after it (newest id wins)."""
    row = conn.execute(
        "SELECT id, effective_from, setup_cents, rush_multiplier_percent FROM price_rule_sets"
        " WHERE effective_from <= %s ORDER BY effective_from DESC, id DESC LIMIT 1",
        (on,),
    ).fetchone()
    if row is None:
        return None
    materials, machines, post = _rates(conn, row[0])
    return PriceRules(
        rule_set_id=row[0],
        effective_from=row[1],
        setup_cents=row[2],
        rush_multiplier_percent=row[3],
        material_cents_per_gram=materials,
        machine_cents_per_minute=machines,
        post_process_cents_per_part=post,
    )


def _version(conn: psycopg.Connection, rule_set_id: int) -> PriceRulesOut:
    row = conn.execute(
        "SELECT s.id, s.effective_from, s.setup_cents, s.rush_multiplier_percent, s.note,"
        "       s.created_at, u.display_name"
        " FROM price_rule_sets s LEFT JOIN users u ON u.id = s.created_by WHERE s.id = %s",
        (rule_set_id,),
    ).fetchone()
    assert row is not None
    materials, machines, post = _rates(conn, rule_set_id)
    return PriceRulesOut.model_validate(
        {
            "id": row[0],
            "effective_from": row[1],
            "setup_cents": row[2],
            "rush_multiplier_percent": row[3],
            "note": row[4],
            "created_at": row[5],
            "created_by_name": row[6],
            "material_cents_per_gram": materials,
            "machine_cents_per_minute": machines,
            "post_process_cents_per_part": post,
        }
    )


def list_versions(conn: psycopg.Connection, actor: Actor) -> list[PriceRulesOut]:
    if not can(actor, "price_rules.read"):
        raise ForbiddenError("price_rules.read")
    ids = [
        r[0]
        for r in conn.execute(
            "SELECT id FROM price_rule_sets ORDER BY effective_from DESC, id DESC"
        )
    ]
    return [_version(conn, i) for i in ids]


def create_version(
    conn: psycopg.Connection, actor: Actor, body: PriceRulesIn, key: str, today: date
) -> tuple[idempotency.StoredResponse, bool]:
    req_hash = idempotency.request_hash(body.model_dump(mode="json"))
    with conn.transaction():
        stored = idempotency.claim(
            conn, user_id=actor.user_id, endpoint=CREATE_ENDPOINT, key=key, req_hash=req_hash
        )
        if not can(actor, "price_rules.write"):
            raise ForbiddenError("price_rules.write")
        if stored is not None:
            return idempotency.StoredResponse(
                stored.status, _version(conn, stored.body["id"]).model_dump(mode="json")
            ), True

        if body.effective_from < today:
            raise InvalidRulesError(
                f"effective_from {body.effective_from} is in the past; prices cannot be backdated"
            )
        materials = {code: mid for code, mid in conn.execute("SELECT code, id FROM materials")}
        unknown = sorted(set(body.material_cents_per_gram) - set(materials))
        unpriced = sorted(set(materials) - set(body.material_cents_per_gram))
        if unknown or unpriced:
            raise InvalidRulesError(
                f"every material needs a price; unknown: {unknown}, missing: {unpriced}"
            )
        for label, given, needed in (
            ("process", body.machine_cents_per_minute, PROCESSES),
            ("post-processing", body.post_process_cents_per_part, POST_PROCESSES),
        ):
            missing = [k for k in needed if k not in given]
            if missing:
                raise InvalidRulesError(f"every {label} needs a price; missing: {missing}")
        if any(
            not 0 <= v <= 10_000_000
            for v in (
                *body.material_cents_per_gram.values(),
                *body.machine_cents_per_minute.values(),
                *body.post_process_cents_per_part.values(),
            )
        ):
            raise InvalidRulesError("rates must be between 0 and 10,000,000 cents")

        row = conn.execute(
            "INSERT INTO price_rule_sets (effective_from, setup_cents, rush_multiplier_percent, note, created_by)"
            " VALUES (%s, %s, %s, %s, %s) RETURNING id",
            (
                body.effective_from,
                body.setup_cents,
                body.rush_multiplier_percent,
                body.note,
                actor.user_id,
            ),
        ).fetchone()
        assert row is not None
        rule_set_id = int(row[0])
        for code, cents in body.material_cents_per_gram.items():
            conn.execute(
                "INSERT INTO price_material_rates (rule_set_id, material_id, cents_per_gram) VALUES (%s, %s, %s)",
                (rule_set_id, materials[code], cents),
            )
        for process, cents in body.machine_cents_per_minute.items():
            conn.execute(
                "INSERT INTO price_machine_rates (rule_set_id, process, cents_per_minute) VALUES (%s, %s, %s)",
                (rule_set_id, process, cents),
            )
        for kind, cents in body.post_process_cents_per_part.items():
            conn.execute(
                "INSERT INTO price_post_process_rates (rule_set_id, kind, cents_per_part) VALUES (%s, %s, %s)",
                (rule_set_id, kind, cents),
            )

        out = _version(conn, rule_set_id).model_dump(mode="json")
        audit.record(
            conn,
            actor_user_id=actor.user_id,
            action="price_rules.create",
            entity_type="price_rule_set",
            entity_id=str(rule_set_id),
            before=None,
            after=out,
            idempotency_key=key,
        )
        response = idempotency.StoredResponse(status=201, body=out)
        idempotency.store(
            conn, user_id=actor.user_id, endpoint=CREATE_ENDPOINT, key=key, response=response
        )
        return response, False
