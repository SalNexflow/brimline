"""Tiny scheduling instances whose best answers are worked out by hand in the tests.

Durations are stripped down so the arithmetic stays visible: no prep, setup, cool-down or
finishing unless a case adds them; a machine task lasts quantity x minutes per part.
"""

from brimline_engine.scheduling.config import Durations, Weights
from brimline_engine.scheduling.model import Fixed, Instance, Job, Machine

BARE = Durations(
    prep_minutes=0,
    setup_minutes=0,
    changeover_minutes=30,
    finish_base_minutes=0,
    finish_minutes_per_part=0,
    cool_down_minutes={},
)
WEIGHTS = Weights(
    late_job=1000,
    tardiness_per_minute=10,
    changeover=600,
    finish_time_per_minute=1,
    unscheduled_job=1_000_000,
    rush_multiplier=3,
)
ALWAYS_OPEN = ((0, 10_000),)
PRINTER = Machine("M1", "fdm", frozenset({"PLA", "PETG"}), (256, 256, 256))
BIG = Machine("M2", "fdm", frozenset({"PLA", "PETG"}), (400, 400, 400))


def job(id_: str, arrival: int, minutes: int, due: int = 9_000, **kw: object) -> Job:
    base: dict[str, object] = {
        "id": id_,
        "arrival": arrival,
        "material": "PLA",
        "process": "fdm",
        "part_mm": (50, 50, 50),
        "quantity": 1,
        "minutes_per_part": minutes,
        "post_minutes_per_part": 0,
        "due": due,
        "rush": False,
    }
    base.update(kw)
    return Job(**base)  # type: ignore[arg-type]


def instance(
    *jobs: Job,
    machines: tuple[Machine, ...] = (PRINTER,),
    shifts: tuple[tuple[int, int], ...] = ALWAYS_OPEN,
    staff: int = 5,
    horizon: int = 10_000,
    fixed: tuple[Fixed, ...] = (),
) -> Instance:
    return Instance("case", horizon, machines, jobs, shifts, staff, fixed)


# Due-date order: A (60 min, due 100) arrives before B (50 min, due 70).
# Best: B then A -> B ends 50 (on time), A ends 110 (10 late). One late job, 10 minutes.
# First-come-first-served: A then B -> B ends 110 (40 late).
DUE_ORDER = instance(job("A", 1, 60, due=100), job("B", 2, 50, due=70))

# Changeovers: X1 (PLA), Y (PETG), X2 (PLA), 10 minutes each, 30-minute changeover.
# In arrival order: X1 0-10, Y 40-50, X2 80-90: 2 changeovers, finish 90.
# Best: X1, X2, Y -> 0-10, 10-20, 50-60: 1 changeover, finish 60.
CHANGEOVER = instance(job("X1", 1, 10), job("Y", 2, 10, material="PETG"), job("X2", 3, 10))
