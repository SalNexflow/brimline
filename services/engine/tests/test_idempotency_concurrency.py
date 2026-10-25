"""Two requests with the same key at the same moment must produce exactly one order and one
audit row. Two tests: one forces the overlap deterministically, one races many real requests."""

import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient

from brimline_engine import audit, idempotency, orders
from brimline_engine.permissions import Actor
from tests.conftest import login
from tests.test_orders_api import VALID_ORDER, audit_count, order_count

STAFF_CODE = "U-STAFF"


def _staff_actor(owner_url: str) -> Actor:
    with psycopg.connect(owner_url) as conn:
        row = conn.execute("SELECT id FROM users WHERE code = %s", (STAFF_CODE,)).fetchone()
    assert row is not None
    return Actor(user_id=int(row[0]), role="staff", customer_id=None)


def test_second_request_waits_for_the_first_then_replays_it(
    test_database: str, owner_url: str, app_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    actor = _staff_actor(owner_url)
    body = orders.OrderCreate.model_validate(VALID_ORDER)
    key = f"test-{uuid.uuid4()}"
    today = date(2026, 10, 26)

    first_is_inside = threading.Event()
    release_first = threading.Event()
    real_record = audit.record

    def slow_record(*args: Any, **kwargs: Any) -> None:
        # Pause the first request after it claimed the key and wrote its order, before commit.
        first_is_inside.set()
        assert release_first.wait(timeout=10)
        real_record(*args, **kwargs)

    monkeypatch.setattr(audit, "record", slow_record)
    results: dict[str, tuple[idempotency.StoredResponse, bool]] = {}
    waited: dict[str, float] = {}

    def run(name: str) -> None:
        started = time.monotonic()
        with psycopg.connect(app_url, autocommit=True) as conn:
            results[name] = orders.create_order(conn, actor, body, key, today)
        waited[name] = time.monotonic() - started

    first = threading.Thread(target=run, args=("first",))
    first.start()
    assert first_is_inside.wait(timeout=10)
    second = threading.Thread(target=run, args=("second",))
    second.start()
    time.sleep(0.5)  # the second request is now blocked on the key's primary key
    assert second.is_alive(), "second request should be waiting for the first to commit"
    release_first.set()
    first.join(timeout=10)
    second.join(timeout=10)

    first_response, first_replayed = results["first"]
    second_response, second_replayed = results["second"]
    assert (first_replayed, second_replayed) == (False, True)
    assert second_response == first_response
    assert waited["second"] >= 0.4
    number = first_response.body["order_number"]
    assert audit_count(owner_url, number) == 1


def test_many_simultaneous_requests_with_one_key_create_one_order(
    client: TestClient, owner_url: str
) -> None:
    headers = {**login(client, STAFF_CODE), "Idempotency-Key": f"test-{uuid.uuid4()}"}
    before = order_count(owner_url)
    start = threading.Barrier(8)

    def send(_: int) -> Any:
        start.wait()
        return client.post("/orders", json=VALID_ORDER, headers=headers)

    with ThreadPoolExecutor(max_workers=8) as pool:
        responses = list(pool.map(send, range(8)))

    assert [r.status_code for r in responses] == [201] * 8
    assert len({r.json()["order_number"] for r in responses}) == 1
    assert sum("Idempotent-Replayed" not in r.headers for r in responses) == 1
    assert order_count(owner_url) == before + 1
    assert audit_count(owner_url, responses[0].json()["order_number"]) == 1


def test_the_same_key_on_two_endpoints_is_two_separate_keys(
    test_database: str, owner_url: str
) -> None:
    actor = _staff_actor(owner_url)
    key = f"test-{uuid.uuid4()}"
    with psycopg.connect(owner_url) as conn:
        for endpoint in ("POST /a", "POST /b"):
            claimed = idempotency.claim(
                conn, user_id=actor.user_id, endpoint=endpoint, key=key, req_hash="h"
            )
            assert claimed is None  # each endpoint's first use owns its own key
        conn.rollback()  # leave nothing behind
