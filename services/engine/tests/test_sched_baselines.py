"""Baselines on tiny instances, against schedules worked out by hand (see tests/sched_cases.py)."""

from brimline_engine.scheduling.baselines import edd, fcfs
from brimline_engine.scheduling.config import Durations
from brimline_engine.scheduling.metrics import evaluate
from brimline_engine.scheduling.model import Fixed, Slot
from tests.sched_cases import BARE, BIG, CHANGEOVER, DUE_ORDER, PRINTER, WEIGHTS, instance, job


def machine_slots(schedule: object) -> dict[str, tuple[str, int, int]]:
    out = {}
    for plan in schedule.plans:  # type: ignore[attr-defined]
        slot = plan.slot("machine")
        out[plan.job_id] = (plan.machine, slot.start, slot.end)
    return out


def test_fcfs_follows_arrival_and_edd_follows_due_dates() -> None:
    f = fcfs(DUE_ORDER, BARE)
    e = edd(DUE_ORDER, BARE)
    assert machine_slots(f) == {"A": ("M1", 0, 60), "B": ("M1", 60, 110)}
    assert machine_slots(e) == {"B": ("M1", 0, 50), "A": ("M1", 50, 110)}
    fm, em = evaluate(DUE_ORDER, f, WEIGHTS), evaluate(DUE_ORDER, e, WEIGHTS)
    assert (fm.late_jobs, fm.total_lateness_minutes) == (1, 40)
    assert (em.late_jobs, em.total_lateness_minutes) == (1, 10)


def test_a_changeover_adds_thirty_minutes_between_materials() -> None:
    s = fcfs(CHANGEOVER, BARE)
    assert machine_slots(s) == {"X1": ("M1", 0, 10), "Y": ("M1", 40, 50), "X2": ("M1", 80, 90)}
    m = evaluate(CHANGEOVER, s, WEIGHTS)
    assert (m.changeovers, m.finish_time) == (2, 90)


def test_print_runs_overnight_but_manual_work_waits_for_the_next_shift() -> None:
    d = Durations(**{**BARE.model_dump(), "finish_base_minutes": 30})
    shifts = ((0, 480), (1440, 1920))
    # Material arrives at 470: the 600-minute print starts at 470 (inside the shift) and ends
    # at 1070, in the night. Packing (30 min) waits for the next shift: 1440-1470.
    on_time = instance(job("P", 1, 600, release=470), shifts=shifts, horizon=2880)
    plan = fcfs(on_time, d).plans[0]
    assert plan.slots == (Slot("machine", 470, 1070), Slot("finish", 1440, 1470))
    # Material at 485: the shift is over, so printing starts next morning at 1440 and ends at
    # 2040; no shift is left for packing within the 2-day horizon: reported, not dropped.
    too_late = instance(job("P", 1, 600, release=485), shifts=shifts, horizon=2880)
    s = fcfs(too_late, d)
    assert (s.plans, s.unscheduled) == ((), ("P",))


def test_one_person_means_manual_tasks_queue() -> None:
    d = Durations(**{**BARE.model_dump(), "prep_minutes": 30})
    two = instance(job("A", 1, 100), job("B", 2, 100), machines=(PRINTER, BIG), staff=1)
    plans = {p.job_id: p for p in fcfs(two, d).plans}
    assert plans["A"].slot("prep") == Slot("prep", 0, 30)
    assert plans["B"].slot("prep") == Slot("prep", 30, 60)  # the only person was busy
    assert plans["B"].machine == "M2"  # M1 is busy until 130; M2 is free at 60


def test_a_part_goes_only_where_it_fits() -> None:
    tall = instance(job("T", 1, 10, part_mm=(300, 50, 50)), machines=(PRINTER, BIG))
    assert fcfs(tall, BARE).plans[0].machine == "M2"


def test_a_fixed_task_keeps_its_place() -> None:
    inst = instance(job("G", 1, 100), job("F", 2, 50), fixed=(Fixed("F", "M1", 200),))
    slots = machine_slots(fcfs(inst, BARE))
    assert slots["F"] == ("M1", 200, 250)
    assert slots["G"] == ("M1", 250, 350)  # placed after the fixed task, never moving it
