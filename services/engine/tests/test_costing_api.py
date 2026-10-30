"""Quoted versus actual through the API (M10): failures with reasons, reprints, the frozen outcome
and the report. Expected costs are worked out by hand in the comments (hard rule 10).

Rates (config/shop.toml): setup 1500 c, PETG-BLACK 4 c/g, FDM 6 c/min.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient

from brimline_engine.api.deps import utc_now
from brimline_engine.main import app
from tests.conftest import FIXED_NOW, login
from tests.test_planning_api import (  # noqa: F401 (fixtures used by name)
    approve,
    draft,
    fresh_planning_state,
    key,
    plan_day,
    tasks_of,
)
from tests.test_quotes_api import decide, edit, submit

# 4 phone stands, 35 g and 90 min each. Estimate: 1500 + 4 x (35 x 4 + 90 x 6) = 1500 + 2720.
QUOTE = {
    "due_date": "2026-12-18",
    "rush": False,
    "notes": "",
    "lines": [
        {
            "part_name": "Phone stand",
            "quantity": 4,
            "material_code": "PETG-BLACK",
            "grams_per_part": 35,
            "minutes_per_part": 90,
            "part_mm": [80, 60, 40],
            "post_processing": [],
        }
    ],
}
ESTIMATE = 4220


@contextmanager
def clock(at: datetime) -> Iterator[None]:
    before = app.dependency_overrides[utc_now]
    app.dependency_overrides[utc_now] = lambda: at
    try:
        yield
    finally:
        app.dependency_overrides[utc_now] = before


def run(client: TestClient, at: datetime, task_id: int, action: str, **mark: Any) -> Any:
    """One button press at `at`, signed in afresh (sessions last 8 hours)."""
    with clock(at):
        headers = login(client, "U-OPERATOR") | key()
        return client.post(f"/tasks/{task_id}/{action}", json=mark or None, headers=headers)


def replan(client: TestClient, at: datetime) -> Any:
    with clock(at):
        planner = login(client, "U-PLANNER")
        plan_day(client, planner)
        assert approve(client, planner, draft(client, planner)["id"]).status_code == 200
        return client.get("/queues", headers=login(client, "U-OPERATOR")).json()


def outcome_row(owner_url: str, label_start: str) -> dict[str, Any]:
    with psycopg.connect(owner_url) as conn:
        cur = conn.execute(
            "SELECT estimated_cents, actual_cents, estimated_minutes, actual_seconds,"
            " estimated_grams, actual_grams, grams_assumed, attempts, failed_attempts,"
            " failure_reasons FROM job_outcomes WHERE label LIKE %s",
            (label_start + "%",),
        )
        row = cur.fetchone()
        assert row is not None, f"no outcome for {label_start}"
        return dict(zip([d.name for d in cur.description or []], row, strict=True))


@pytest.fixture
def quoted_job(client: TestClient) -> str:
    """An approved quote's order; returns its job key (order-line)."""
    number = submit(client, "U-STAFF").json()["quote_number"]
    assert edit(client, "U-STAFF", number, QUOTE).status_code == 200
    approved = decide(client, "U-STAFF", number, "approve")
    assert approved.status_code == 200, approved.text
    return f"{approved.json()['order_number']}-1"


def test_a_failed_print_is_reprinted_and_both_attempts_are_costed(
    client: TestClient, quoted_job: str, owner_url: str
) -> None:
    t0 = FIXED_NOW
    q = replan(client, t0)
    prep, machine, *rest = tasks_of(q, quoted_job)
    assert machine["attempt"] == 1
    for t, action in ((prep, "start"), (prep, "done"), (machine, "start")):
        assert run(client, t0, t["id"], action).status_code == 200
    # Fails 2 hours in with 50 g used: 1500 + 50 x 4 + 120 x 6 = 1500 + 200 + 720 = 2420.
    failed = run(
        client, t0 + timedelta(hours=2), machine["id"], "fail",
        failure_reason="warping", material_used_g=50,
    )  # fmt: skip
    assert failed.status_code == 200, failed.text

    # The next Plan day plans the job again: a reprint, attempt 2.
    q = replan(client, t0 + timedelta(hours=2, minutes=5))
    prep, machine, *rest = tasks_of(q, quoted_job)
    assert machine["attempt"] == 2 and prep["attempt"] == 2
    t1 = t0 + timedelta(hours=3)
    for t, action in ((prep, "start"), (prep, "done"), (machine, "start")):
        assert run(client, t1, t["id"], action).status_code == 200
    # Runs 450 min (quoted 4 x 90 = 360) with 150 g: 1500 + 150 x 4 + 450 x 6 = 1500 + 600 + 2700.
    t2 = t1 + timedelta(minutes=450)
    assert run(client, t2, machine["id"], "done", material_used_g=150).status_code == 200
    for t in rest:
        assert run(client, t2, t["id"], "start").status_code == 200
        assert run(client, t2, t["id"], "done").status_code == 200

    o = outcome_row(owner_url, quoted_job.rsplit("-", 1)[0] + " line 1")
    assert o == {
        "estimated_cents": ESTIMATE,
        "actual_cents": 2420 + 4800,
        "estimated_minutes": 360,
        "actual_seconds": (120 + 450) * 60,
        "estimated_grams": 140,
        "actual_grams": 200,
        "grams_assumed": 0,
        "attempts": 2,
        "failed_attempts": 1,
        "failure_reasons": ["warping"],
    }
    # The report lists the job and the type's numbers include it.
    report = client.get("/reports/quoted-vs-actual", headers=login(client, "U-STAFF")).json()
    line = next(j for j in report["jobs"] if j["label"].startswith(quoted_job.rsplit("-", 1)[0]))
    assert (line["estimated_cents"], line["actual_cents"], line["synthetic"]) == (4220, 7220, False)


def test_a_run_copied_into_a_new_plan_is_counted_once(client: TestClient, owner_url: str) -> None:
    # The seeded model tray (BL-0003, no quote): 6 x 40 min = 240 min estimated.
    t0 = FIXED_NOW
    prep, machine, *rest = tasks_of(replan(client, t0), "BL-0003-1")
    for t, action in ((prep, "start"), (prep, "done"), (machine, "start")):
        assert run(client, t0, t["id"], action).status_code == 200
    # A new plan is approved while the print runs: the running task is copied into it.
    # Prep is behind it, so the new plan holds the running print and what follows it.
    machine, *rest = tasks_of(replan(client, t0 + timedelta(hours=1)), "BL-0003-1")
    assert machine["kind"] == "machine" and machine["status"] == "running"
    t1 = t0 + timedelta(hours=4)
    assert run(client, t1, machine["id"], "done").status_code == 200
    for t in rest:
        assert run(client, t1, t["id"], "start").status_code == 200
        assert run(client, t1, t["id"], "done").status_code == 200
    o = outcome_row(owner_url, "BL-0003 line 1")
    # One run of 4 hours, not two; no quote, so no cost on either side.
    assert (o["attempts"], o["actual_seconds"], o["estimated_minutes"]) == (1, 4 * 3600, 240)
    assert (o["estimated_cents"], o["actual_cents"]) == (None, None)


def test_a_failure_before_the_print_is_an_attempt_with_setup_only(
    client: TestClient, quoted_job: str, owner_url: str
) -> None:
    t0 = FIXED_NOW
    prep, *_ = tasks_of(replan(client, t0), quoted_job)
    assert run(client, t0, prep["id"], "start").status_code == 200
    assert run(client, t0, prep["id"], "fail", failure_reason="other").status_code == 200
    q = replan(client, t0 + timedelta(minutes=10))
    steps = tasks_of(q, quoted_job)
    t1 = t0 + timedelta(hours=1)
    for t in steps:
        assert run(client, t1, t["id"], "start").status_code == 200
        end = t1 + timedelta(minutes=360) if t["kind"] == "machine" else t1
        grams = {"material_used_g": 140} if t["kind"] == "machine" else {}
        assert run(client, end, t["id"], "done", **grams).status_code == 200
        t1 = end
    o = outcome_row(owner_url, quoted_job.rsplit("-", 1)[0] + " line 1")
    # Setup twice, the print exactly as quoted: 1500 + (1500 + 140 x 4 + 360 x 6) = 1500 + 4220.
    assert (o["attempts"], o["failed_attempts"], o["actual_cents"]) == (2, 1, 1500 + ESTIMATE)


def test_what_may_be_recorded_with_each_action(client: TestClient) -> None:
    prep, *_ = tasks_of(replan(client, FIXED_NOW), "BL-0003-1")
    assert run(client, FIXED_NOW, prep["id"], "start", material_used_g=5).status_code == 422
    assert run(client, FIXED_NOW, prep["id"], "start").status_code == 200
    r = run(client, FIXED_NOW, prep["id"], "done", material_used_g=5)
    assert r.status_code == 422 and "print or machining" in r.json()["detail"]
    r = run(client, FIXED_NOW, prep["id"], "done", failure_reason="clog")
    assert r.status_code == 422 and "only when a task fails" in r.json()["detail"]
    r = run(client, FIXED_NOW, prep["id"], "fail")
    assert r.status_code == 422 and "why it failed" in r.json()["detail"]
    r = run(client, FIXED_NOW, prep["id"], "fail", failure_reason="melted")
    assert r.status_code == 422  # not one of the reasons


def test_outcomes_are_frozen_for_the_app(app_url: str) -> None:
    with psycopg.connect(app_url) as conn, pytest.raises(psycopg.errors.Error):
        conn.execute("UPDATE job_outcomes SET actual_cents = 0")


@pytest.mark.parametrize(("user", "status"), [("U-STAFF", 200), ("U-PLANNER", 200),
                                              ("U-OPERATOR", 403), ("U-HARBOR", 403)])  # fmt: skip
def test_who_may_read_the_report(client: TestClient, user: str, status: int) -> None:
    r = client.get("/reports/quoted-vs-actual", headers=login(client, user))
    assert r.status_code == status


def test_the_seeded_history_flags_the_under_quoted_type_and_is_labelled(
    client: TestClient,
) -> None:
    report = client.get("/reports/quoted-vs-actual", headers=login(client, "U-STAFF")).json()
    flagged = [t["material_code"] for t in report["types"] if t["flagged"]]
    assert flagged == ["TPU-BLACK"]  # config/costing.toml: the demo's biased material
    assert report["types"][0]["suggestion"] == "Review the price rule for TPU-BLACK."
    assert report["synthetic_jobs"] == 64  # 8 materials x 8 jobs
    assert all(j["synthetic"] for j in report["jobs"] if j["label"].startswith("History "))
