"""Each guard rule (docs/DISPATCH_RULES.md) on hand-made facts: one change from an allowed start breaks
exactly one rule, and the verdict names it."""

from dataclasses import replace

import pytest

from brimline_engine.dispatch.guard import Call, Facts, TaskFacts, check

TASK = TaskFacts(7, "machine", "planned", 3, "FDM-1", True, None)
OK = Facts(
    machine_known=True,
    stop_supported=True,
    approved=frozenset({("start_task", 7, "FDM-1")}),
    approver_roles=frozenset({"operator"}),
    asked_by_role="planner",
    executed=frozenset(),
    run_schedule_id=3,
    approved_schedule_id=3,
    task=TASK,
    machine_state="idle",
    plan_check_added=(),
    grams_needed=200,
    grams_free=200,
)
START = Call("start_task", "FDM-1", 7)


def test_an_approved_start_with_every_fact_right_is_allowed() -> None:
    assert check(START, OK).code == "allowed"


@pytest.mark.parametrize(
    ("change", "code"),
    [
        ({"machine_known": False}, "unknown"),
        ({"task": None}, "unknown"),
        ({"approved": frozenset()}, "not_approved"),
        ({"approved": frozenset({("start_task", 7, "FDM-2")})}, "not_approved"),
        ({"executed": frozenset({("start_task", 7, "FDM-1")})}, "already_executed"),
        ({"approver_roles": frozenset({"customer"})}, "not_allowed"),
        ({"asked_by_role": "operator"}, "not_allowed"),
        ({"approved_schedule_id": 4}, "stale_plan"),
        ({"run_schedule_id": 2}, "stale_plan"),
        ({"task": replace(TASK, status="running")}, "task_state"),
        ({"task": replace(TASK, earlier_done=False)}, "task_state"),
        ({"task": replace(TASK, kind="prep")}, "task_state"),
        ({"task": replace(TASK, planned_machine="FDM-2")}, "task_state"),
        ({"machine_state": "running"}, "machine_state"),
        ({"machine_state": "failed"}, "machine_state"),
        ({"machine_state": None}, "machine_state"),
        ({"plan_check_added": ("machine_overlap",)}, "plan_check"),
        ({"grams_free": 199}, "material_now"),
    ],
)
def test_each_rule_refuses_on_its_own(change: dict[str, object], code: str) -> None:
    v = check(START, replace(OK, **change))  # type: ignore[arg-type]
    assert (v.allowed, v.code) == (False, code)


def test_a_finished_machine_may_take_the_next_job() -> None:
    assert check(START, replace(OK, machine_state="done")).allowed


def test_the_precheck_skips_only_the_approval_rules() -> None:
    unapproved = replace(OK, approved=frozenset(), approver_roles=frozenset())
    assert check(START, unapproved, require_approval=False).allowed
    assert (
        check(START, replace(unapproved, grams_free=0), require_approval=False).code
        == "material_now"
    )


STOP_TASK = replace(TASK, status="running", running_on="FDM-1")
STOP_OK = replace(OK, approved=frozenset({("stop_task", 7, "FDM-1")}), task=STOP_TASK,
                  machine_state="running")  # fmt: skip
STOP = Call("stop_task", "FDM-1", 7)


@pytest.mark.parametrize(
    ("change", "code"),
    [
        ({}, "allowed"),
        ({"stop_supported": False}, "unsupported"),
        ({"task": TASK}, "task_state"),
        ({"machine_state": "idle"}, "machine_state"),
    ],
)
def test_stop_rules(change: dict[str, object], code: str) -> None:
    assert check(STOP, replace(STOP_OK, **change)).code == code  # type: ignore[arg-type]


def test_reads_need_no_approval_but_a_known_machine() -> None:
    nothing = replace(OK, approved=frozenset(), task=None)
    assert check(Call("get_status", "FDM-1"), nothing).allowed
    assert check(Call("explain_error", "FDM-1"), nothing).allowed
    assert (
        check(Call("get_status", "FDM-9"), replace(nothing, machine_known=False)).code == "unknown"
    )
