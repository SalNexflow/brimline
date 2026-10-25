"""Orders over HTTP: who sees what, and what a write leaves behind.

Seeded data (config/shop.toml): BL-0001 and BL-0002 belong to C-HARBOR (user U-HARBOR),
BL-0003 belongs to C-WILLOW (user U-WILLOW). Orders created here are committed, so tests
compare counts before and after instead of assuming absolute numbers.
"""

import uuid
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient

from tests.conftest import login

# The engine's fixed clock is 2026-10-26 10:00 in the shop, so this is a valid due date.
VALID_ORDER: dict[str, Any] = {
    "customer_code": "C-HARBOR",
    "due_date": "2026-11-06",
    "rush": False,
    "notes": "Matte finish if possible.",
    "lines": [{"part_name": "Phone stand", "quantity": 20, "material_code": "PETG-BLACK"}],
}


def new_key() -> str:
    return f"test-{uuid.uuid4()}"


def post_order(client: TestClient, user: str, body: dict[str, Any], key: str | None = None) -> Any:
    headers = login(client, user)
    headers["Idempotency-Key"] = key or new_key()
    return client.post("/orders", json=body, headers=headers)


def count(owner_url: str, query: str, *params: object) -> int:
    with psycopg.connect(owner_url) as conn:
        row = conn.execute(query.encode(), params).fetchone()
        assert row is not None
        return int(row[0])


def order_count(owner_url: str) -> int:
    return count(owner_url, "SELECT count(*) FROM orders")


def audit_count(owner_url: str, order_number: str) -> int:
    return count(
        owner_url,
        "SELECT count(*) FROM audit_log WHERE entity_type = 'order' AND entity_id = %s",
        order_number,
    )


# --- Reading: lists and details are scoped ---------------------------------------------------


@pytest.mark.parametrize("user", ["U-STAFF", "U-PLANNER", "U-OPERATOR"])
def test_shop_roles_see_every_customers_orders(client: TestClient, user: str) -> None:
    numbers = {o["order_number"] for o in client.get("/orders", headers=login(client, user)).json()}
    assert {"BL-0001", "BL-0002", "BL-0003"} <= numbers


def test_a_customer_sees_only_their_own_orders(client: TestClient) -> None:
    harbor = client.get("/orders", headers=login(client, "U-HARBOR")).json()
    willow = client.get("/orders", headers=login(client, "U-WILLOW")).json()
    assert {o["customer_code"] for o in harbor} == {"C-HARBOR"}
    assert {o["customer_code"] for o in willow} == {"C-WILLOW"}
    assert "BL-0003" not in {o["order_number"] for o in harbor}


def test_another_customers_order_looks_like_it_does_not_exist(client: TestClient) -> None:
    headers = login(client, "U-HARBOR")
    other = client.get("/orders/BL-0003", headers=headers)
    missing = client.get("/orders/BL-9999", headers=headers)
    assert other.status_code == missing.status_code == 404
    assert other.json() == missing.json()  # same body: nothing reveals that BL-0003 exists


def test_order_detail_lists_its_jobs(client: TestClient) -> None:
    detail = client.get("/orders/BL-0001", headers=login(client, "U-HARBOR")).json()
    assert detail["customer_name"] == "Harbor Lane Robotics Club"
    assert [(j["part_name"], j["quantity"], j["material_code"]) for j in detail["lines"]] == [
        ("Robot chassis plate", 4, "PETG-BLACK"),
        ("Wheel hub", 8, "PLA-BLACK"),
    ]


@pytest.mark.parametrize(
    ("user", "expected"),
    [("U-STAFF", True), ("U-PLANNER", True), ("U-OPERATOR", False), ("U-HARBOR", False)],
)
def test_who_is_told_they_can_view_history(client: TestClient, user: str, expected: bool) -> None:
    detail = client.get("/orders/BL-0001", headers=login(client, user)).json()
    assert detail["can_view_history"] is expected


@pytest.mark.parametrize(
    ("user", "order", "status"),
    [
        ("U-STAFF", "BL-0001", 200),
        ("U-PLANNER", "BL-0001", 200),
        ("U-OPERATOR", "BL-0001", 403),
        ("U-HARBOR", "BL-0001", 403),  # their own order: they know it exists, but no history
        ("U-HARBOR", "BL-0003", 404),  # someone else's: not even its existence
    ],
)
def test_history_access(client: TestClient, user: str, order: str, status: int) -> None:
    response = client.get(f"/orders/{order}/history", headers=login(client, user))
    assert response.status_code == status


# --- Writing: permissions ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("user", "customer_code", "status"),
    [
        ("U-STAFF", "C-WILLOW", 201),
        ("U-HARBOR", "C-HARBOR", 201),  # a customer, for themselves
        ("U-HARBOR", "C-WILLOW", 403),  # a customer, for someone else
        ("U-HARBOR", "C-NOBODY", 403),  # unknown code: customers learn nothing about codes
        ("U-STAFF", "C-NOBODY", 422),  # staff may list customers, so they get the real reason
        ("U-PLANNER", "C-HARBOR", 403),
        ("U-OPERATOR", "C-HARBOR", 403),
    ],
)
def test_who_may_create_orders_for_whom(
    client: TestClient, owner_url: str, user: str, customer_code: str, status: int
) -> None:
    before = order_count(owner_url)
    response = post_order(client, user, {**VALID_ORDER, "customer_code": customer_code})
    assert response.status_code == status, response.text
    assert order_count(owner_url) == before + (1 if status == 201 else 0)


# --- Writing: validation (code decides dates and references) ----------------------------------


@pytest.mark.parametrize(
    ("change", "fragment"),
    [
        ({"due_date": "2026-10-25"}, "before today (2026-10-26)"),
        ({"lines": [{"part_name": "X", "quantity": 1, "material_code": "GOLD"}]}, "GOLD"),
    ],
)
def test_business_rules_reject_bad_orders(
    client: TestClient, change: dict[str, Any], fragment: str
) -> None:
    response = post_order(client, "U-STAFF", {**VALID_ORDER, **change})
    assert response.status_code == 422
    assert fragment in response.json()["detail"]


def test_an_order_due_today_is_accepted(client: TestClient) -> None:
    assert (
        post_order(client, "U-STAFF", {**VALID_ORDER, "due_date": "2026-10-26"}).status_code == 201
    )


@pytest.mark.parametrize(
    "change",
    [
        {"lines": []},
        {"lines": [{"part_name": "X", "quantity": 0, "material_code": "PLA-BLACK"}]},
        {"price_cents": 1},  # unknown fields are refused: a client cannot sneak in a price
        {"due_date": "next friday"},
    ],
)
def test_malformed_bodies_are_rejected(client: TestClient, change: dict[str, Any]) -> None:
    assert post_order(client, "U-STAFF", {**VALID_ORDER, **change}).status_code == 422


# --- Writing: the audit row --------------------------------------------------------------------


def test_creating_an_order_writes_one_complete_audit_row(
    client: TestClient, owner_url: str
) -> None:
    key = new_key()
    created = post_order(client, "U-STAFF", VALID_ORDER, key).json()
    number = created["order_number"]

    with psycopg.connect(owner_url) as conn:
        rows = conn.execute(
            "SELECT u.code, a.action, a.entity_type, a.entity_id, a.before, a.after, a.idempotency_key"
            " FROM audit_log a JOIN users u ON u.id = a.actor_user_id"
            " WHERE a.entity_type = 'order' AND a.entity_id = %s",
            (number,),
        ).fetchall()
    assert len(rows) == 1
    actor, action, entity_type, entity_id, before, after, audit_key = rows[0]
    assert (actor, action, entity_type, entity_id) == ("U-STAFF", "order.create", "order", number)
    assert before is None
    assert after["customer_code"] == "C-HARBOR"
    assert after["lines"][0]["part_name"] == "Phone stand"
    assert audit_key == key

    history = client.get(f"/orders/{number}/history", headers=login(client, "U-STAFF")).json()
    assert [(h["actor_name"], h["action"], h["idempotency_key"]) for h in history] == [
        ("Sam Ortega", "order.create", key)
    ]


# --- Writing: idempotency ----------------------------------------------------------------------


def test_replaying_a_request_returns_the_first_response_and_writes_nothing(
    client: TestClient, owner_url: str
) -> None:
    key = new_key()
    first = post_order(client, "U-STAFF", VALID_ORDER, key)
    orders_after_first = order_count(owner_url)
    second = post_order(client, "U-STAFF", VALID_ORDER, key)

    assert first.status_code == second.status_code == 201
    assert second.json() == first.json()
    assert second.headers["Idempotent-Replayed"] == "true"
    assert "Idempotent-Replayed" not in first.headers
    assert order_count(owner_url) == orders_after_first
    assert audit_count(owner_url, first.json()["order_number"]) == 1


def test_reusing_a_key_with_a_different_body_is_a_conflict(
    client: TestClient, owner_url: str
) -> None:
    key = new_key()
    assert post_order(client, "U-STAFF", VALID_ORDER, key).status_code == 201
    before = order_count(owner_url)
    changed = {**VALID_ORDER, "notes": "Actually, glossy."}
    assert post_order(client, "U-STAFF", changed, key).status_code == 409
    assert order_count(owner_url) == before


def test_two_users_with_the_same_key_do_not_share_responses(
    client: TestClient, owner_url: str
) -> None:
    key = new_key()
    staff = post_order(client, "U-STAFF", {**VALID_ORDER, "customer_code": "C-WILLOW"}, key)
    customer = post_order(client, "U-HARBOR", VALID_ORDER, key)

    assert staff.status_code == customer.status_code == 201
    assert staff.json()["order_number"] != customer.json()["order_number"]
    assert customer.json()["customer_code"] == "C-HARBOR"  # not the staff user's Willow order
    assert "Idempotent-Replayed" not in customer.headers


def test_a_failed_request_does_not_use_up_its_key(client: TestClient) -> None:
    key = new_key()
    rejected = post_order(client, "U-STAFF", {**VALID_ORDER, "due_date": "2026-01-01"}, key)
    assert rejected.status_code == 422
    # The failed attempt rolled back, so the corrected request with the same key succeeds.
    assert post_order(client, "U-STAFF", VALID_ORDER, key).status_code == 201


@pytest.mark.parametrize("key", [None, "short"])
def test_a_write_without_a_usable_key_is_refused(client: TestClient, key: str | None) -> None:
    headers = login(client, "U-STAFF")
    if key is not None:
        headers["Idempotency-Key"] = key
    assert client.post("/orders", json=VALID_ORDER, headers=headers).status_code == 400


# --- Replays use today's permissions (found by the M1 adversarial review, DEFECT_LOG #8) -------


def _temp_user(owner_url: str, role: str, customer_code: str | None) -> str:
    code = f"U-TMP-{uuid.uuid4().hex[:8]}"
    with psycopg.connect(owner_url) as conn:
        conn.execute(
            "INSERT INTO users (code, display_name, role, customer_id)"
            " VALUES (%s, 'Temporary tester', %s, (SELECT id FROM customers WHERE code = %s))",
            (code, role, customer_code),
        )
    return code


def _set_user(owner_url: str, code: str, role: str, customer_code: str | None) -> None:
    with psycopg.connect(owner_url) as conn:
        conn.execute(
            "UPDATE users SET role = %s, customer_id = (SELECT id FROM customers WHERE code = %s)"
            " WHERE code = %s",
            (role, customer_code, code),
        )


def test_a_replay_after_losing_access_is_not_found(client: TestClient, owner_url: str) -> None:
    user = _temp_user(owner_url, "customer", "C-HARBOR")
    key = new_key()
    created = post_order(client, user, VALID_ORDER, key)
    assert created.status_code == 201

    _set_user(owner_url, user, "customer", "C-COPPER")  # moved to another customer
    number = created.json()["order_number"]
    assert client.get(f"/orders/{number}", headers=login(client, user)).status_code == 404
    replay = post_order(client, user, VALID_ORDER, key)
    assert replay.status_code == 404
    assert replay.json() == {"detail": "order not found"}


def test_a_replay_reflects_current_permissions(client: TestClient, owner_url: str) -> None:
    user = _temp_user(owner_url, "staff", None)
    key = new_key()
    first = post_order(client, user, VALID_ORDER, key)
    assert first.json()["can_view_history"] is True

    _set_user(owner_url, user, "operator", None)  # demoted: may read orders, not their history
    replay = post_order(client, user, VALID_ORDER, key)
    assert replay.status_code == 201
    assert replay.json()["order_number"] == first.json()["order_number"]
    assert replay.json()["can_view_history"] is False
