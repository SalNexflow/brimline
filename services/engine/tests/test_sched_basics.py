"""Calendar, durations and metrics, against values worked out by hand from config/scheduler.toml."""

import pytest

from brimline_engine.scheduling.calendar import (
    earliest_machine_start,
    earliest_manual_start,
    horizon_minutes,
    manual_start_ranges,
    shift_windows,
)
from brimline_engine.scheduling.config import Weights, load_scheduler_config
from brimline_engine.scheduling.durations import eligible_machines, fits, task_durations
from brimline_engine.scheduling.metrics import evaluate
from brimline_engine.scheduling.model import Instance, Job, JobPlan, Machine, Schedule, Slot

CFG = load_scheduler_config()
WINDOWS = shift_windows(CFG.shifts)


def job(id_: str = "J1", **kw: object) -> Job:
    base: dict[str, object] = {
        "id": id_,
        "arrival": 1,
        "material": "PETG-BLACK",
        "process": "fdm",
        "part_mm": (100, 80, 40),
        "quantity": 20,
        "minutes_per_part": 90,
        "post_minutes_per_part": 0,
        "due": 5000,
        "rush": False,
    }
    base.update(kw)
    return Job(**base)  # type: ignore[arg-type]


# --- Shifts ---------------------------------------------------------------------------------


def test_shift_windows_by_hand() -> None:
    # Minute 0 = Monday 08:00. Mon-Fri 08:00-17:00 = [day*1440, day*1440 + 540).
    # Saturday (day 5) 09:00-13:00: 5*1440 - 480 + 540 = 7260 to 7500. Sunday: none.
    assert WINDOWS[:6] == (
        (0, 540),
        (1440, 1980),
        (2880, 3420),
        (4320, 4860),
        (5760, 6300),
        (7260, 7500),
    )
    assert WINDOWS[6] == (10080, 10620)  # the second Monday
    assert len(WINDOWS) == 12  # two weeks of six working days
    assert horizon_minutes(CFG.shifts) == 14 * 1440


@pytest.mark.parametrize(
    ("t", "expected"),
    [(0, 0), (535, 535), (539, 539), (540, 1440), (-5, 0), (6300, 7260), (20000, None)],
)
def test_a_machine_task_starts_inside_a_shift_but_may_run_on(t: int, expected: int | None) -> None:
    assert earliest_machine_start(t, WINDOWS) == expected


@pytest.mark.parametrize(
    ("t", "duration", "expected"),
    [
        (500, 30, 500),  # 08:20 + 30 min ends 08:50... in horizon minutes 530 <= 540: fits
        (510, 30, 510),  # ends exactly at 17:00: fits
        (535, 30, 1440),  # 16:55 is too late for a 30-minute manual task: next morning
        (0, 600, None),  # longer than any shift: never fits
        (7259, 240, 7260),  # Saturday's 4-hour shift fits a 240-minute task exactly
    ],
)
def test_a_manual_task_must_fit_inside_one_shift(
    t: int, duration: int, expected: int | None
) -> None:
    assert earliest_manual_start(t, duration, WINDOWS) == expected


def test_manual_start_ranges_leave_room_for_the_task() -> None:
    assert manual_start_ranges(30, ((0, 540), (1440, 1980)))[0] == (0, 510)
    assert manual_start_ranges(600, ((0, 540),)) == []


# --- Durations and eligibility ----------------------------------------------------------------


def test_durations_by_hand() -> None:
    # machine: setup 15 + 20 parts x 90 min + fdm cool-down 20 = 1835. finish: 10 + 20 x 1 = 30.
    assert task_durations(job(), CFG.durations) == {"prep": 15, "machine": 1835, "finish": 30}
    # Post-processing 5 min per part for 20 parts = 100; CNC has no cool-down: 15 + 20 x 90 = 1815.
    assert task_durations(job(process="cnc", post_minutes_per_part=5), CFG.durations) == {
        "prep": 15,
        "machine": 1815,
        "post": 100,
        "finish": 30,
    }


SMALL = Machine("FDM-1", "fdm", frozenset({"PETG-BLACK", "PLA-BLACK"}), (256, 256, 256))
LARGE = Machine("FDM-4", "fdm", frozenset({"PETG-BLACK"}), (350, 350, 400))
RESIN = Machine("RESIN-1", "resin", frozenset({"RESIN-GREY"}), (218, 123, 235))


def test_a_part_may_be_turned_to_fit() -> None:
    assert fits(job(part_mm=(40, 250, 100)), SMALL)  # 250 fits along any 256 side
    tall = job(part_mm=(300, 100, 50))
    assert not fits(tall, SMALL)
    assert fits(tall, LARGE)  # 300 fits the 350 or 400 side
    assert eligible_machines(tall, (SMALL, LARGE, RESIN)) == [LARGE]


def test_material_and_process_must_match() -> None:
    assert not fits(job(material="PLA-WHITE"), SMALL)
    assert not fits(job(process="resin", material="RESIN-GREY"), SMALL)
    assert fits(job(process="resin", material="RESIN-GREY", part_mm=(100, 100, 100)), RESIN)


# --- Metrics ---------------------------------------------------------------------------------

WEIGHTS = Weights(
    late_job=1000,
    tardiness_per_minute=10,
    changeover=600,
    finish_time_per_minute=1,
    unscheduled_job=1_000_000,
    rush_multiplier=3,
)


def test_metrics_and_objective_by_hand() -> None:
    a = job("A", material="PLA-BLACK", due=100)
    b = job("B", due=200, rush=True)
    c = job("C", material="PLA-BLACK", due=1000)
    inst = Instance("t", 2000, (SMALL, LARGE), (a, b, c), ((0, 2000),), staff=1)
    schedule = Schedule(
        "hand",
        (
            JobPlan("A", "FDM-1", (Slot("machine", 0, 100),)),  # on time (100 <= 100)
            JobPlan("B", "FDM-1", (Slot("machine", 130, 230),)),  # rush, 30 min late
            JobPlan("C", "FDM-1", (Slot("machine", 260, 300),)),  # on time
        ),
        unscheduled=("D",),
    )
    m = evaluate(inst, schedule, WEIGHTS)
    assert (m.scheduled, m.unscheduled, m.late_jobs, m.rush_late_jobs) == (3, 1, 1, 1)
    assert m.total_lateness_minutes == 30
    assert m.changeovers == 2  # PLA -> PETG -> PLA on FDM-1
    assert m.finish_time == 300
    # busy 100 + 100 + 40 = 240 over 2 machines x 300 minutes = 0.4
    assert m.utilisation == pytest.approx(0.4)
    # late B: 1000 x 3; lateness 30 x 10 x 3 = 900; changeovers 2 x 600; finish 300; unscheduled 1e6
    assert m.objective == 3000 + 900 + 1200 + 300 + 1_000_000
