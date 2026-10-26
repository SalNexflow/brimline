"""Scheduler-side metric definitions fixed after the M4 review (DEFECT_LOG #27).
Hand-worked values; the checker has the same cases in test_checker_cases.py."""

import pytest

from brimline_engine.scheduling.metrics import evaluate
from brimline_engine.scheduling.model import Fixed, JobPlan, Schedule, Slot
from tests.sched_cases import WEIGHTS, instance, job


def test_fixed_back_to_back_tasks_count_no_changeover() -> None:
    inst = instance(
        job("A", 1, 100),
        job("B", 2, 100, material="PETG"),
        fixed=(Fixed("A", "M1", 0), Fixed("B", "M1", 100)),
    )
    s = Schedule(
        "hand",
        (
            JobPlan("A", "M1", (Slot("machine", 0, 100),)),
            JobPlan("B", "M1", (Slot("machine", 100, 200),)),
        ),
        (),
    )
    assert evaluate(inst, s, WEIGHTS).changeovers == 0


def test_an_unscheduled_jobs_fixed_task_is_in_the_material_sequence() -> None:
    inst = instance(
        job("A", 1, 100), job("B", 2, 100, material="PETG"), fixed=(Fixed("A", "M1", 0),)
    )
    s = Schedule("hand", (JobPlan("B", "M1", (Slot("machine", 130, 230),)),), ("A",))
    assert evaluate(inst, s, WEIGHTS).changeovers == 1


def test_utilisation_counts_only_time_from_minute_zero() -> None:
    # Fixed since -1000 for 1100 minutes: 100 minutes after minute 0, one machine, finish 100.
    inst = instance(job("A", 1, 1100), fixed=(Fixed("A", "M1", -1000),))
    s = Schedule("hand", (JobPlan("A", "M1", (Slot("machine", -1000, 100),)),), ())
    assert evaluate(inst, s, WEIGHTS).utilisation == pytest.approx(1.0)
