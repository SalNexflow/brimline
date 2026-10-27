"""Plan day, the board, approval and operator queues, through the API (M5).

The engine's clock is FIXED_NOW, Monday 2026-10-26 10:00 in Berlin, so the plan's minute 0 is
that Monday 08:00 and nothing may start before minute 120. The background solve runs at once
here (the runner is replaced), so a test can read the finished run straight away.
"""

import threading
import uuid
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg.types.json import Jsonb

from brimline_engine.api.planning import planning_runner
from brimline_engine.main import app
from brimline_engine.permissions import Actor
from brimline_engine.planning import queues, runs, schedules
from brimline_engine.scheduling.config import scheduler_config
from tests.conftest import FIXED_NOW, login

TZ = "Europe/Berlin"
PLAN_START = FIXED_NOW  # 10:00 Berlin; minute 120 of the plan


def key() -> dict[str, str]:
    return {"Idempotency-Key": f"test-{uuid.uuid4()}"}


@pytest.fixture(autouse=True)
def fresh_planning_state(client: TestClient, owner_url: str) -> Iterator[None]:
    """No plans, runs or tasks, and every seeded job waiting; the solve runs synchronously."""

    def reset() -> None:
        with psycopg.connect(owner_url) as conn:
            conn.execute("TRUNCATE tasks, schedules, planning_runs CASCADE")
            conn.execute("UPDATE jobs SET status = 'pending'")
            conn.execute("UPDATE orders SET status = 'open'")

    def run_now(run_id: int, now: datetime) -> None:
        runs.execute_run(
            app.state.pool, run_id, now, scheduler_config(), TZ, deterministic_time=5.0
        )

    reset()
    app.dependency_overrides[planning_runner] = lambda: run_now
    yield
    app.dependency_overrides.pop(planning_runner, None)
    reset()


@pytest.fixture
def planner(client: TestClient) -> dict[str, str]:
    return login(client, "U-PLANNER")


@pytest.fixture
def operator(client: TestClient) -> dict[str, str]:
    return login(client, "U-OPERATOR")


def plan_day(client: TestClient, headers: dict[str, str]) -> dict[str, Any]:
    r = client.post("/planning-runs", headers=headers | key())
    assert r.status_code == 202, r.text
    run = client.get(f"/planning-runs/{r.json()['id']}", headers=headers).json()
    assert run["status"] == "done", run
    result: dict[str, Any] = run
    return result


def draft(client: TestClient, headers: dict[str, str]) -> dict[str, Any]:
    board = client.get("/board", headers=headers).json()
    assert board["draft"] is not None
    result: dict[str, Any] = board["draft"]
    return result


def approve(client: TestClient, headers: dict[str, str], sid: int) -> Any:
    return client.post(f"/schedules/{sid}/approve", headers=headers | key())


def audit_rows(owner_url: str, action: str, entity_id: str) -> int:
    with psycopg.connect(owner_url) as conn:
        row = conn.execute(
            "SELECT count(*) FROM audit_log WHERE action = %s AND entity_id = %s",
            (action, entity_id),
        ).fetchone()
    assert row is not None
    return int(row[0])


def actor(owner_url: str, code: str, role: str) -> Actor:
    with psycopg.connect(owner_url) as conn:
        row = conn.execute("SELECT id FROM users WHERE code = %s", (code,)).fetchone()
    assert row is not None
    return Actor(user_id=int(row[0]), role=role, customer_id=None)  # type: ignore[arg-type]


# --- Plan day ---------------------------------------------------------------------------------


def test_plan_day_returns_a_run_and_produces_a_checked_draft(
    client: TestClient, planner: dict[str, str]
) -> None:
    run = plan_day(client, planner)
    assert run["schedule_id"] is not None and run["progress"]["check_valid"] is True
    d = draft(client, planner)
    assert d["status"] == "draft" and d["check"]["valid"] is True and d["check"]["violations"] == []
    # Every seeded line with full planning data is planned; the hilt has no size (on purpose).
    # (Orders made by other test modules have no planning data, so look at the seeded ones.)
    seeded = {f"BL-000{n}" for n in range(1, 9)}
    unplannable = {u["job"]: u["missing"] for u in d["unplannable"] if u["job"][:7] in seeded}
    assert unplannable == {"BL-0008-2": ["part size"]}
    assert len([j for j in d["jobs"] if j["order_number"] in seeded]) == 12
    # Nothing starts before the moment of planning.
    assert min(datetime.fromisoformat(t["start"]) for t in d["tasks"]) >= PLAN_START
    assert d["can_approve"] is True


def test_plan_day_while_a_run_is_active_returns_that_run(
    client: TestClient, planner: dict[str, str]
) -> None:
    started: list[int] = []
    app.dependency_overrides[planning_runner] = lambda: lambda run_id, now: started.append(run_id)
    first = client.post("/planning-runs", headers=planner | key()).json()
    second = client.post("/planning-runs", headers=planner | key()).json()
    assert first["id"] == second["id"] and first["status"] == "queued"
    assert started == [first["id"]]  # the second press started nothing


def test_only_planners_plan_and_customers_see_no_board(client: TestClient) -> None:
    assert (
        client.post("/planning-runs", headers=login(client, "U-OPERATOR") | key()).status_code
        == 403
    )
    assert (
        client.post("/planning-runs", headers=login(client, "U-STAFF") | key()).status_code == 403
    )
    assert client.get("/board", headers=login(client, "U-HARBOR")).status_code == 403
    assert client.get("/board", headers=login(client, "U-STAFF")).status_code == 200


def test_a_failed_run_says_why(
    client: TestClient, planner: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(*args: object, **kwargs: object) -> None:
        raise RuntimeError("solver exploded")

    monkeypatch.setattr(runs, "build_inputs", broken)
    r = client.post("/planning-runs", headers=planner | key()).json()
    run = client.get(f"/planning-runs/{r['id']}", headers=planner).json()
    assert (run["status"], run["error"]) == ("failed", "solver exploded")


def test_an_interrupted_run_is_marked_failed_at_engine_start(owner_url: str, app_url: str) -> None:
    with psycopg.connect(owner_url, autocommit=True) as conn:
        conn.execute(
            "INSERT INTO planning_runs (requested_by, status) SELECT id, 'running' FROM users"
            " WHERE code = 'U-PLANNER'"
        )
    with psycopg.connect(app_url, autocommit=True) as conn:
        assert runs.recover_interrupted(conn) == 1
        row = conn.execute("SELECT status, error FROM planning_runs").fetchone()
    assert row is not None and row[0] == "failed" and "restarted" in row[1]


# --- The badge is the independent checker -----------------------------------------------------


def test_a_tampered_plan_fails_the_badge_shows_why_and_cannot_be_approved(
    client: TestClient, planner: dict[str, str], owner_url: str
) -> None:
    plan_day(client, planner)
    sid = draft(client, planner)["id"]
    with psycopg.connect(owner_url) as conn:
        # Saved plans cannot change (trigger); simulate a corrupted row as the owner.
        conn.execute("ALTER TABLE schedules DISABLE TRIGGER schedules_guard")
        doc = conn.execute("SELECT document FROM schedules WHERE id = %s", (sid,)).fetchone()
        assert doc is not None
        d = doc[0]
        task = d["plan"]["jobs"][0]["tasks"][-1]
        task["end"] += 1  # one minute too long
        conn.execute("UPDATE schedules SET document = %s WHERE id = %s", (Jsonb(d), sid))
        conn.execute("ALTER TABLE schedules ENABLE TRIGGER schedules_guard")
    board = draft(client, planner)
    assert board["check"]["valid"] is False and board["can_approve"] is False
    assert [v["code"] for v in board["check"]["violations"]] == ["wrong_duration"]
    r = approve(client, planner, sid)
    assert r.status_code == 422 and "independent check fails" in r.json()["detail"]


def test_a_saved_plan_cannot_be_changed(
    client: TestClient, planner: dict[str, str], owner_url: str
) -> None:
    plan_day(client, planner)
    sid = draft(client, planner)["id"]
    with (
        psycopg.connect(owner_url) as conn,
        pytest.raises(psycopg.errors.RaiseException, match="saved version"),
    ):
        conn.execute("UPDATE schedules SET document = '{}' WHERE id = %s", (sid,))


# --- Approval ---------------------------------------------------------------------------------


def test_approval_is_audited_writes_tasks_and_replays(
    client: TestClient, planner: dict[str, str], owner_url: str
) -> None:
    plan_day(client, planner)
    d = draft(client, planner)
    k = key()
    first = client.post(f"/schedules/{d['id']}/approve", headers=planner | k)
    assert first.status_code == 200 and first.json()["status"] == "approved"
    replay = client.post(f"/schedules/{d['id']}/approve", headers=planner | k)
    assert replay.headers.get("Idempotent-Replayed") == "true" and replay.json() == first.json()
    assert audit_rows(owner_url, "schedule.approve", str(d["version"])) == 1
    board = client.get("/board", headers=planner).json()
    assert board["draft"] is None and board["approved"]["id"] == d["id"]
    assert all(t["task_id"] is not None for t in board["approved"]["tasks"])


def test_only_a_planner_approves(client: TestClient, planner: dict[str, str]) -> None:
    plan_day(client, planner)
    sid = draft(client, planner)["id"]
    for code in ("U-OPERATOR", "U-STAFF", "U-HARBOR"):
        assert approve(client, login(client, code), sid).status_code == 403


def test_a_discarded_plan_cannot_be_approved(
    client: TestClient, planner: dict[str, str], owner_url: str
) -> None:
    plan_day(client, planner)
    d = draft(client, planner)
    assert client.post(f"/schedules/{d['id']}/discard", headers=planner | key()).status_code == 200
    assert audit_rows(owner_url, "schedule.discard", str(d["version"])) == 1
    assert approve(client, planner, d["id"]).status_code == 409


def test_a_stale_plan_is_refused(
    client: TestClient, planner: dict[str, str], owner_url: str
) -> None:
    plan_day(client, planner)
    sid = draft(client, planner)["id"]
    with psycopg.connect(owner_url) as conn:
        conn.execute("UPDATE jobs SET quantity = quantity + 1 WHERE line_no = 1 AND order_id = 1")
    try:
        assert draft(client, planner)["stale"] is True
        r = approve(client, planner, sid)
        assert r.status_code == 422 and "stale" in r.json()["detail"]
    finally:
        with psycopg.connect(owner_url) as conn:
            conn.execute(
                "UPDATE jobs SET quantity = quantity - 1 WHERE line_no = 1 AND order_id = 1"
            )


def test_a_new_plan_replaces_the_waiting_draft(
    client: TestClient, planner: dict[str, str], owner_url: str
) -> None:
    plan_day(client, planner)
    old = draft(client, planner)
    plan_day(client, planner)
    assert draft(client, planner)["version"] > old["version"]
    assert approve(client, planner, old["id"]).status_code == 409
    assert audit_rows(owner_url, "schedule.discard", str(old["version"])) == 1


def test_at_most_one_approved_schedule_in_the_database(
    client: TestClient, planner: dict[str, str], owner_url: str
) -> None:
    plan_day(client, planner)
    assert approve(client, planner, draft(client, planner)["id"]).status_code == 200
    plan_day(client, planner)
    sid = draft(client, planner)["id"]
    with psycopg.connect(owner_url) as conn, pytest.raises(psycopg.errors.UniqueViolation):
        # Bypassing the engine: the partial unique index still allows only one approved plan.
        conn.execute(
            "UPDATE schedules SET status = 'approved', decided_by = created_by, decided_at = now()"
            " WHERE id = %s",
            (sid,),
        )


def test_two_concurrent_approvals_one_wins(
    client: TestClient, planner: dict[str, str], owner_url: str, app_url: str
) -> None:
    plan_day(client, planner)
    d = draft(client, planner)
    who = actor(owner_url, "U-PLANNER", "planner")
    barrier = threading.Barrier(2)
    outcomes: list[str] = []
    lock = threading.Lock()

    def attempt() -> None:
        with psycopg.connect(app_url, autocommit=True) as conn:
            barrier.wait()
            try:
                schedules.approve(
                    conn, who, d["id"], f"race-{uuid.uuid4()}", FIXED_NOW, scheduler_config(), TZ
                )
                result = "approved"
            except schedules.ConflictError:
                result = "refused"
        with lock:
            outcomes.append(result)

    threads = [threading.Thread(target=attempt) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    assert sorted(outcomes) == ["approved", "refused"]
    assert audit_rows(owner_url, "schedule.approve", str(d["version"])) == 1


# --- Unapproved plans never reach operators ---------------------------------------------------


def test_a_draft_is_not_in_any_queue(
    client: TestClient, planner: dict[str, str], operator: dict[str, str]
) -> None:
    plan_day(client, planner)
    q = client.get("/queues", headers=operator).json()
    assert q["schedule_version"] is None
    assert all(queue["tasks"] == [] for queue in q["queues"])


def test_the_database_refuses_tasks_for_an_unapproved_schedule(
    client: TestClient, planner: dict[str, str], app_url: str
) -> None:
    plan_day(client, planner)
    sid = draft(client, planner)["id"]
    with (
        psycopg.connect(app_url) as conn,
        pytest.raises(
            psycopg.errors.RaiseException, match="only be written for the approved schedule"
        ),
    ):
        conn.execute(
            "INSERT INTO tasks (schedule_id, job_id, seq, kind, planned_start, planned_end)"
            " SELECT %s, id, 1, 'prep', now(), now() + interval '15 minutes' FROM jobs LIMIT 1",
            (sid,),
        )


# --- Operators --------------------------------------------------------------------------------


def approved_queues(client: TestClient, planner: dict[str, str], operator: dict[str, str]) -> Any:
    plan_day(client, planner)
    assert approve(client, planner, draft(client, planner)["id"]).status_code == 200
    return client.get("/queues", headers=operator).json()


def tasks_of(q: Any, job: str) -> list[dict[str, Any]]:
    found = [t for queue in q["queues"] for t in queue["tasks"] if t["job"] == job]
    order = ["prep", "machine", "post", "finish"]
    return sorted(found, key=lambda t: order.index(t["kind"]))


def act(client: TestClient, headers: dict[str, str], task_id: int, action: str) -> Any:
    return client.post(f"/tasks/{task_id}/{action}", headers=headers | key())


def test_an_operator_completes_a_job_and_its_order(
    client: TestClient, planner: dict[str, str], operator: dict[str, str], owner_url: str
) -> None:
    q = approved_queues(client, planner, operator)
    job = "BL-0003-1"  # the model tray: the only line of order BL-0003
    steps = tasks_of(q, job)
    assert [t["kind"] for t in steps] == ["prep", "machine", "finish"]
    assert steps[0]["can_start"] and not steps[1]["can_start"]
    # Not in order: the machine task cannot start before prep is done.
    assert act(client, operator, steps[1]["id"], "start").status_code == 409
    for t in steps:
        assert act(client, operator, t["id"], "start").status_code == 200
        assert act(client, operator, t["id"], "done").status_code == 200
    with psycopg.connect(owner_url) as conn:
        row = conn.execute(
            "SELECT j.status, o.status FROM jobs j JOIN orders o ON o.id = j.order_id"
            " WHERE o.order_number = 'BL-0003'"
        ).fetchone()
    assert row == ("done", "done")
    assert audit_rows(owner_url, "task.done", str(steps[-1]["id"])) == 1


def test_task_rules(client: TestClient, planner: dict[str, str], operator: dict[str, str]) -> None:
    q = approved_queues(client, planner, operator)
    prep = tasks_of(q, "BL-0003-1")[0]
    assert act(client, operator, prep["id"], "done").status_code == 409  # not running yet
    assert act(client, planner, prep["id"], "start").status_code == 403  # planners do not
    assert act(client, operator, prep["id"], "start").status_code == 200
    assert act(client, operator, prep["id"], "start").status_code == 409  # already running
    assert act(client, operator, prep["id"], "fail").status_code == 200
    assert act(client, operator, prep["id"], "done").status_code == 409  # failed is final
    after = tasks_of(client.get("/queues", headers=operator).json(), "BL-0003-1")
    assert after[0]["status"] == "failed" and not after[1]["can_start"]


def test_a_machine_runs_one_task_at_a_time(
    client: TestClient, planner: dict[str, str], operator: dict[str, str]
) -> None:
    q = approved_queues(client, planner, operator)
    # Two jobs whose machine tasks are on the same machine: run the first, then try the second.
    machine_queue = next(
        queue for queue in q["queues"] if queue["machine"] and len(queue["tasks"]) >= 2
    )
    a, b = machine_queue["tasks"][:2]
    for t in (a, b):
        prep = tasks_of(q, t["job"])[0]
        assert act(client, operator, prep["id"], "start").status_code == 200
        assert act(client, operator, prep["id"], "done").status_code == 200
    assert act(client, operator, a["id"], "start").status_code == 200
    r = act(client, operator, b["id"], "start")
    assert r.status_code == 409 and "already running" in r.json()["detail"]


def test_approval_waits_while_manual_work_is_in_progress(
    client: TestClient, planner: dict[str, str], operator: dict[str, str]
) -> None:
    q = approved_queues(client, planner, operator)
    prep = tasks_of(q, "BL-0003-1")[0]
    assert act(client, operator, prep["id"], "start").status_code == 200
    plan_day(client, planner)
    r = approve(client, planner, draft(client, planner)["id"])
    assert r.status_code == 422 and "in progress" in r.json()["detail"]


# --- Fixed tasks from real work (M5 added requirement 1) --------------------------------------


def fixed_after(
    client: TestClient,
    planner: dict[str, str],
    operator: dict[str, str],
    owner_url: str,
    app_url: str,
    work: Callable[[Actor, dict[str, Any], psycopg.Connection], None],
    replan_at: datetime,
) -> dict[str, Any]:
    q = approved_queues(client, planner, operator)
    steps = {t["kind"]: t for t in tasks_of(q, "BL-0003-1")}
    who = actor(owner_url, "U-OPERATOR", "operator")
    with psycopg.connect(app_url, autocommit=True) as conn:
        work(who, steps, conn)
    from brimline_engine.planning.inputs import build_inputs

    with psycopg.connect(app_url) as conn:
        inputs = build_inputs(conn, replan_at, scheduler_config(), TZ)
    fixed = {f.job_id: f for f in inputs.instance.fixed}
    return {"fixed": fixed.get("BL-0003-1"), "anchor": inputs.anchor, "steps": steps}


def minute(dt: datetime) -> int:
    # FIXED_NOW's week: Monday 08:00 Berlin is 07:00 UTC; no clock change in this week.
    return int((dt - datetime(2026, 10, 26, 7, 0, tzinfo=UTC)) / timedelta(minutes=1))


def _start_machine(at: datetime) -> Callable[[Actor, dict[str, Any], psycopg.Connection], None]:
    def work(who: Actor, steps: dict[str, Any], conn: psycopg.Connection) -> None:
        queues.act(
            conn, who, steps["prep"]["id"], "start", f"k-{uuid.uuid4()}", at - timedelta(minutes=20)
        )
        queues.act(
            conn, who, steps["prep"]["id"], "done", f"k-{uuid.uuid4()}", at - timedelta(minutes=5)
        )
        queues.act(conn, who, steps["machine"]["id"], "start", f"k-{uuid.uuid4()}", at)

    return work


def test_a_running_task_ends_at_its_planned_end_when_that_is_later_than_now(
    client: TestClient,
    planner: dict[str, str],
    operator: dict[str, str],
    owner_url: str,
    app_url: str,
) -> None:
    started = FIXED_NOW + timedelta(minutes=30)
    out = fixed_after(
        client,
        planner,
        operator,
        owner_url,
        app_url,
        _start_machine(started),
        started + timedelta(minutes=10),
    )
    planned_end = datetime.fromisoformat(out["steps"]["machine"]["planned_end"])
    assert out["fixed"] is not None
    assert (out["fixed"].start, out["fixed"].end) == (minute(started), minute(planned_end))


def test_a_running_task_past_its_planned_end_ends_now_at_the_earliest(
    client: TestClient,
    planner: dict[str, str],
    operator: dict[str, str],
    owner_url: str,
    app_url: str,
) -> None:
    started = FIXED_NOW + timedelta(minutes=30)
    late = started + timedelta(days=1)  # far past the planned end (the tray takes 300 minutes)
    out = fixed_after(client, planner, operator, owner_url, app_url, _start_machine(started), late)
    assert out["fixed"] is not None
    assert (out["fixed"].start, out["fixed"].end) == (minute(started), minute(late))


def test_a_done_task_keeps_its_actual_times(
    client: TestClient,
    planner: dict[str, str],
    operator: dict[str, str],
    owner_url: str,
    app_url: str,
) -> None:
    started = FIXED_NOW + timedelta(minutes=30)
    ended = started + timedelta(minutes=47)  # much quicker than planned

    def work(who: Actor, steps: dict[str, Any], conn: psycopg.Connection) -> None:
        _start_machine(started)(who, steps, conn)
        queues.act(conn, who, steps["machine"]["id"], "done", f"k-{uuid.uuid4()}", ended)

    out = fixed_after(
        client, planner, operator, owner_url, app_url, work, ended + timedelta(hours=1)
    )
    assert out["fixed"] is not None
    assert (out["fixed"].start, out["fixed"].end) == (minute(started), minute(ended))
