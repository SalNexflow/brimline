"""Dispatch routes (M12): machine states, asking the dispatcher, Proceed (which then executes), and the
simulation's mode switch. The rules live in brimline_engine.dispatch; these only translate."""

from datetime import datetime
from typing import Annotated, Any, Literal

import psycopg
from fastapi import APIRouter, HTTPException, Path, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from brimline_engine import audit, idempotency
from brimline_engine.ai.clients import client_for
from brimline_engine.ai.config import models_config
from brimline_engine.ai.guard import VISITOR, demo_config, over_limit, spend
from brimline_engine.api.deps import Conn, CurrentSettings, CurrentUser, IdempotencyKey, Now
from brimline_engine.api.planning import Tz
from brimline_engine.dispatch import service
from brimline_engine.dispatch.runtime import Floor, sources
from brimline_engine.idempotency import IdempotencyConflictError
from brimline_engine.machines.config import machines_config
from brimline_engine.permissions import can
from brimline_engine.settings import Settings
from brimline_engine.text import SafeText

router = APIRouter(tags=["dispatch"])
RunId = Annotated[int, Path(ge=1)]
ERRORS: dict[type[Exception], int] = {
    service.NotFoundError: 404,
    service.ForbiddenError: 403,
    service.ConflictError: 409,
    IdempotencyConflictError: 409,
}
SIMULATED = (
    "Simulated machines: each adapter speaks its machine's protocol to a mock server. Untested on real"
    " hardware."
)


def _error(exc: Exception) -> HTTPException:
    status = ERRORS[type(exc)]
    return HTTPException(status, {404: "not found", 403: "not allowed"}.get(status, str(exc)))


def _floor(request: Request) -> Floor:
    floor: Floor | None = request.app.state.floor
    if floor is None:
        raise HTTPException(409, "no machines are connected (SIM_MACHINES is off)")
    return floor


def budget_reason(conn: psycopg.Connection, settings: Settings) -> str | None:
    """Why the model may not be called now (the hosted demo's daily budget), or None."""
    if not settings.demo_mode:
        return None
    return over_limit(spend(conn, VISITOR.get()), demo_config().budget)


class MachineInfo(service.MachineOut):
    docs: str
    docs_read: str


class ProposalView(BaseModel):
    id: int
    action: str
    task_id: int
    job: str
    machine: str
    reason: str  # the agent's words
    precheck: str
    precheck_detail: str
    approved: bool
    executed: bool


class CallView(BaseModel):
    made_by: str
    why_code: str
    tool: str
    args: dict[str, Any]
    verdict: str
    detail: str
    result: dict[str, Any] | None
    at: datetime


class RunView(BaseModel):
    id: int
    schedule_id: int
    proposed_by: str
    note: str
    created_at: datetime
    proposals: list[ProposalView]
    calls: list[CallView]


class DispatchOut(BaseModel):
    simulated_notice: str
    connected: bool
    machines: list[MachineInfo]
    runs: list[RunView]


@router.get("/dispatch")
def get_dispatch(conn: Conn, user: CurrentUser, request: Request) -> DispatchOut:
    """The machines as they report themselves now, and the latest dispatches with every proposal,
    approval, tool call and guard verdict."""
    if not can(user.actor, "dispatch.read"):
        raise HTTPException(403, "not allowed")
    floor: Floor | None = request.app.state.floor
    cfg = machines_config().by_code()
    machines = []
    if floor is not None:
        for m in service.machine_states(floor.shop, sources()):
            c = cfg[m.code]
            machines.append(
                MachineInfo(**m.model_dump(), docs=c.docs, docs_read=c.read.isoformat())
            )
    runs = []
    for rid, sid, by, note, at in conn.execute(
        "SELECT id, schedule_id, proposed_by, note, created_at FROM dispatch_runs"
        " ORDER BY id DESC LIMIT 5"
    ).fetchall():
        proposals = [
            ProposalView(
                id=r[0],
                action=r[1],
                task_id=r[2],
                job=f"{r[3]}-{r[4]}",
                machine=r[5],
                reason=r[6],
                precheck=r[7],
                precheck_detail=r[8],
                approved=r[9],
                executed=r[10],
            )
            for r in conn.execute(
                "SELECT p.id, p.action, p.task_id, o.order_number, j.line_no, p.machine_code,"
                "       p.reason, p.precheck, p.precheck_detail,"
                "       EXISTS (SELECT 1 FROM dispatch_approvals a WHERE a.proposal_id = p.id),"
                "       EXISTS (SELECT 1 FROM dispatch_executions e WHERE e.proposal_id = p.id)"
                " FROM dispatch_proposals p JOIN tasks t ON t.id = p.task_id"
                " JOIN jobs j ON j.id = t.job_id JOIN orders o ON o.id = j.order_id"
                " WHERE p.run_id = %s ORDER BY p.id",
                (rid,),
            ).fetchall()
        ]
        calls = [
            CallView(
                made_by=r[0],
                why_code=r[1],
                tool=r[2],
                args=r[3],
                verdict=r[4],
                detail=r[5],
                result=r[6],
                at=r[7],
            )
            for r in conn.execute(
                "SELECT made_by, why_code, tool, args, verdict, detail, result, created_at"
                " FROM dispatch_calls WHERE run_id = %s ORDER BY id",
                (rid,),
            ).fetchall()
        ]
        runs.append(RunView(id=rid, schedule_id=sid, proposed_by=by, note=note, created_at=at,
                            proposals=proposals, calls=calls))  # fmt: skip
    return DispatchOut(
        simulated_notice=SIMULATED, connected=floor is not None, machines=machines, runs=runs
    )


@router.post("/dispatch/runs", status_code=201)
def ask_dispatcher(
    request: Request,
    conn: Conn,
    user: CurrentUser,
    now: Now,
    key: IdempotencyKey,
    settings: CurrentSettings,
    tz: Tz,
) -> dict[str, Any]:
    """Ask the dispatcher for proposals. Nothing reaches a machine until a person presses Proceed."""
    floor = _floor(request)
    endpoint = "POST /dispatch/runs"
    stored = idempotency.claim(conn, user_id=user.actor.user_id, endpoint=endpoint, key=key,
                               req_hash="ask")  # fmt: skip
    if stored is not None:
        return stored.body
    try:
        run_id = service.propose(
            conn,
            user.actor,
            floor.shop,
            sources(),
            now,
            tz,
            client_for(settings.ai_mode, models_config().task("dispatch_propose").model),
            settings.ai_mode,
            budget_reason(conn, settings),
        )
    except tuple(ERRORS) as exc:
        conn.execute(
            "DELETE FROM idempotency_keys WHERE user_id = %s AND endpoint = %s AND key = %s",
            (user.actor.user_id, endpoint, key),
        )
        raise _error(exc) from None
    response = idempotency.StoredResponse(201, {"run_id": run_id})
    idempotency.store(
        conn, user_id=user.actor.user_id, endpoint=endpoint, key=key, response=response
    )
    return response.body


class ProceedIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    proposal_ids: list[int] = Field(min_length=1, max_length=12)


@router.post("/dispatch/runs/{run_id}/proceed")
def proceed(
    run_id: RunId,
    body: ProceedIn,
    request: Request,
    response: Response,
    conn: Conn,
    user: CurrentUser,
    now: Now,
    key: IdempotencyKey,
    settings: CurrentSettings,
    tz: Tz,
) -> dict[str, Any]:
    """Approve specific proposals, then carry them out: the agent issues the tool calls and the guard
    checks each one; when the agent cannot be used, code carries out exactly the approved actions."""
    floor = _floor(request)
    try:
        stored, replayed = service.proceed(conn, user.actor, run_id, body.proposal_ids, key, now)
    except tuple(ERRORS) as exc:
        raise _error(exc) from None
    outcomes = service.execute(
        conn,
        run_id,
        floor.shop,
        sources(),
        now,
        tz,
        client_for(settings.ai_mode, models_config().task("dispatch_execute").model),
        settings.ai_mode,
        budget_reason(conn, settings),
        user.actor.user_id,
    )
    if replayed:
        response.headers["Idempotent-Replayed"] = "true"
    return {**stored.body, "calls": [o.__dict__ for o in outcomes]}


class SimModeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["success", "failure", "slow", "unresponsive"]
    busy: bool = False
    message: SafeText = Field(default="", max_length=300)


@router.post("/machines/{code}/simulation")
def set_simulation(
    code: Annotated[str, Path(pattern=r"^[A-Z0-9-]{1,20}$")],
    body: SimModeIn,
    request: Request,
    conn: Conn,
    user: CurrentUser,
    key: IdempotencyKey,
) -> dict[str, Any]:
    """Simulation only: make a machine fail, slow down, stop answering, look busy, or report a message.
    For trying the guard; planners only, audited."""
    if not can(user.actor, "dispatch.ask"):
        raise HTTPException(403, "not allowed")
    floor = _floor(request)
    sim = floor.fleet.sims.get(code)
    if sim is None:
        raise HTTPException(404, "not found")
    sim.mode, sim.message = body.mode, body.message
    sim.external_job = "someone-elses-job" if body.busy else None
    audit.record(
        conn,
        actor_user_id=user.actor.user_id,
        action="machine.simulation",
        entity_type="machine",
        entity_id=code,
        before=None,
        after=body.model_dump(),
        idempotency_key=key,
    )
    return {"machine": code, **body.model_dump()}
