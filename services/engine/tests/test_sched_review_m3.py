"""Regression tests for the M3 adversarial review findings (DEFECT_LOG #19-#24).
Inputs are the reviewer's triggering cases; expected answers are worked out by hand.
Every case runs on all four methods, because they must obey exactly the same rules."""

from collections.abc import Callable

import pytest
from ortools.sat.python import cp_model

from brimline_engine.scheduling.baselines import edd, fcfs
from brimline_engine.scheduling.config import SchedulerConfig, load_scheduler_config
from brimline_engine.scheduling.cpsat import solve
from brimline_engine.scheduling.generator import generate
from brimline_engine.scheduling.metrics import evaluate
from brimline_engine.scheduling.model import Fixed, Instance, Job, Schedule
from brimline_engine.scheduling.validation import InstanceError
from brimline_engine.shop_config import load_shop_config
from tests.sched_cases import BARE, WEIGHTS, instance, job

BASE = load_scheduler_config()
CFG: SchedulerConfig = BASE.model_copy(update={"durations": BARE, "weights": WEIGHTS})
METHODS: dict[str, Callable[[Instance], Schedule]] = {
    "fcfs": lambda i: fcfs(i, BARE),
    "edd": lambda i: edd(i, BARE),
    "simple": lambda i: solve(i, CFG, variant="simple"),
    "circuit": lambda i: solve(i, CFG, variant="circuit"),
}


def machine_slots(s: Schedule) -> dict[str, tuple[str, int, int]]:
    out = {}
    for p in s.plans:
        slot = p.slot("machine")
        assert slot is not None
        out[p.job_id] = (p.machine, slot.start, slot.end)
    return out


@pytest.mark.parametrize("method", METHODS)
def test_nothing_overlaps_a_fixed_task(method: str) -> None:
    # #19: fixed A runs 500-600, fixed B 0-100 (both PLA). C needs 450 minutes: the gap 100-500
    # is only 400, so C must go after A: 600-1050.
    inst = instance(
        job("A", 1, 100),
        job("B", 2, 100),
        job("C", 3, 450),
        fixed=(Fixed("A", "M1", 500), Fixed("B", "M1", 0)),
    )
    assert machine_slots(METHODS[method](inst))["C"] == ("M1", 600, 1050)


@pytest.mark.parametrize("method", METHODS)
def test_overlapping_fixed_tasks_are_an_error_not_a_schedule(method: str) -> None:
    inst = instance(
        job("A", 1, 100), job("B", 2, 100), fixed=(Fixed("A", "M1", 0), Fixed("B", "M1", 50))
    )
    with pytest.raises(InstanceError, match="overlap"):
        METHODS[method](inst)


@pytest.mark.parametrize("method", METHODS)
def test_fixed_tasks_back_to_back_with_different_materials_are_accepted(method: str) -> None:
    # #20: reality skipped the changeover gap; that is a fact, not a reason to drop everything.
    inst = instance(
        job("A", 1, 100),
        job("B", 2, 100, material="PETG"),
        job("C", 3, 10),
        fixed=(Fixed("A", "M1", 0), Fixed("B", "M1", 100)),
    )
    s = METHODS[method](inst)
    assert s.unscheduled == ()
    slots = machine_slots(s)
    assert (slots["A"], slots["B"]) == (("M1", 0, 100), ("M1", 100, 200))
    assert slots["C"] == ("M1", 230, 240)  # PLA after PETG: the 30-minute changeover applies


@pytest.mark.parametrize("method", METHODS)
def test_a_fixed_task_past_the_horizon_still_blocks_its_machine(method: str) -> None:
    # #21: A is running 0-1500 on the only machine; the horizon ends at 1000. C cannot use M1.
    inst = instance(job("A", 1, 1500), job("C", 2, 50), horizon=1000, fixed=(Fixed("A", "M1", 0),))
    s = METHODS[method](inst)
    assert machine_slots(s) == {"A": ("M1", 0, 1500)}
    assert s.unscheduled == ("C",)


@pytest.mark.parametrize("method", METHODS)
def test_an_overdue_job_is_still_scheduled(method: str) -> None:
    # #22: a job already overdue at planning time (due -9500) must be planned, as soon as possible.
    inst = instance(job("A", 1, 600, due=-9500))
    s = METHODS[method](inst)
    assert machine_slots(s) == {"A": ("M1", 0, 600)}
    assert evaluate(inst, s, WEIGHTS).total_lateness_minutes == 600 + 9500


@pytest.mark.parametrize("method", METHODS)
def test_idle_time_before_a_waiting_job_is_used(method: str) -> None:
    # #23: A waits for material until 1000; B can run first, in the idle time 0-100.
    inst = instance(job("A", 1, 100, due=2000, release=1000), job("B", 2, 100, due=3000))
    assert machine_slots(METHODS[method](inst)) == {"A": ("M1", 1000, 1100), "B": ("M1", 0, 100)}


def test_unscheduled_jobs_count_as_late_or_unscheduled() -> None:
    # #24: B can never fit (20,000 minutes in a 10,000 horizon). It must not improve "late".
    inst = instance(job("A", 1, 100, due=50), job("B", 2, 20_000, due=100))
    m = evaluate(inst, edd(inst, BARE), WEIGHTS)
    assert (m.late_jobs, m.unscheduled, m.late_or_unscheduled) == (1, 1, 2)


def test_a_job_with_no_machine_work_is_rejected() -> None:
    with pytest.raises(ValueError, match="at least 1"):
        Job("Z", 1, "PLA", "fdm", (1, 1, 1), 1, 0, 0, 100, False)


def test_the_simple_model_says_its_optimum_is_for_a_stand_in() -> None:
    inst = instance(job("A", 1, 10))
    assert solve(inst, CFG, variant="simple").info["objective"] == "stand-in changeovers"
    assert solve(inst, CFG, variant="circuit").info["objective"] == "exact"


def test_a_short_limit_on_80_jobs_still_returns_a_complete_schedule() -> None:
    # Review finding 2: with a partial hint, the circuit model at 1 s returned UNKNOWN and every
    # job unscheduled. With a complete hint it must do at least as well as EDD.
    inst = generate(1, 80, load_shop_config(), BASE)
    hint = edd(inst, BASE.durations)
    s = solve(inst, BASE, variant="circuit", hint=hint, deterministic_time=1.0)
    assert len(s.unscheduled) <= len(hint.unscheduled)
    assert evaluate(inst, s, BASE.weights).objective <= evaluate(inst, hint, BASE.weights).objective


def test_when_cpsat_finds_nothing_it_returns_the_hint_and_says_so(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Run the real search, then report "nothing found", as a real time-out would.
    real_solve = cp_model.CpSolver.solve

    def times_out(self: cp_model.CpSolver, model: cp_model.CpModel) -> object:
        real_solve(self, model)
        return cp_model.UNKNOWN

    monkeypatch.setattr(cp_model.CpSolver, "solve", times_out)
    inst = instance(job("A", 1, 10), job("B", 2, 10))
    hint = edd(inst, BARE)
    s = solve(inst, CFG, hint=hint)
    assert s.plans == hint.plans
    assert (s.info["status"], s.info["fallback"]) == ("UNKNOWN", "edd")
