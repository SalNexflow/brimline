"""The CP-SAT model on tiny instances whose optimum is worked out by hand (tests/sched_cases.py).
Every case runs on both variants: they must agree on these small, exactly solvable instances."""

from itertools import pairwise

import pytest

from brimline_engine.scheduling.baselines import edd
from brimline_engine.scheduling.config import Durations, SchedulerConfig, load_scheduler_config
from brimline_engine.scheduling.cpsat import Variant, solve
from brimline_engine.scheduling.generator import generate
from brimline_engine.scheduling.metrics import evaluate
from brimline_engine.scheduling.model import Fixed, Schedule, Slot
from brimline_engine.shop_config import load_shop_config
from tests.sched_cases import BARE, BIG, CHANGEOVER, DUE_ORDER, PRINTER, WEIGHTS, instance, job

BASE = load_scheduler_config()
VARIANTS: list[Variant] = ["simple", "circuit"]


def config(durations: Durations = BARE) -> SchedulerConfig:
    return BASE.model_copy(update={"durations": durations, "weights": WEIGHTS})


def machine_slots(schedule: Schedule) -> dict[str, tuple[str, int, int]]:
    out = {}
    for plan in schedule.plans:
        slot = plan.slot("machine")
        assert slot is not None
        out[plan.job_id] = (plan.machine, slot.start, slot.end)
    return out


@pytest.mark.parametrize("variant", VARIANTS)
def test_due_date_order_is_found(variant: Variant) -> None:
    s = solve(DUE_ORDER, config(), variant=variant)
    assert s.info["status"] == "OPTIMAL"
    assert machine_slots(s) == {"B": ("M1", 0, 50), "A": ("M1", 50, 110)}
    m = evaluate(DUE_ORDER, s, WEIGHTS)
    assert (m.late_jobs, m.total_lateness_minutes) == (1, 10)


@pytest.mark.parametrize("variant", VARIANTS)
def test_grouping_materials_saves_a_changeover(variant: Variant) -> None:
    s = solve(CHANGEOVER, config(), variant=variant)
    m = evaluate(CHANGEOVER, s, WEIGHTS)
    # By hand: X1, X2 back to back, one 30-minute changeover, Y: finish 10 + 10 + 30 + 10 = 60.
    assert (m.changeovers, m.finish_time) == (1, 60)
    slots = sorted(machine_slots(s).values(), key=lambda v: v[1])
    gaps = [b[1] - a[2] for a, b in pairwise(slots)]
    assert sorted(gaps) == [0, 30]


@pytest.mark.parametrize("variant", VARIANTS)
def test_overnight_print_and_next_morning_packing(variant: Variant) -> None:
    d = Durations(**{**BARE.model_dump(), "finish_base_minutes": 30})
    shifts = ((0, 480), (1440, 1920))
    ok = instance(job("P", 1, 600, release=470), shifts=shifts, horizon=2880)
    plan = solve(ok, config(d), variant=variant).plans[0]
    assert plan.slots == (Slot("machine", 470, 1070), Slot("finish", 1440, 1470))
    late = instance(job("P", 1, 600, release=485), shifts=shifts, horizon=2880)
    s = solve(late, config(d), variant=variant)
    assert (s.plans, s.unscheduled) == ((), ("P",))  # reported, not dropped


@pytest.mark.parametrize("variant", VARIANTS)
def test_a_job_can_use_the_gap_before_a_fixed_task(variant: Variant) -> None:
    inst = instance(job("G", 1, 100), job("F", 2, 50), fixed=(Fixed("F", "M1", 200),))
    slots = machine_slots(solve(inst, config(), variant=variant))
    assert slots["F"] == ("M1", 200, 250)  # never moves
    assert slots["G"] == ("M1", 0, 100)  # fits before it, unlike the greedy baselines


@pytest.mark.parametrize("variant", VARIANTS)
def test_one_person_means_manual_tasks_queue(variant: Variant) -> None:
    d = Durations(**{**BARE.model_dump(), "prep_minutes": 30})
    two = instance(job("A", 1, 100), job("B", 2, 100), machines=(PRINTER, BIG), staff=1)
    preps = sorted(
        (slot for p in solve(two, config(d), variant=variant).plans if (slot := p.slot("prep"))),
        key=lambda slot: slot.start,
    )
    assert preps == [Slot("prep", 0, 30), Slot("prep", 30, 60)]


@pytest.mark.parametrize("variant", VARIANTS)
def test_an_idle_machine_and_an_impossible_job(variant: Variant) -> None:
    # Two machines, one job: one machine stays empty. Plus a job no machine can make.
    inst = instance(job("A", 1, 10), job("Z", 2, 10, material="NYLON"), machines=(PRINTER, BIG))
    s = solve(inst, config(), variant=variant)
    assert [p.job_id for p in s.plans] == ["A"]
    assert s.unscheduled == ("Z",)


def test_same_seed_same_schedule() -> None:
    shop = load_shop_config()
    inst = generate(5, 20, shop, BASE)
    hint = edd(inst, BASE.durations)
    first = solve(inst, BASE, hint=hint, deterministic_time=2.0)
    second = solve(inst, BASE, hint=hint, deterministic_time=2.0)
    assert first.plans == second.plans and first.unscheduled == second.unscheduled
    assert first.info["hinted"] is True


def test_cpsat_is_never_worse_than_its_edd_hint_on_a_generated_instance() -> None:
    inst = generate(1, 20, load_shop_config(), BASE)
    hint = edd(inst, BASE.durations)
    s = solve(inst, BASE, hint=hint, deterministic_time=3.0)
    assert evaluate(inst, s, BASE.weights).objective <= evaluate(inst, hint, BASE.weights).objective
