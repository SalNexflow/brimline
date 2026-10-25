"""Price rules are dated, versioned, and never change once written."""

import uuid
from datetime import date
from typing import Any, LiteralString

import psycopg
import pytest
from fastapi.testclient import TestClient

from brimline_engine.price_rules import load_rules
from tests.conftest import login

# The seeded version, copied by hand from config/shop.toml (not read from it).
SEEDED_MATERIALS = {
    "PLA-BLACK": 3,
    "PLA-WHITE": 3,
    "PETG-BLACK": 4,
    "PETG-ORANGE": 4,
    "TPU-BLACK": 7,
    "RESIN-GREY": 12,
    "RESIN-CLEAR": 16,
    "AL-6061": 2,
}


def new_version(effective_from: str, **changes: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "effective_from": effective_from,
        "setup_cents": 1800,
        "rush_multiplier_percent": 160,
        "material_cents_per_gram": dict(SEEDED_MATERIALS),
        "machine_cents_per_minute": {"fdm": 7, "resin": 10, "cnc": 50},
        "post_process_cents_per_part": {"sanding": 250, "painting": 400, "assembly": 600},
        "note": "Winter prices",
    }
    body.update(changes)
    return body


def post_version(
    client: TestClient, user: str, body: dict[str, Any], key: str | None = None
) -> Any:
    headers = {**login(client, user), "Idempotency-Key": key or f"test-{uuid.uuid4()}"}
    return client.post("/price-rules", json=body, headers=headers)


def test_the_seeded_version_is_in_effect(owner_conn: psycopg.Connection) -> None:
    rules = load_rules(owner_conn, date(2026, 10, 26))
    assert rules is not None
    assert rules.effective_from == date(2026, 10, 25)
    assert (rules.setup_cents, rules.rush_multiplier_percent) == (1500, 150)
    assert dict(rules.material_cents_per_gram) == SEEDED_MATERIALS
    assert dict(rules.machine_cents_per_minute) == {"cnc": 45, "fdm": 6, "resin": 9}
    assert dict(rules.post_process_cents_per_part) == {
        "assembly": 500,
        "painting": 350,
        "sanding": 200,
    }


def test_no_rules_before_the_first_version(owner_conn: psycopg.Connection) -> None:
    assert load_rules(owner_conn, date(2026, 10, 24)) is None


def test_a_new_version_applies_from_its_effective_date_only(
    client: TestClient, owner_url: str
) -> None:
    created = post_version(client, "U-STAFF", new_version("2031-03-01"))
    assert created.status_code == 201, created.text
    with psycopg.connect(owner_url) as conn:
        before = load_rules(conn, date(2031, 2, 28))
        on = load_rules(conn, date(2031, 3, 1))
    assert before is not None and on is not None
    assert before.rule_set_id != created.json()["id"]
    assert on.rule_set_id == created.json()["id"]
    assert on.setup_cents == 1800


@pytest.mark.parametrize(
    ("user", "read", "write"),
    [
        ("U-STAFF", 200, 201),
        ("U-PLANNER", 200, 403),
        ("U-OPERATOR", 403, 403),
        ("U-HARBOR", 403, 403),
    ],
)
def test_who_may_read_and_write_prices(
    client: TestClient, user: str, read: int, write: int
) -> None:
    assert client.get("/price-rules", headers=login(client, user)).status_code == read
    assert post_version(client, user, new_version("2032-01-01")).status_code == write


@pytest.mark.parametrize(
    ("body", "fragment"),
    [
        (new_version("2026-10-25"), "cannot be backdated"),  # the fixed clock says 2026-10-26
        (
            new_version("2033-01-01", material_cents_per_gram={"PLA-BLACK": 3}),
            "every material needs a price",
        ),
        (
            new_version("2033-01-01", machine_cents_per_minute={"fdm": 7}),
            "every process needs a price",
        ),
    ],
)
def test_incomplete_or_backdated_versions_are_refused(
    client: TestClient, body: dict[str, Any], fragment: str
) -> None:
    response = post_version(client, "U-STAFF", body)
    assert response.status_code == 422
    assert fragment in response.json()["detail"]


def test_creating_a_version_is_idempotent_and_audited(client: TestClient, owner_url: str) -> None:
    key = f"test-{uuid.uuid4()}"
    first = post_version(client, "U-STAFF", new_version("2034-01-01"), key)
    second = post_version(client, "U-STAFF", new_version("2034-01-01"), key)
    assert first.status_code == second.status_code == 201
    assert second.json() == first.json()
    assert second.headers["Idempotent-Replayed"] == "true"
    with psycopg.connect(owner_url) as conn:
        rows = conn.execute(
            "SELECT action, idempotency_key FROM audit_log WHERE entity_type = 'price_rule_set'"
            " AND entity_id = %s",
            (str(first.json()["id"]),),
        ).fetchall()
    assert rows == [("price_rules.create", key)]


# --- Immutability, in the database -------------------------------------------------------------

CHANGES: list[LiteralString] = [
    "UPDATE price_rule_sets SET setup_cents = 0",
    "DELETE FROM price_rule_sets",
    "UPDATE price_material_rates SET cents_per_gram = 0",
    "DELETE FROM price_machine_rates",
    "TRUNCATE price_post_process_rates",
]


@pytest.mark.parametrize("statement", CHANGES)
def test_versions_cannot_change_even_for_the_owner(
    owner_conn: psycopg.Connection, statement: LiteralString
) -> None:
    with pytest.raises(psycopg.errors.RaiseException, match="price rules are versioned"):
        owner_conn.execute(statement)


@pytest.mark.parametrize("statement", CHANGES)
def test_the_app_role_has_no_right_to_change_versions(
    app_conn: psycopg.Connection, statement: LiteralString
) -> None:
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        app_conn.execute(statement)


def test_rates_cannot_be_added_to_an_existing_version(app_conn: psycopg.Connection) -> None:
    # Adding a rate later would quietly change what an old version charges.
    with pytest.raises(
        psycopg.errors.RaiseException, match="transaction that created their version"
    ):
        app_conn.execute(
            "INSERT INTO price_post_process_rates (rule_set_id, kind, cents_per_part)"
            " SELECT min(id), 'assembly', 1 FROM price_rule_sets"
        )
