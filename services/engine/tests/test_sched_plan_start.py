"""M5: planning happens at a moment (`plan_start`), and fixed tasks carry their real end.
Every method must obey both, and the checker must enforce both (R18, fixed end). Hand-worked."""

from collections.abc import Callable

import pytest

from brimline_engine.checker import check_document
from brimline_engine.scheduling.baselines import edd, fcfs
from brimline_engine.scheduling.config import load_scheduler_config
from brimline_engine.scheduling.cpsat import solve
from brimline_engine.scheduling.export import document
from brimline_engine.scheduling.model import Fixed, Instance, Schedule
from brimline_engine.scheduling.validation import InstanceError
from tests.sched_cases import BARE, WEIGHTS, instance, job
from tests.test_checker_mutations import BARE_RULES

CFG = load_scheduler_config().model_copy(update={"durations": BARE, "weights": WEIGHTS})
METHODS: dict[str, Callable[[Instance], Schedule]] = {
    "fcfs": lambda i: fcfs(i, BARE),
    "edd": lambda i: edd(i, BARE),
    "cpsat": lambda i: solve(i, CFG),
}


def with_plan_start(inst: Instance, minute: int) -> Instance:
    return Instance(
        inst.name,
        inst.horizon,
        inst.machines,
        inst.jobs,
        inst.shifts,
        inst.staff,
        inst.fixed,
        minute,
    )


def machine_slots(s: Schedule) -> dict[str, tuple[int, int]]:
    out = {}
    for p in s.plans:
        slot = p.slot("machine")
        assert slot is not None
        out[p.job_id] = (slot.start, slot.end)
    return out


@pytest.mark.parametrize("method", METHODS)
def test_nothing_starts_before_the_moment_of_planning(method: str) -> None:
    # Planning at minute 300: A (100 min) can start at 300 at the earliest, not at 0.
    inst = with_plan_start(instance(job("A", 1, 100)), 300)
    s = METHODS[method](inst)
    assert machine_slots(s) == {"A": (300, 400)}
    assert check_document(document(inst, s), BARE_RULES).valid


@pytest.mark.parametrize("method", METHODS)
def test_a_running_task_keeps_its_real_times(method: str) -> None:
    # A started at 0 and is expected to end at 250 (its formula says 100: it is running late).
    # B (PLA, same material) on the only machine therefore starts at 250, not at 100.
    fixed = (Fixed("A", "M1", 0, 250),)
    inst = with_plan_start(instance(job("A", 1, 100), job("B", 2, 50), fixed=fixed), 200)
    s = METHODS[method](inst)
    assert machine_slots(s) == {"A": (0, 250), "B": (250, 300)}
    assert check_document(document(inst, s), BARE_RULES).valid


@pytest.mark.parametrize("method", METHODS)
def test_a_finished_task_that_ended_early_frees_its_machine(method: str) -> None:
    # A was done in 40 minutes (formula 100). With planning at 40, B can start at 40.
    fixed = (Fixed("A", "M1", 0, 40),)
    inst = with_plan_start(instance(job("A", 1, 100), job("B", 2, 50), fixed=fixed), 40)
    assert machine_slots(METHODS[method](inst))["B"] == (40, 90)


def test_a_fixed_task_must_end_after_it_starts() -> None:
    inst = instance(job("A", 1, 100), fixed=(Fixed("A", "M1", 50, 50),))
    with pytest.raises(InstanceError, match="not after its start"):
        edd(inst, BARE)


def test_the_checker_refuses_a_task_planned_before_the_moment_of_planning() -> None:
    inst = instance(job("A", 1, 100))
    d = document(inst, edd(inst, BARE))  # A at 0-100
    d["instance"]["plan_start"] = 1
    assert check_document(d, BARE_RULES).codes() == {"before_plan_start"}


def test_the_checker_uses_the_fixed_end_for_the_tasks_length() -> None:
    fixed = (Fixed("A", "M1", 0, 250),)
    inst = instance(job("A", 1, 100), fixed=fixed)
    d = document(inst, edd(inst, BARE))
    assert check_document(d, BARE_RULES).valid
    d["plan"]["jobs"][0]["tasks"][0]["end"] = 100  # the formula length, not the real one
    assert check_document(d, BARE_RULES).codes() == {"wrong_duration"}
