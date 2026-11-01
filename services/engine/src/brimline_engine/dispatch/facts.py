"""The facts the guard decides on, gathered by code: the database, the machine's own adapter, and the
independent checker through its JSON format (the checker imports nothing from here).

Nothing the agent says is a fact: a status comes from asking the adapter now, never from the model.
"""

import copy
from datetime import datetime
from typing import Any

import psycopg

from brimline_engine.checker import check_document
from brimline_engine.dispatch.guard import Call, Facts, TaskFacts
from brimline_engine.machines.model import Adapter, AdapterError
from brimline_engine.materials.grams import job_grams
from brimline_engine.planning.clock import minute_at_or_after

# G06: the checker rules a start must not add (docs/DISPATCH_RULES.md).
PLAN_RULES = frozenset(
    {
        "not_eligible",
        "before_release",
        "machine_off_shift",
        "machine_overlap",
        "changeover",
        "machine_down",
        "material_short",
        "past_horizon",
    }
)


def started_now(doc: dict[str, Any], job: str, minute: int) -> dict[str, Any]:
    """The plan document with `job`'s machine task moved to start at `minute`, its prep placed just
    before it (done already). Everything else as approved."""
    out = copy.deepcopy(doc)
    pj = next(p for p in out["plan"]["jobs"] if p["job_id"] == job)
    for t in pj["tasks"]:
        if t["kind"] == "machine":
            t["end"], t["start"] = minute + (t["end"] - t["start"]), minute
    for t in pj["tasks"]:
        if t["kind"] == "prep":
            t["start"], t["end"] = minute - (t["end"] - t["start"]), minute
    return out


def plan_check_added(doc: dict[str, Any], job: str, minute: int) -> tuple[str, ...]:
    """G06: checker rule codes (from PLAN_RULES) that starting `job` at `minute` adds to the plan."""

    def found(d: dict[str, Any]) -> set[tuple[str, str | None]]:
        return {(v.code, v.job) for v in check_document(d).violations if v.code in PLAN_RULES}

    added = found(started_now(doc, job, minute)) - found(doc)
    return tuple(sorted({code for code, _ in added}))


def free_grams(conn: psycopg.Connection, material_id: int) -> int:
    """Stock on hand now, less the grams of prints running now (D148; G07)."""
    on_hand = conn.execute(
        "SELECT coalesce(max(on_hand_g), 0) FROM stock WHERE material_id = %s", (material_id,)
    ).fetchone()
    running = conn.execute(
        "SELECT j.id, j.quantity FROM tasks t JOIN schedules s ON s.id = t.schedule_id"
        " AND s.status = 'approved' JOIN jobs j ON j.id = t.job_id"
        " WHERE t.kind = 'machine' AND t.status = 'running' AND j.material_id = %s",
        (material_id,),
    ).fetchall()
    grams = job_grams(conn, [int(r[0]) for r in running])
    in_use = sum(int(q) * (grams[int(j)].per_part or 0) for j, q in running)
    return int(on_hand[0] if on_hand else 0) - in_use


def gather(
    conn: psycopg.Connection,
    run_id: int,
    call: Call,
    adapters: dict[str, Adapter],
    now: datetime,
    tz: str,
) -> Facts:
    run = conn.execute(
        "SELECT r.schedule_id, u.role FROM dispatch_runs r JOIN users u ON u.id = r.asked_by"
        " WHERE r.id = %s",
        (run_id,),
    ).fetchone()
    assert run is not None
    run_schedule, asked_role = int(run[0]), str(run[1])
    approvals = conn.execute(
        "SELECT p.action, p.task_id, p.machine_code, a.approved_role, e.id IS NOT NULL"
        " FROM dispatch_approvals a JOIN dispatch_proposals p ON p.id = a.proposal_id"
        " LEFT JOIN dispatch_executions e ON e.proposal_id = p.id WHERE p.run_id = %s",
        (run_id,),
    ).fetchall()
    approved = frozenset((str(a), int(t), str(m)) for a, t, m, _, _ in approvals)
    executed = frozenset((str(a), int(t), str(m)) for a, t, m, _, done in approvals if done)
    roles = frozenset(
        str(r)
        for a, t, m, r, _ in approvals
        if (a, t, m) == (call.tool, call.task_id, call.machine)
    )
    current = conn.execute("SELECT id FROM schedules WHERE status = 'approved'").fetchone()
    approved_schedule = None if current is None else int(current[0])

    task: TaskFacts | None = None
    grams_needed = grams_free = 0
    added: tuple[str, ...] = ()
    if call.task_id is not None:
        row = conn.execute(
            "SELECT t.kind, t.status, t.schedule_id, m.code, t.job_id, t.seq, j.quantity,"
            "       j.material_id, o.order_number || '-' || j.line_no, s.document, s.anchor"
            " FROM tasks t JOIN jobs j ON j.id = t.job_id JOIN orders o ON o.id = j.order_id"
            " JOIN schedules s ON s.id = t.schedule_id"
            " LEFT JOIN machines m ON m.id = t.machine_id WHERE t.id = %s",
            (call.task_id,),
        ).fetchone()
        if row is not None:
            kind, status, sched, machine, job_id, seq, qty, material_id, key, doc, anchor = row
            earlier = conn.execute(
                "SELECT count(*) FROM tasks WHERE schedule_id = %s AND job_id = %s AND seq < %s"
                " AND status <> 'done'",
                (sched, job_id, seq),
            ).fetchone()
            task = TaskFacts(
                id=call.task_id,
                kind=str(kind),
                status=str(status),
                schedule_id=int(sched),
                planned_machine=str(machine or ""),
                earlier_done=earlier is not None and int(earlier[0]) == 0,
                running_on=str(machine) if status == "running" else None,
            )
            per_part = job_grams(conn, [int(job_id)])[int(job_id)].per_part or 0
            grams_needed = int(qty) * per_part
            grams_free = free_grams(conn, int(material_id))
            if call.tool == "start_task" and kind == "machine":
                added = plan_check_added(doc, str(key), minute_at_or_after(now, anchor, tz))

    adapter = adapters.get(call.machine)
    state: str | None = None
    if adapter is not None and call.tool in ("start_task", "stop_task") and task is not None:
        try:
            state = adapter.get_status().state
        except AdapterError:
            state = None
    return Facts(
        machine_known=adapter is not None,
        stop_supported=adapter is not None and adapter.can_stop,
        approved=approved,
        approver_roles=roles,
        asked_by_role=asked_role,
        executed=executed,
        run_schedule_id=run_schedule,
        approved_schedule_id=approved_schedule,
        task=task,
        machine_state=state,
        plan_check_added=added,
        grams_needed=grams_needed,
        grams_free=grams_free,
    )
