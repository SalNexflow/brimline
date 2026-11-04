"""Connectivity routes (M12b): each machine's connection, derived by code from recorded polls, and a
person's "Test connection" (one read-only status call). Same access as Dispatch: planners and operators."""

from datetime import datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, HTTPException, Path, Request
from pydantic import BaseModel

from brimline_engine import audit, idempotency
from brimline_engine.api.deps import Conn, CurrentSettings, CurrentUser, IdempotencyKey, Now
from brimline_engine.api.dispatch import SIMULATED
from brimline_engine.api.planning import Tz
from brimline_engine.dispatch.runtime import Floor, sources
from brimline_engine.idempotency import IdempotencyConflictError
from brimline_engine.machines import connectivity
from brimline_engine.permissions import can

router = APIRouter(tags=["connectivity"])
MachineCode = Annotated[str, Path(pattern=r"^[A-Z0-9-]{1,20}$")]


class HistoryOut(BaseModel):
    at: datetime
    source: str  # poll | test
    ok: bool
    response_ms: int
    slow: bool


class MachineConnectivityOut(BaseModel):
    code: str
    protocol: str
    source: str  # official | community (where the protocol's description comes from)
    simulated_mode: str  # the simulator's behaviour: success | slow | unresponsive | failure
    state: connectivity.ConnectionState
    last_ok_at: datetime | None
    last_response_ms: int | None
    last_error: str  # what Brimline saw
    last_error_at: datetime | None
    answered: int
    taken: int
    fault: str
    machine_says: str  # untrusted: shown labelled, never obeyed
    history: list[HistoryOut]


class Thresholds(BaseModel):
    checked: str
    poll_seconds: float
    slow_ms: int
    slow_window: int
    unreachable_after: int
    stale_seconds: int
    uptime_minutes: int
    test_every_seconds: int


class ConnectivityOut(BaseModel):
    simulated_notice: str
    connected: bool
    now: datetime
    time_zone: str
    thresholds: Thresholds
    machines: list[MachineConnectivityOut]


class ConnectionTestOut(BaseModel):
    machine: str
    at: datetime
    ok: bool
    response_ms: int
    state: str | None
    error: str
    machine_says: str  # untrusted


def _floor(request: Request) -> Floor:
    floor: Floor | None = request.app.state.floor
    if floor is None:
        raise HTTPException(409, "no machines are connected (SIM_MACHINES is off)")
    return floor


@router.get("/connectivity")
def get_connectivity(
    conn: Conn, user: CurrentUser, request: Request, now: Now, settings: CurrentSettings, tz: Tz
) -> ConnectivityOut:
    if not can(user.actor, "dispatch.read"):
        raise HTTPException(403, "not allowed")
    cfg = connectivity.connectivity_config()
    floor: Floor | None = request.app.state.floor
    machines = []
    if floor is not None:
        adapters = dict(sorted(floor.shop.adapters.items()))
        summaries = connectivity.summarize(conn, list(adapters), now, cfg)
        origin = sources()
        for code, adapter in adapters.items():
            s = summaries[code]
            machines.append(
                MachineConnectivityOut(
                    code=code,
                    protocol=adapter.protocol,
                    source=origin.get(code, "official"),
                    simulated_mode=floor.fleet.sims[code].mode,
                    state=s.state,
                    last_ok_at=s.last_ok_at,
                    last_response_ms=s.last_response_ms,
                    last_error=s.last_error,
                    last_error_at=s.last_error_at,
                    answered=s.answered,
                    taken=s.taken,
                    fault=s.fault,
                    machine_says=s.machine_says,
                    history=[HistoryOut(**h.__dict__) for h in s.history],
                )
            )
    return ConnectivityOut(
        simulated_notice=SIMULATED,
        connected=floor is not None,
        now=now,
        time_zone=tz,
        thresholds=Thresholds(
            checked=cfg.checked.isoformat(),
            poll_seconds=cfg.demo_poll_seconds if settings.demo_mode else cfg.poll_seconds,
            slow_ms=cfg.slow_ms,
            slow_window=cfg.slow_window,
            unreachable_after=cfg.unreachable_after,
            stale_seconds=cfg.stale_seconds,
            uptime_minutes=cfg.uptime_minutes,
            test_every_seconds=cfg.test_every_seconds,
        ),
        machines=machines,
    )


@router.post("/machines/{code}/connection-tests")
def test_connection(
    code: MachineCode,
    request: Request,
    conn: Conn,
    user: CurrentUser,
    key: IdempotencyKey,
    now: Now,
) -> ConnectionTestOut:
    """One read-only status call, now. Recorded like a poll, audited, and at most once per user and
    machine every `test_every_seconds`. A replay of the same key returns the first answer and calls
    nothing. Two steps: take the rate-limit slot (committed), call the machine with no transaction
    open, then record the answer, the audit row and the stored response together."""
    if not can(user.actor, "dispatch.read"):
        raise HTTPException(403, "not allowed")
    adapter = _floor(request).shop.adapters.get(code)
    if adapter is None:
        raise HTTPException(404, "not found")
    cfg = connectivity.connectivity_config()
    uid = user.actor.user_id
    endpoint = f"POST /machines/{code}/connection-tests"
    with conn.transaction():
        done = conn.execute(
            "SELECT request_hash, response_body FROM idempotency_keys"
            " WHERE user_id = %s AND endpoint = %s AND key = %s",
            (uid, endpoint, key),
        ).fetchone()
        if done is not None and done[1] is not None:
            return ConnectionTestOut.model_validate(done[1])  # a replay calls nothing
        # The slot is taken only if this person's last test of this machine is old enough; a second
        # request at the same moment waits for the first's row and then finds it too recent.
        taken = conn.execute(
            "INSERT INTO connection_test_slots AS s (user_id, machine_code, taken_at)"
            " VALUES (%s, %s, %s) ON CONFLICT (user_id, machine_code) DO UPDATE"
            " SET taken_at = EXCLUDED.taken_at WHERE s.taken_at <= %s RETURNING 1",
            (uid, code, now, now - timedelta(seconds=cfg.test_every_seconds)),
        ).fetchone()
        if taken is None:
            last = conn.execute(
                "SELECT taken_at FROM connection_test_slots WHERE user_id = %s AND machine_code = %s",
                (uid, code),
            ).fetchone()
            since = 0 if last is None else int((now - last[0]).total_seconds())
            wait = max(1, cfg.test_every_seconds - since)
            raise HTTPException(429, f"{code} was tested a moment ago; try again in {wait} s.")
    result = connectivity.probe(adapter)
    out = ConnectionTestOut(
        machine=code,
        at=now,
        ok=result.ok,
        response_ms=result.response_ms,
        state=result.state,
        error=result.error,
        machine_says=result.machine_says,
    )
    try:
        with conn.transaction():
            stored = idempotency.claim(
                conn, user_id=uid, endpoint=endpoint, key=key, req_hash="test"
            )
            if stored is not None:  # the same key finished meanwhile: its answer, not a second row
                return ConnectionTestOut.model_validate(stored.body)
            connectivity.record(conn, code, result, now, tested_by=uid)
            audit.record(
                conn,
                actor_user_id=uid,
                action="machine.test_connection",
                entity_type="machine",
                entity_id=code,
                before=None,
                after={
                    "ok": result.ok,
                    "response_ms": result.response_ms,
                    "state": result.state,
                    "error_kind": result.error_kind,
                },
                idempotency_key=key,
            )
            idempotency.store(
                conn,
                user_id=uid,
                endpoint=endpoint,
                key=key,
                response=idempotency.StoredResponse(200, out.model_dump(mode="json")),
            )
    except IdempotencyConflictError as exc:
        raise HTTPException(409, str(exc)) from None
    return out
