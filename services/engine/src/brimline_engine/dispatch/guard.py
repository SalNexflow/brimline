"""The guard: decides whether one tool call may run (docs/DISPATCH_RULES.md, rules G01 to G10).

A pure function of a `Facts` snapshot that code builds from the database, the machine's adapter and the
independent checker (dispatch/facts.py). Facts hold ids, enumerated states, numbers and rule codes only:
no job name, note, file name, machine message or model reason ever reaches a verdict, so text written to
mislead the agent cannot change one (tested by changing every such text).
"""

from dataclasses import dataclass
from typing import Literal

Tool = Literal["get_status", "explain_error", "start_task", "stop_task"]
ACTIONS = ("start_task", "stop_task")
PROCEED_ROLES = frozenset({"planner", "operator"})


@dataclass(frozen=True)
class Call:
    tool: Tool
    machine: str
    task_id: int | None = None


@dataclass(frozen=True)
class TaskFacts:
    id: int
    kind: str  # 'machine' for a print or machining task
    status: str  # planned, running, done, failed
    schedule_id: int
    planned_machine: str
    earlier_done: bool  # every earlier task of its job is done
    running_on: str | None  # machine it runs on, when running


@dataclass(frozen=True)
class Facts:
    machine_known: bool  # the machine exists and is part of this dispatch's shop
    stop_supported: bool  # the protocol has a stop call
    approved: frozenset[tuple[str, int, str]]  # (action, task_id, machine) approved with Proceed
    approver_roles: frozenset[str]  # roles of the people who approved this call's action
    asked_by_role: str  # role of the person who asked for the dispatch
    executed: frozenset[tuple[str, int, str]]  # approved actions already carried out
    run_schedule_id: int  # the plan the proposals were made against
    approved_schedule_id: int | None  # the plan approved now
    task: TaskFacts | None
    machine_state: str | None  # from the adapter, asked by code; None: no answer in time
    plan_check_added: tuple[str, ...]  # checker rule codes the start would add (G06)
    grams_needed: int  # the job's grams (G07)
    grams_free: int  # stock now, less what running prints use


@dataclass(frozen=True)
class Verdict:
    allowed: bool
    code: str  # 'allowed' or the rule's code
    detail: str


def _no(code: str, detail: str) -> Verdict:
    return Verdict(False, code, detail)


def check(call: Call, f: Facts, *, require_approval: bool = True) -> Verdict:
    """The verdict on one call. `require_approval=False` is the pre-check of a proposal (G01, G02
    and the approver half of G08 cannot hold yet)."""
    if not f.machine_known:
        return _no("unknown", f"no machine {call.machine} in this dispatch")
    if call.tool in ("get_status", "explain_error"):
        return Verdict(True, "allowed", "read only")
    if f.task is None:
        return _no("unknown", "no such task")
    key = (call.tool, f.task.id, call.machine)
    if require_approval:
        if key not in f.approved:
            return _no("not_approved", "no Proceed covers this action")
        if key in f.executed:
            return _no("already_executed", "this approved action has already been carried out")
        if not f.approver_roles & PROCEED_ROLES:
            return _no("not_allowed", "only a planner or an operator may give Proceed")
    if f.asked_by_role != "planner":
        return _no("not_allowed", "only a planner may ask for a dispatch")
    if f.task.schedule_id != f.approved_schedule_id or f.run_schedule_id != f.approved_schedule_id:
        return _no("stale_plan", "the plan changed since this was proposed")
    t = f.task
    if call.tool == "start_task":
        if t.kind != "machine" or t.status != "planned":
            return _no("task_state", f"the task is {t.status}, not a planned machine task")
        if not t.earlier_done:
            return _no("task_state", "the job's earlier tasks are not done")
        if call.machine != t.planned_machine:
            return _no("task_state", f"the plan has this task on {t.planned_machine}")
    else:
        if t.status != "running" or t.running_on != call.machine:
            return _no("task_state", "the task is not running on this machine")
        if not f.stop_supported:
            return _no(
                "unsupported", "this machine's protocol has no stop call; stop it at the machine"
            )
    if f.machine_state is None:
        return _no("machine_state", "the machine did not answer in time")
    wanted = "idle" if call.tool == "start_task" else "running"
    if call.tool == "start_task" and f.machine_state not in ("idle", "done"):
        return _no("machine_state", f"the machine reports {f.machine_state}")
    if call.tool == "stop_task" and f.machine_state != wanted:
        return _no("machine_state", f"the machine reports {f.machine_state}")
    if call.tool == "start_task":
        if f.plan_check_added:
            return _no("plan_check", "the checker finds: " + ", ".join(f.plan_check_added))
        if f.grams_free < f.grams_needed:
            return _no("material_now", f"{f.grams_free} g free, the job needs {f.grams_needed} g")
    return Verdict(True, "allowed", "every rule holds")
