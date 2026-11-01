"""Materials through the API (M9): the seeded plan still plans fully, the TPU-BLACK shortage and
its suggestion, purchase orders, delays moving deliveries, and prints taking stock.

Worked by hand from config/shop.toml, config/scheduler.toml and config/purchasing.toml, planning
on Mon 26 Oct 2026 at 10:00 Berlin (minute 120; Thursday is [4320, 4860)):
  Bottle cage clip (BL-0005-2): 12 x 12 min, 55 g -> 660 g of TPU-BLACK; 500 g on hand; the
  recorded 1000 g delivery arrives Fri 30 Oct 10:00 (minute 5880). Due Thu 29 Oct 17:00 (4860).
  Finish 10 + 12 = 22 min -> starts by 4838; machine 15 + 144 + 20 = 179 -> needed by 4659,
  Thu 13:39. At 4659 the level is 500 - 660 = -160: short by 160 g.
  Suggestion (Quickspool Express, 2 days, 500 g packs, no safety stock): one 500 g pack; ordered
  Tue 27 it arrives Thu 29 10:00, before 13:39, so the latest day is Tue 27 Oct.
"""

from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, date, datetime
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient

from brimline_engine.db import demo_seed
from brimline_engine.db.migrate import drop_database, ensure_database, migrate, with_database
from brimline_engine.db.seed import seed
from brimline_engine.scheduling.config import scheduler_config
from brimline_engine.settings import Settings
from brimline_engine.shop_config import load_shop_config
from tests.conftest import FIXED_NOW, login
from tests.test_costing_api import replan, run
from tests.test_planning_api import (  # noqa: F401 (fixtures used by name)
    draft,
    fresh_planning_state,
    key,
    plan_day,
    tasks_of,
)

SEEDED = {f"BL-000{n}" for n in range(1, 9)}
CLIP = "BL-0005-2"


@pytest.fixture(autouse=True)
def no_disruptions(owner_url: str) -> Iterator[None]:
    yield
    with psycopg.connect(owner_url) as conn:
        conn.execute("TRUNCATE material_delays, disruptions CASCADE")


def materials(client: TestClient, user: str = "U-STAFF") -> dict[str, Any]:
    r = client.get("/stock", headers=login(client, user))
    assert r.status_code == 200, r.text
    body: dict[str, Any] = r.json()
    return body


def machine_start(plan: dict[str, Any], job: str) -> datetime:
    t = next(t for t in plan["tasks"] if t["job"] == job and t["kind"] == "machine")
    return datetime.fromisoformat(t["start"])


def stock_of(owner_url: str, code: str) -> int:
    with psycopg.connect(owner_url) as conn:
        row = conn.execute(
            "SELECT s.on_hand_g FROM stock s JOIN materials m ON m.id = s.material_id"
            " WHERE m.code = %s",
            (code,),
        ).fetchone()
    assert row is not None
    return int(row[0])


def test_every_seeded_order_still_plans_fully(client: TestClient) -> None:
    planner = login(client, "U-PLANNER")
    plan_day(client, planner)
    d = draft(client, planner)
    assert d["check"]["valid"] is True
    # Only the hilt, which has no size on purpose (as before M9); nobody misses grams.
    unplannable = {u["job"]: u["missing"] for u in d["unplannable"] if u["job"][:7] in SEEDED}
    assert unplannable == {"BL-0008-2": ["part size"]}
    assert not [j["key"] for j in d["jobs"] if j["unscheduled"] and j["order_number"] in SEEDED]
    # The clip waits for its delivery: Fri 30 Oct 10:00 Berlin = 09:00 UTC.
    assert machine_start(d, CLIP) >= datetime(2026, 10, 30, 9, 0, tzinfo=UTC)


def test_the_tpu_shortage_and_what_to_order(client: TestClient) -> None:
    plan_day(client, login(client, "U-PLANNER"))
    m = materials(client)
    (plan,) = m["plans"]
    assert plan["status"] == "draft" and plan["material_known"] is True
    tpu = next(s for s in plan["shortages"] if s["material"] == "TPU-BLACK")
    assert tpu["short_by_g"] == 160
    assert datetime.fromisoformat(tpu["short_at"]) == datetime(2026, 10, 29, 12, 39, tzinfo=UTC)
    (job,) = tpu["affected"]
    assert job["job"] == CLIP and job["grams"] == 660 and job["late_minutes"] > 0
    assert job["waits_after_order"] is False
    s = tpu["suggestion"]
    assert (s["supplier"], s["grams"], s["packs"], s["in_time"]) == (
        "Quickspool Express",
        500,
        1,
        True,
    )
    assert date.fromisoformat(s["order_by"]) == date(2026, 10, 27)
    assert datetime.fromisoformat(s["arrives_at"]) == datetime(2026, 10, 29, 9, 0, tzinfo=UTC)
    # Only TPU-BLACK is short among the seeded orders' materials.
    assert [x["material"] for x in plan["shortages"]] == ["TPU-BLACK"]
    row = next(r for r in m["stock"] if r["material"] == "TPU-BLACK")
    assert (row["on_hand_g"], row["on_order_g"]) == (500, 1000)


def test_recording_the_suggested_order_ends_the_shortage(client: TestClient) -> None:
    staff = login(client, "U-STAFF")
    body = {
        "material_code": "TPU-BLACK",
        "grams": 500,
        "supplier": "Quickspool Express",
        "expected_at": "2026-10-29T09:00:00Z",
    }
    k = key()
    r = client.post("/purchase-orders", json=body, headers=staff | k)
    assert r.status_code == 201, r.text
    again = client.post("/purchase-orders", json=body, headers=staff | k)
    assert again.status_code == 201 and again.headers["Idempotent-Replayed"] == "true"
    planner = login(client, "U-PLANNER")
    plan_day(client, planner)
    d = draft(client, planner)
    # 500 + 500 by Thu 10:00 covers the 660 g: the clip starts Thursday and is on time.
    start = machine_start(d, CLIP)
    assert (
        datetime(2026, 10, 29, 9, 0, tzinfo=UTC)
        <= start
        <= datetime(2026, 10, 29, 12, 39, tzinfo=UTC)
    )
    assert not [
        s for s in materials(client)["plans"][0]["shortages"] if s["material"] == "TPU-BLACK"
    ]


@pytest.mark.parametrize(
    ("user", "status"), [("U-PLANNER", 403), ("U-OPERATOR", 403), ("U-HARBOR", 403)]
)
def test_only_staff_record_purchase_orders(client: TestClient, user: str, status: int) -> None:
    body = {"material_code": "PLA-BLACK", "grams": 1000, "supplier": "X",
            "expected_at": "2026-11-02T09:00:00Z"}  # fmt: skip
    r = client.post("/purchase-orders", json=body, headers=login(client, user) | key())
    assert r.status_code == status


@pytest.mark.parametrize(
    ("user", "status"),
    [("U-STAFF", 200), ("U-PLANNER", 200), ("U-OPERATOR", 403), ("U-HARBOR", 403)],
)
def test_who_sees_materials(client: TestClient, user: str, status: int) -> None:
    assert client.get("/stock", headers=login(client, user)).status_code == status


def test_a_purchase_order_must_be_sensible(client: TestClient) -> None:
    staff = login(client, "U-STAFF")
    base = {"material_code": "PLA-BLACK", "grams": 1000, "supplier": "X",
            "expected_at": "2026-11-02T09:00:00Z"}  # fmt: skip
    for change, status in (
        ({"material_code": "NOPE"}, 422),
        ({"grams": 0}, 422),
        ({"expected_at": "2026-10-20T09:00:00Z"}, 422),  # in the past
        ({"expected_at": "2026-11-02T09:00:00"}, 422),  # no time zone
        ({"ordered_by_ai": True}, 422),  # unknown field
    ):
        r = client.post("/purchase-orders", json=base | change, headers=staff | key())
        assert r.status_code == status, (change, r.text)


def test_receiving_adds_to_stock_once_and_is_audited(client: TestClient, owner_url: str) -> None:
    staff = login(client, "U-STAFF")
    k = key()
    r = client.post("/purchase-orders/PO-0001/receive", headers=staff | k)
    assert r.status_code == 200, r.text
    assert stock_of(owner_url, "TPU-BLACK") == 500 + 1000
    replay = client.post("/purchase-orders/PO-0001/receive", headers=staff | k)
    assert replay.headers["Idempotent-Replayed"] == "true"
    assert client.post("/purchase-orders/PO-0001/receive", headers=staff | key()).status_code == 409
    assert stock_of(owner_url, "TPU-BLACK") == 1500
    with psycopg.connect(owner_url) as conn:
        audited = conn.execute(
            "SELECT count(*) FROM audit_log WHERE action = 'purchase_order.receive'"
            " AND entity_id = 'PO-0001'"
        ).fetchone()
        moved = conn.execute(
            "SELECT grams_delta, reason FROM stock_movements WHERE purchase_order_id IS NOT NULL"
        ).fetchall()
    assert audited == (1,) and moved == [(1000, "delivery")]
    m = materials(client)
    assert any(x["what"] == "PO-0001" and x["grams"] == 1000 for x in m["movements"])


def test_a_material_delay_moves_the_open_delivery(client: TestClient, owner_url: str) -> None:
    # TPU-BLACK late until Mon 2 Nov 10:00 Berlin (09:00 UTC), as a pending disruption: the
    # delivery moves there, so the clip starts no earlier.
    with psycopg.connect(owner_url) as conn:
        conn.execute(
            "INSERT INTO disruptions (message, received_at, events, status, created_by)"
            " SELECT '', %s, %s::jsonb, 'pending', id FROM users WHERE code = 'U-PLANNER'",
            (FIXED_NOW, '[{"type": "material_delayed", "material": "TPU-BLACK",'
                        ' "ends_at": "2026-11-02T09:00:00+00:00"}]'),
        )  # fmt: skip
    planner = login(client, "U-PLANNER")
    plan_day(client, planner)
    d = draft(client, planner)
    assert machine_start(d, CLIP) >= datetime(2026, 11, 2, 9, 0, tzinfo=UTC)
    # Other materials are not held back by it.
    assert machine_start(d, "BL-0001-2") < datetime(2026, 10, 27, 9, 0, tzinfo=UTC)


def test_a_finished_print_takes_its_grams_and_a_failed_one_what_it_recorded(
    client: TestClient, owner_url: str
) -> None:
    # Wheel hub (BL-0001-2): 8 x 25 g = 200 g of PLA-BLACK, 4000 g on hand.
    q = replan(client, FIXED_NOW)
    prep, machine, *_ = tasks_of(q, "BL-0001-2")
    for t, action in ((prep, "start"), (prep, "done"), (machine, "start")):
        assert run(client, FIXED_NOW, t["id"], action).status_code == 200
    assert run(client, FIXED_NOW, machine["id"], "fail", failure_reason="clog",
               material_used_g=30).status_code == 200  # fmt: skip
    assert stock_of(owner_url, "PLA-BLACK") == 4000 - 30
    # The reprint finishes without anyone weighing it: the job's 200 g are assumed.
    later = FIXED_NOW.replace(hour=12)
    q = replan(client, later)
    prep, machine, *_ = tasks_of(q, "BL-0001-2")
    for t, action in ((prep, "start"), (prep, "done"), (machine, "start"), (machine, "done")):
        assert run(client, later, t["id"], action).status_code == 200
    assert stock_of(owner_url, "PLA-BLACK") == 4000 - 30 - 200
    with psycopg.connect(owner_url) as conn:
        rows = conn.execute(
            "SELECT grams_delta, grams_assumed FROM stock_movements WHERE reason = 'print'"
            " ORDER BY id"
        ).fetchall()
    assert rows == [(-30, False), (-200, True)]


def test_a_print_that_uses_more_than_the_record_stops_at_zero(
    client: TestClient, owner_url: str
) -> None:
    # The record drops to 100 g after planning (someone used PLA-BLACK off the books).
    q = replan(client, FIXED_NOW)
    with psycopg.connect(owner_url) as conn:
        conn.execute(
            "UPDATE stock SET on_hand_g = 100 FROM materials m"
            " WHERE m.id = stock.material_id AND m.code = 'PLA-BLACK'"
        )
    prep, machine, *_ = tasks_of(q, "BL-0001-2")
    for t, action in ((prep, "start"), (prep, "done"), (machine, "start")):
        assert run(client, FIXED_NOW, t["id"], action).status_code == 200
    r = run(client, FIXED_NOW, machine["id"], "done", material_used_g=250)
    assert r.status_code == 200
    assert stock_of(owner_url, "PLA-BLACK") == 0
    with psycopg.connect(owner_url) as conn:
        assert conn.execute(
            "SELECT grams_delta, missing_g FROM stock_movements WHERE reason = 'print'"
        ).fetchall() == [(-100, 150)]


def test_the_demo_seed_plans_fully_on_any_day(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The hosted demo's nightly reset (M11) with M9's stock: a Wednesday and a Saturday."""
    assert settings.database_owner_url
    name = "brimline_test_demo_m9"
    owner = with_database(settings.database_owner_url, name)
    app = with_database(settings.database_url, name)
    fast = scheduler_config().model_copy(
        update={"solver": replace_solver(scheduler_config().solver, 2.0)}
    )
    monkeypatch.setattr(demo_seed, "effective_scheduler_config", lambda: fast)
    shop = load_shop_config()
    for now in (datetime(2026, 11, 11, 9, 0, tzinfo=UTC), datetime(2026, 11, 14, 9, 0, tzinfo=UTC)):
        drop_database(settings.database_owner_url, name)
        ensure_database(settings.database_owner_url, name)
        migrate(owner, app)
        seed(owner, demo_seed.shifted(shop, now.date()))
        sid = demo_seed.plan_and_approve(app, now, shop.shop.time_zone)
        with psycopg.connect(owner) as conn:
            row = conn.execute(
                "SELECT document, unplannable FROM schedules WHERE id = %s", (sid,)
            ).fetchone()
        assert row is not None
        doc, unplannable = row
        assert doc["plan"]["unscheduled"] == [], now
        assert [u["missing"] for u in unplannable] == [["part size"]], now
        assert "TPU-BLACK" in doc["instance"]["stock"]
    drop_database(settings.database_owner_url, name)


def replace_solver(solver: Any, seconds: float) -> Any:
    return solver.model_copy(update={"deterministic_time_seconds": seconds})


_ = replace  # dataclasses.replace kept for readers comparing with test_sched_stock
