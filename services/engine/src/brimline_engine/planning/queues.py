"""Operator queues: the approved schedule's tasks, per machine, plus one queue for manual work.

Only the approved schedule is ever read here, and a database trigger keeps tasks of any other
schedule from existing, so an unapproved plan cannot reach an operator (two guards).

Rules for marking work, enforced here: a task starts only when the job's previous task is
done; a machine runs one task at a time; a task goes planned -> running -> done or failed and
never back. Times are the server's clock. Finishing a job's last task finishes the job (and the
order, when it was the last job); a failed task fails its job, which the next Plan day plans
again from the start.
"""

from datetime import datetime
from typing import Any, Literal

import psycopg
from pydantic import BaseModel, ConfigDict, Field

from brimline_engine import audit, idempotency
from brimline_engine.costing.store import record_outcome
from brimline_engine.materials.stock import take_for_print
from brimline_engine.permissions import Actor, can
from brimline_engine.planning.inputs import job_key
from brimline_engine.text import SafeText

TaskAction = Literal["start", "done", "fail"]
TaskStatus = Literal["planned", "running", "done", "failed", "cancelled"]


class NotFoundError(Exception):
    pass


class ForbiddenError(Exception):
    pass


class ConflictError(Exception):
    """Not allowed in the task's current state (409)."""


class InvalidError(Exception):
    """What was recorded does not fit the action or the task (422)."""


FailureReason = Literal[
    "warping", "bed_adhesion", "layer_shift", "clog", "spaghetti", "damaged_in_finishing", "other"
]


class TaskMark(BaseModel):
    """What the operator records with Done or Failed (M10). A failure needs its reason; grams are
    for print and machining tasks only and may be left out (the report then assumes the quote's)."""

    model_config = ConfigDict(extra="forbid")
    failure_reason: FailureReason | None = None
    failure_note: SafeText | None = Field(default=None, max_length=500)
    material_used_g: int | None = Field(default=None, gt=0, le=1_000_000)


def _check_mark(action: TaskAction, kind: str, mark: TaskMark) -> None:
    if action == "fail" and mark.failure_reason is None:
        raise InvalidError("say why it failed (failure_reason)")
    if action != "fail" and (mark.failure_reason or mark.failure_note):
        raise InvalidError("a reason is recorded only when a task fails")
    if mark.material_used_g is not None and (action == "start" or kind != "machine"):
        raise InvalidError("grams are recorded when a print or machining task ends")


class QueueTask(BaseModel):
    id: int
    kind: str
    status: TaskStatus
    job: str
    order_number: str
    part_name: str
    quantity: int
    material_code: str
    rush: bool
    planned_start: datetime
    planned_end: datetime
    actual_start: datetime | None
    actual_end: datetime | None
    can_start: bool
    waiting_for: str | None  # why it cannot start yet, in plain words
    attempt: int  # 2 or more: a reprint after a failed attempt


class Queue(BaseModel):
    machine: str | None  # None: manual work (prep, post-processing, finishing)
    name: str
    tasks: list[QueueTask]


class QueuesOut(BaseModel):
    time_zone: str
    schedule_version: int | None
    queues: list[Queue]
    can_update: bool


_ROWS = (
    "SELECT t.id, t.kind, t.status, o.order_number, j.line_no, j.part_name, j.quantity,"
    "       mat.code, o.rush, t.planned_start, t.planned_end, t.actual_start, t.actual_end,"
    "       m.code, m.name, t.job_id, t.seq,"
    # Attempt 2 or more is a reprint: the job failed before and was planned again (M10).
    "       1 + (SELECT count(*) FROM tasks f WHERE f.job_id = t.job_id AND f.status = 'failed')"
    " FROM tasks t JOIN schedules s ON s.id = t.schedule_id AND s.status = 'approved'"
    " JOIN jobs j ON j.id = t.job_id JOIN orders o ON o.id = j.order_id"
    " JOIN materials mat ON mat.id = j.material_id LEFT JOIN machines m ON m.id = t.machine_id"
    " WHERE t.status <> 'cancelled' ORDER BY t.planned_start, t.id"
)


def _blocker(
    row: tuple[Any, ...], by_job: dict[int, dict[int, str]], running_on: dict[str, int]
) -> str | None:
    status, machine, job_id, seq = row[2], row[13], row[15], row[16]
    if status != "planned":
        return None
    earlier = {s: st for s, st in by_job[job_id].items() if s < seq}
    open_ = [s for s, st in earlier.items() if st != "done"]
    if open_:
        return "the job's previous task is not done yet"
    if machine is not None and machine in running_on:
        return f"{machine} is busy"
    return None


def get_queues(conn: psycopg.Connection, actor: Actor, tz: str) -> QueuesOut:
    if not can(actor, "queue.read"):
        raise ForbiddenError("queue.read")
    version = conn.execute("SELECT version FROM schedules WHERE status = 'approved'").fetchone()
    rows = conn.execute(_ROWS).fetchall()
    by_job: dict[int, dict[int, str]] = {}
    running_on: dict[str, int] = {}
    for r in rows:
        by_job.setdefault(r[15], {})[r[16]] = r[2]
        if r[2] == "running" and r[13] is not None:
            running_on[r[13]] = r[0]
    machines = conn.execute("SELECT code, name FROM machines WHERE active ORDER BY code").fetchall()
    queues = {code: Queue(machine=code, name=name, tasks=[]) for code, name in machines}
    manual = Queue(machine=None, name="Manual work", tasks=[])
    may_update = can(actor, "task.update")
    for r in rows:
        waiting = _blocker(r, by_job, running_on)
        task = QueueTask(
            id=r[0],
            kind=r[1],
            status=r[2],
            job=job_key(r[3], r[4]),
            order_number=r[3],
            part_name=r[5],
            quantity=r[6],
            material_code=r[7],
            rush=r[8],
            planned_start=r[9],
            planned_end=r[10],
            actual_start=r[11],
            actual_end=r[12],
            can_start=may_update and r[2] == "planned" and waiting is None,
            waiting_for=waiting,
            attempt=r[17],
        )
        (queues[r[13]] if r[13] is not None else manual).tasks.append(task)
    return QueuesOut(
        time_zone=tz,
        schedule_version=None if version is None else int(version[0]),
        queues=[*queues.values(), manual],
        can_update=may_update,
    )


def act(
    conn: psycopg.Connection,
    actor: Actor,
    task_id: int,
    action: TaskAction,
    key: str,
    now: datetime,
    mark: TaskMark | None = None,
) -> tuple[idempotency.StoredResponse, bool]:
    if not can(actor, "task.update"):
        raise ForbiddenError("task.update")
    mark = mark or TaskMark()
    endpoint = f"POST /tasks/{task_id}/{action}"
    with conn.transaction():
        stored = idempotency.claim(
            conn,
            user_id=actor.user_id,
            endpoint=endpoint,
            key=key,
            # A plain action hashes as before M10, so a retry across that deploy still replays.
            req_hash=action if mark == TaskMark() else action + mark.model_dump_json(),
        )
        if stored is not None:
            return stored, True
        # Lock the task's schedule for sharing first: an approval of a new plan (which locks the
        # current one for update) then waits for this action, or this action waits for it and
        # sees the plan superseded. Either way no start can slip between them.
        found = conn.execute("SELECT schedule_id FROM tasks WHERE id = %s", (task_id,)).fetchone()
        if found is None:
            raise NotFoundError(str(task_id))
        locked = conn.execute(
            "SELECT status FROM schedules WHERE id = %s FOR SHARE", (found[0],)
        ).fetchone()
        assert locked is not None
        row = conn.execute(
            "SELECT t.status, t.job_id, t.seq, t.kind, t.machine_id, t.schedule_id,"
            "       t.actual_start, j.order_id, j.status, o.status"
            " FROM tasks t JOIN jobs j ON j.id = t.job_id JOIN orders o ON o.id = j.order_id"
            " WHERE t.id = %s FOR UPDATE OF t",
            (task_id,),
        ).fetchone()
        assert row is not None
        status, job_id, seq, kind, machine_id, schedule_id, a_start, order_id, j_st, o_st = row
        if locked[0] != "approved":
            raise ConflictError("this task belongs to a plan that is no longer the approved one")
        if "cancelled" in (j_st, o_st):
            raise ConflictError("this job or its order was cancelled")
        _check_mark(action, kind, mark)
        before = {"status": status}
        if action == "start":
            if status != "planned":
                raise ConflictError(f"only a planned task can start; this one is {status}")
            open_earlier = conn.execute(
                "SELECT count(*) FROM tasks WHERE schedule_id = %s AND job_id = %s AND seq < %s"
                " AND status <> 'done'",
                (schedule_id, job_id, seq),
            ).fetchone()
            assert open_earlier is not None
            if open_earlier[0]:
                raise ConflictError("the job's previous task is not done yet")
            if machine_id is not None:
                busy = conn.execute(
                    "SELECT count(*) FROM tasks WHERE schedule_id = %s AND machine_id = %s"
                    " AND status = 'running'",
                    (schedule_id, machine_id),
                ).fetchone()
                assert busy is not None
                if busy[0]:
                    raise ConflictError("the machine is already running another task")
            try:
                conn.execute(
                    "UPDATE tasks SET status = 'running', actual_start = %s WHERE id = %s",
                    (now, task_id),
                )
            except psycopg.errors.UniqueViolation:
                # The database's guard: someone started another task on this machine at the
                # same moment, and won (tasks_one_running_per_machine).
                raise ConflictError("the machine is already running another task") from None
            conn.execute(
                "UPDATE jobs SET status = 'in_progress' WHERE id = %s AND status <> 'in_progress'",
                (job_id,),
            )
            conn.execute(
                "UPDATE orders SET status = 'in_production', updated_at = %s"
                " WHERE id = %s AND status = 'open'",
                (now, order_id),
            )
            after: dict[str, Any] = {"status": "running", "actual_start": now.isoformat()}
        else:
            if status != "running":
                raise ConflictError(
                    f"only a running task can be marked {action}; this one is {status}"
                )
            new = "done" if action == "done" else "failed"
            end = max(now, a_start)  # the server clock never runs backwards for one task
            conn.execute(
                "UPDATE tasks SET status = %s, actual_end = %s, failure_reason = %s,"
                " failure_note = %s, material_used_g = %s WHERE id = %s",
                (
                    new,
                    end,
                    mark.failure_reason,
                    mark.failure_note,
                    mark.material_used_g,
                    task_id,
                ),
            )
            after = {
                "status": new,
                "actual_end": end.isoformat(),
                **mark.model_dump(exclude_none=True),
            }
            if kind == "machine":  # the print used its material: take it from stock (M9)
                taken = take_for_print(conn, task_id, actor.user_id, now)
                if taken is None:
                    # Nothing gives this job's grams, so stock would never go down (review of
                    # M9): the operator weighs it. The whole action is undone.
                    raise InvalidError(
                        "this job has no grams per part: record the grams used with this print"
                    )
                after["stock_taken_g"] = taken.grams
                after["stock_grams_assumed"] = taken.assumed
                if taken.missing:
                    after["stock_missing_g"] = taken.missing
            if new == "failed":
                conn.execute("UPDATE jobs SET status = 'failed' WHERE id = %s", (job_id,))
            else:
                left = conn.execute(
                    "SELECT count(*) FROM tasks WHERE schedule_id = %s AND job_id = %s"
                    " AND status <> 'done'",
                    (schedule_id, job_id),
                ).fetchone()
                assert left is not None
                if left[0] == 0:
                    conn.execute("UPDATE jobs SET status = 'done' WHERE id = %s", (job_id,))
                    record_outcome(conn, job_id, end)  # quoted versus actual (M10)
                    conn.execute(
                        "UPDATE orders SET status = 'done', updated_at = %s WHERE id = %s"
                        " AND NOT EXISTS (SELECT 1 FROM jobs WHERE order_id = %s"
                        "                 AND status NOT IN ('done', 'cancelled'))",
                        (now, order_id, order_id),
                    )
        audit.record(
            conn,
            actor_user_id=actor.user_id,
            action=f"task.{action}",
            entity_type="task",
            entity_id=str(task_id),
            before=before,
            after={**after, "kind": kind},
            idempotency_key=key,
        )
        response = idempotency.StoredResponse(200, {"id": task_id, "status": after["status"]})
        idempotency.store(
            conn, user_id=actor.user_id, endpoint=endpoint, key=key, response=response
        )
        return response, False
