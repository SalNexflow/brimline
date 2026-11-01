"""Dispatch: propose, Proceed, execute through the guard, and watch running work (docs/DISPATCH_RULES.md).

Every tool call, by the agent or by code, is one `dispatch_calls` row with the guard's verdict and the
machine's answer; a start or stop that reaches a machine is also an audit-log row. Nothing reaches a
machine without a Proceed on that exact action, and nothing runs twice (G02, enforced by a unique row).
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any

import anthropic
import psycopg
from psycopg.types.json import Jsonb
from pydantic import BaseModel

from brimline_engine import audit, idempotency
from brimline_engine.ai.calls import record_call
from brimline_engine.ai.config import models_config
from brimline_engine.ai.gateway import ModelClient, run_structured
from brimline_engine.dispatch import agent
from brimline_engine.dispatch.facts import gather
from brimline_engine.dispatch.guard import Call, check
from brimline_engine.machines.model import Adapter, AdapterError
from brimline_engine.permissions import Actor, can
from brimline_engine.planning.inputs import job_key
from brimline_engine.planning.queues import TaskAction, TaskMark, apply_action

PROPOSE_SCHEMA: dict[str, Any] = anthropic.transform_schema(agent.Proposals)
EXECUTE_SCHEMA: dict[str, Any] = anthropic.transform_schema(agent.ToolCalls)


class NotFoundError(Exception):
    pass


class ForbiddenError(Exception):
    pass


class ConflictError(Exception):
    pass


@dataclass
class Shop:
    """What dispatch needs besides the database: the machines' adapters and, when simulated, a way to
    put a job's file on a machine (stands in for slicing and uploading)."""

    adapters: dict[str, Adapter]
    prepare: Any  # (machine, job, seconds) -> None
    speed: float  # simulated machine seconds per real second (1.0 for real machines)
    simulated: bool = True


# --- Reading -----------------------------------------------------------------------------------


class MachineOut(BaseModel):
    code: str
    protocol: str
    source: str  # official | community
    state: str | None  # None: did not answer
    job: str | None
    progress: float | None
    message: str  # the machine's own words: untrusted, shown labelled


def machine_states(shop: Shop, sources: dict[str, str]) -> list[MachineOut]:
    out = []
    for code, a in sorted(shop.adapters.items()):
        try:
            s = a.get_status()
            out.append(
                MachineOut(
                    code=code,
                    protocol=a.protocol,
                    source=sources.get(code, "official"),
                    state=s.state,
                    job=s.job,
                    progress=s.progress,
                    message=s.message[:300],
                )
            )
        except AdapterError as e:
            out.append(
                MachineOut(
                    code=code,
                    protocol=a.protocol,
                    source=sources.get(code, "official"),
                    state=None,
                    job=None,
                    progress=None,
                    message=f"no answer ({e.kind})",
                )
            )
    return out


def _startable(conn: psycopg.Connection, schedule_id: int) -> list[dict[str, Any]]:
    """Machine tasks of the approved plan that may start now: planned, earlier tasks done. The text
    fields are what people wrote (untrusted)."""
    rows = conn.execute(
        "SELECT t.id, o.order_number, j.line_no, j.part_name, m.code, mat.code, t.planned_start,"
        "       o.notes,"
        "       (SELECT f.filename FROM files f WHERE f.job_id = j.id ORDER BY f.id DESC LIMIT 1)"
        " FROM tasks t JOIN jobs j ON j.id = t.job_id JOIN orders o ON o.id = j.order_id"
        " JOIN machines m ON m.id = t.machine_id JOIN materials mat ON mat.id = j.material_id"
        " WHERE t.schedule_id = %s AND t.kind = 'machine' AND t.status = 'planned'"
        " AND NOT EXISTS (SELECT 1 FROM tasks e WHERE e.schedule_id = t.schedule_id"
        "                 AND e.job_id = t.job_id AND e.seq < t.seq AND e.status <> 'done')"
        " ORDER BY t.planned_start, t.id",
        (schedule_id,),
    ).fetchall()
    return [
        {
            "task_id": int(r[0]),
            "job": job_key(r[1], r[2]),
            "part_name": r[3],
            "machine": r[4],
            "material": r[5],
            "planned_start": r[6].isoformat(),
            "notes": r[7] or "",
            "file_name": r[8] or "",
        }
        for r in rows
    ]


# --- Propose -----------------------------------------------------------------------------------


def propose(
    conn: psycopg.Connection,
    actor: Actor,
    shop: Shop,
    sources: dict[str, str],
    now: datetime,
    tz: str,
    client: ModelClient | None,
    mode: str,
    budget_reason: str | None,
) -> int:
    """Ask the agent (or, when it cannot be used, code) for proposals; pre-check and store them."""
    if not can(actor, "dispatch.ask"):
        raise ForbiddenError("dispatch.ask")
    plan = conn.execute("SELECT id FROM schedules WHERE status = 'approved'").fetchone()
    if plan is None:
        raise ConflictError("there is no approved plan to dispatch")
    schedule_id = int(plan[0])
    tasks = _startable(conn, schedule_id)
    machines = [m.model_dump() for m in machine_states(shop, sources)]
    proposals: list[agent.ProposalOut] = []
    proposed_by, note, call_id = "agent", "", None
    if client is None or budget_reason:
        note = budget_reason or "agent unavailable (AI is off)"
    else:
        task = models_config().task("dispatch_propose")
        result = run_structured(
            client,
            purpose="dispatch_propose",
            mode=mode,
            task=task,
            price=models_config().prices[task.model],
            schema=agent.Proposals,
            json_schema=PROPOSE_SCHEMA,
            system=agent.PROPOSE_SYSTEM,
            user=agent.propose_prompt(tasks, machines),
        )
        call_id = record_call(conn, result.record, actor.user_id)
        if result.value is None:
            note = f"agent unavailable ({result.record.outcome})"
        else:
            proposals = result.value.proposals
    if note:  # code proposes: each startable task whose machine reports idle, one per machine
        proposed_by = "code"
        parsed = agent.Proposals.model_validate_json(
            agent.fake_propose(agent.propose_prompt(tasks, machines))
        )
        proposals = [
            p.model_copy(
                update={"reason": "Proposed by code: the machine is free and this is next."}
            )
            for p in parsed.proposals
        ]
    with conn.transaction():
        row = conn.execute(
            "INSERT INTO dispatch_runs (schedule_id, asked_by, proposed_by, ai_call_id, note,"
            " created_at) VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
            (schedule_id, actor.user_id, proposed_by, call_id, note, now),
        ).fetchone()
        assert row is not None
        run_id = int(row[0])
        for p in proposals:
            call = Call(p.action, p.machine, p.task_id)
            verdict = check(
                call, gather(conn, run_id, call, shop.adapters, now, tz), require_approval=False
            )
            conn.execute(
                "INSERT INTO dispatch_proposals (run_id, action, task_id, machine_code, reason,"
                " precheck, precheck_detail, created_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)"
                " ON CONFLICT (run_id, action, task_id, machine_code) DO NOTHING",
                (
                    run_id,
                    p.action,
                    p.task_id,
                    p.machine,
                    p.reason,
                    verdict.code,
                    verdict.detail,
                    now,
                ),
            )
    return run_id


# --- Proceed -----------------------------------------------------------------------------------


def proceed(
    conn: psycopg.Connection,
    actor: Actor,
    run_id: int,
    proposal_ids: list[int],
    key: str,
    now: datetime,
) -> tuple[idempotency.StoredResponse, bool]:
    """A person approves specific proposals that passed their pre-check. Approving one twice adds
    nothing (one approval per proposal)."""
    if not can(actor, "dispatch.proceed"):
        raise ForbiddenError("dispatch.proceed")
    endpoint = f"POST /dispatch/{run_id}/proceed"
    with conn.transaction():
        stored = idempotency.claim(
            conn,
            user_id=actor.user_id,
            endpoint=endpoint,
            key=key,
            req_hash=idempotency.request_hash({"proposals": sorted(proposal_ids)}),
        )
        if stored is not None:
            return stored, True
        if conn.execute("SELECT 1 FROM dispatch_runs WHERE id = %s", (run_id,)).fetchone() is None:
            raise NotFoundError(str(run_id))
        ok = {
            int(r[0])
            for r in conn.execute(
                "SELECT id FROM dispatch_proposals WHERE run_id = %s AND precheck = 'allowed'"
                " AND id = ANY(%s)",
                (run_id, proposal_ids),
            ).fetchall()
        }
        if set(proposal_ids) - ok:
            raise ConflictError(
                "only proposals of this dispatch that passed the check can be approved"
            )
        added = []
        for pid in sorted(ok):
            row = conn.execute(
                "INSERT INTO dispatch_approvals (proposal_id, approved_by, approved_role, created_at)"
                " VALUES (%s, %s, %s, %s) ON CONFLICT (proposal_id) DO NOTHING RETURNING id",
                (pid, actor.user_id, actor.role, now),
            ).fetchone()
            if row is not None:
                added.append(pid)
        audit.record(
            conn,
            actor_user_id=actor.user_id,
            action="dispatch.proceed",
            entity_type="dispatch_run",
            entity_id=str(run_id),
            before=None,
            after={"approved": added, "already_approved": sorted(ok - set(added))},
            idempotency_key=key,
        )
        response = idempotency.StoredResponse(200, {"run_id": run_id, "approved": sorted(ok)})
        idempotency.store(
            conn, user_id=actor.user_id, endpoint=endpoint, key=key, response=response
        )
        return response, False


# --- Execute -----------------------------------------------------------------------------------


@dataclass(frozen=True)
class CallOutcome:
    tool: str
    machine: str
    task_id: int | None
    verdict: str
    detail: str


def _approved_open(conn: psycopg.Connection, run_id: int) -> list[dict[str, Any]]:
    return [
        {"proposal_id": int(r[0]), "action": r[1], "task_id": int(r[2]), "machine": r[3]}
        for r in conn.execute(
            "SELECT p.id, p.action, p.task_id, p.machine_code FROM dispatch_proposals p"
            " JOIN dispatch_approvals a ON a.proposal_id = p.id"
            " WHERE p.run_id = %s AND NOT EXISTS"
            " (SELECT 1 FROM dispatch_executions e WHERE e.proposal_id = p.id) ORDER BY p.id",
            (run_id,),
        ).fetchall()
    ]


def execute(
    conn: psycopg.Connection,
    run_id: int,
    shop: Shop,
    sources: dict[str, str],
    now: datetime,
    tz: str,
    client: ModelClient | None,
    mode: str,
    budget_reason: str | None,
    actor_user_id: int,
    calls_override: list[agent.ToolCallOut] | None = None,
) -> list[CallOutcome]:
    """Carry out the approved, not yet executed actions of a run. The agent issues the tool calls;
    when it cannot be used, code issues exactly the approved actions ("executed by code").
    `calls_override` replaces the agent's calls (the eval's scripted misbehaving agent)."""
    approved = _approved_open(conn, run_id)
    if not approved and calls_override is None:
        return []
    made_by, why = "agent", ""
    calls: list[agent.ToolCallOut] = []
    if calls_override is not None:
        calls = calls_override
    elif client is None or budget_reason:
        made_by, why = "code", ("AI budget reached" if budget_reason else "agent unavailable")
    else:
        machines = [
            m.model_dump()
            for m in machine_states(shop, sources)
            if m.code in {a["machine"] for a in approved}
        ]
        task = models_config().task("dispatch_execute")
        result = run_structured(
            client,
            purpose="dispatch_execute",
            mode=mode,
            task=task,
            price=models_config().prices[task.model],
            schema=agent.ToolCalls,
            json_schema=EXECUTE_SCHEMA,
            system=agent.EXECUTE_SYSTEM,
            user=agent.execute_prompt(
                [{k: a[k] for k in ("action", "task_id", "machine")} for a in approved], machines
            ),
        )
        record_call(conn, result.record, actor_user_id)
        if result.value is None:
            made_by, why = "code", f"agent unavailable ({result.record.outcome})"
        else:
            calls = result.value.calls
    if made_by == "code":
        calls = [
            agent.ToolCallOut(tool=a["action"], machine=a["machine"], task_id=a["task_id"])
            for a in approved
        ]
    return [_run_call(conn, run_id, c, made_by, why, shop, now, tz, actor_user_id) for c in calls]


def _log(
    conn: psycopg.Connection,
    run_id: int,
    c: agent.ToolCallOut,
    made_by: str,
    why: str,
    proposal_id: int | None,
    verdict: str,
    detail: str,
    result: Any,  # noqa: ANN401 - JSON
    now: datetime,
) -> int:
    row = conn.execute(
        "INSERT INTO dispatch_calls (run_id, made_by, why_code, tool, args, proposal_id, verdict,"
        " detail, result, created_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
        (
            run_id,
            made_by,
            why,
            c.tool,
            Jsonb(c.model_dump()),
            proposal_id,
            verdict,
            detail,
            None if result is None else Jsonb(result),
            now,
        ),
    ).fetchone()
    assert row is not None
    return int(row[0])


def _run_call(
    conn: psycopg.Connection,
    run_id: int,
    c: agent.ToolCallOut,
    made_by: str,
    why: str,
    shop: Shop,
    now: datetime,
    tz: str,
    actor_user_id: int,
) -> CallOutcome:
    call = Call(c.tool, c.machine, c.task_id)
    adapter = shop.adapters.get(c.machine)
    if c.tool in ("get_status", "explain_error"):
        with conn.transaction():
            verdict = check(call, gather(conn, run_id, call, shop.adapters, now, tz))
            result: Any = None
            if verdict.allowed and adapter is not None:
                try:
                    if c.tool == "get_status":
                        s = adapter.get_status()
                        result = {"state": s.state, "job": s.job, "message": s.message[:300]}
                    else:
                        result = {"machine_says": adapter.last_error()[:300]}
                except AdapterError as e:
                    result = {"error": e.kind}
            _log(conn, run_id, c, made_by, why, None, verdict.code, verdict.detail, result, now)
        return CallOutcome(c.tool, c.machine, c.task_id, verdict.code, verdict.detail)

    with conn.transaction():
        prop = conn.execute(
            "SELECT p.id FROM dispatch_proposals p JOIN dispatch_approvals a ON a.proposal_id = p.id"
            " WHERE p.run_id = %s AND p.action = %s AND p.task_id = %s AND p.machine_code = %s",
            (run_id, c.tool, c.task_id, c.machine),
        ).fetchone()
        proposal_id = None if prop is None else int(prop[0])
        verdict = check(call, gather(conn, run_id, call, shop.adapters, now, tz))
        if not verdict.allowed or adapter is None or c.task_id is None or proposal_id is None:
            _log(
                conn, run_id, c, made_by, why, proposal_id, verdict.code, verdict.detail, None, now
            )
            return CallOutcome(c.tool, c.machine, c.task_id, verdict.code, verdict.detail)
    # Allowed: change the task, then the machine, in one transaction; a machine that refuses or does
    # not answer undoes the task change and the refusal is logged instead.
    try:
        with conn.transaction():
            # The task's row is the lock: a second Proceed or a retry of the same action waits here,
            # then finds it executed (G02); the app role may not lock append-only rows.
            conn.execute("SELECT 1 FROM tasks WHERE id = %s FOR UPDATE", (c.task_id,))
            again = check(call, gather(conn, run_id, call, shop.adapters, now, tz))
            if not again.allowed:  # someone else carried it out a moment ago
                _log(
                    conn, run_id, c, made_by, why, proposal_id, again.code, again.detail, None, now
                )
                return CallOutcome(c.tool, c.machine, c.task_id, again.code, again.detail)
            job = _job_of(conn, c.task_id)
            if c.tool == "start_task":
                kind, before, after = apply_action(
                    conn, actor_user_id, c.task_id, "start", now, TaskMark(), time_source="machine"
                )
                shop.prepare(c.machine, job, _machine_seconds(conn, c.task_id))
                adapter.start(job)
            else:
                mark = TaskMark(failure_reason="other", failure_note="Stopped through dispatch.")
                kind, before, after = apply_action(
                    conn, actor_user_id, c.task_id, "fail", now, mark
                )
                adapter.stop(job)
            call_id = _log(
                conn,
                run_id,
                c,
                made_by,
                why,
                proposal_id,
                "allowed",
                "carried out",
                {"ok": True},
                now,
            )
            conn.execute(
                "INSERT INTO dispatch_executions (proposal_id, call_id, created_at) VALUES (%s, %s, %s)",
                (proposal_id, call_id, now),
            )
            audit.record(
                conn,
                actor_user_id=actor_user_id,
                action=f"dispatch.{c.tool}",
                entity_type="task",
                entity_id=str(c.task_id),
                before=before,
                after={
                    **after,
                    "kind": kind,
                    "machine": c.machine,
                    "made_by": made_by,
                    "why_code": why,
                },
                idempotency_key=f"dispatch-{proposal_id}",
            )
    except AdapterError as e:
        with conn.transaction():
            _log(conn, run_id, c, made_by, why, proposal_id, "machine_refused", e.kind,
                 {"error": e.kind, "detail": e.detail[:300]}, now)  # fmt: skip
        return CallOutcome(c.tool, c.machine, c.task_id, "machine_refused", e.kind)
    return CallOutcome(c.tool, c.machine, c.task_id, "allowed", "carried out")


def _job_of(conn: psycopg.Connection, task_id: int) -> str:
    row = conn.execute(
        "SELECT o.order_number, j.line_no FROM tasks t JOIN jobs j ON j.id = t.job_id"
        " JOIN orders o ON o.id = j.order_id WHERE t.id = %s",
        (task_id,),
    ).fetchone()
    assert row is not None
    return job_key(row[0], row[1])


def _machine_seconds(conn: psycopg.Connection, task_id: int) -> int:
    row = conn.execute(
        "SELECT extract(epoch FROM planned_end - planned_start) FROM tasks WHERE id = %s",
        (task_id,),
    ).fetchone()
    return int(row[0]) if row and row[0] else 60


# --- Watch -------------------------------------------------------------------------------------


def poll_once(conn: psycopg.Connection, shop: Shop, now: datetime) -> list[tuple[int, str]]:
    """Check every running task that dispatch started; record the ones the machine has finished or
    failed. Returns (task id, new status). Machine text goes into the note as the machine's words."""
    rows = conn.execute(
        "SELECT t.id, m.code, o.order_number, j.line_no, t.actual_start FROM tasks t"
        " JOIN schedules s ON s.id = t.schedule_id AND s.status = 'approved'"
        " JOIN machines m ON m.id = t.machine_id JOIN jobs j ON j.id = t.job_id"
        " JOIN orders o ON o.id = j.order_id"
        " WHERE t.kind = 'machine' AND t.status = 'running' AND EXISTS ("
        "   SELECT 1 FROM dispatch_executions e JOIN dispatch_proposals p ON p.id = e.proposal_id"
        "   WHERE p.task_id = t.id AND p.action = 'start_task')"
    ).fetchall()
    done: list[tuple[int, str]] = []
    for task_id, machine, number, line_no, started in rows:
        adapter = shop.adapters.get(machine)
        if adapter is None:
            continue
        try:
            s = adapter.get_status()
        except AdapterError:
            continue  # no answer: look again next time
        ours = s.job in (None, job_key(number, line_no))
        finished = s.state == "done" or (s.state == "idle" and s.job is None)
        if s.state == "running" or not ours:
            continue
        if s.seconds is not None:
            source, seconds = "machine", s.seconds
        else:  # the protocol reports no time: code's watch, on the simulated clock
            source, seconds = "polled", int((now - started).total_seconds() * shop.speed)
        action: TaskAction
        if finished:
            action, mark = "done", TaskMark()
        elif s.state in ("failed", "offline"):
            note = (
                f"Machine reported: {s.message}"[:500]
                if s.message
                else "The machine reported a failure."
            )
            action, mark = "fail", TaskMark(failure_reason="other", failure_note=note)
        else:
            continue
        with conn.transaction():
            kind, before, after = apply_action(
                conn,
                None,
                int(task_id),
                action,
                now,
                mark,
                time_source=source,
                machine_seconds=seconds,
            )
            audit.record(
                conn,
                actor_user_id=None,
                action=f"dispatch.machine_{action}",
                entity_type="task",
                entity_id=str(task_id),
                before=before,
                after={**after, "kind": kind, "time_source": source, "machine_seconds": seconds},
                idempotency_key=None,
            )
        done.append((int(task_id), "done" if action == "done" else "failed"))
    return done
