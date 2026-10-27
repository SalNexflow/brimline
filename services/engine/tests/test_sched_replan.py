"""M6 scheduling: machine downtimes in every method, and CP-SAT's re-planning costs.
Hand-worked with the stripped-down durations of sched_cases (a machine task lasts quantity x
minutes per part; 30-minute changeover; shop always open)."""

from collections.abc import Callable

import pytest

from brimline_engine.checker import check_document
from brimline_engine.scheduling.baselines import edd, fcfs
from brimline_engine.scheduling.config import load_scheduler_config
from brimline_engine.scheduling.cpsat import solve
from brimline_engine.scheduling.export import document
from brimline_engine.scheduling.model import Downtime, Fixed, Instance, Previous, Schedule
from brimline_engine.scheduling.validation import InstanceError
from tests.sched_cases import BARE, BIG, PRINTER, WEIGHTS, instance, job
from tests.test_checker_mutations import BARE_RULES

CFG = load_scheduler_config().model_copy(update={"durations": BARE, "weights": WEIGHTS})
METHODS: dict[str, Callable[[Instance], Schedule]] = {
    "fcfs": lambda i: fcfs(i, BARE),
    "edd": lambda i: edd(i, BARE),
    "cpsat": lambda i: solve(i, CFG),
}


def with_(inst: Instance, **kw: object) -> Instance:
    fields = {f: getattr(inst, f) for f in inst.__dataclass_fields__}
    return Instance(**(fields | kw))


def machine_slot(s: Schedule, job_id: str) -> tuple[str, int, int]:
    plan = next(p for p in s.plans if p.job_id == job_id)
    slot = plan.slot("machine")
    assert slot is not None
    return (plan.machine, slot.start, slot.end)


@pytest.mark.parametrize("method", METHODS)
def test_nothing_runs_on_a_machine_while_it_is_down(method: str) -> None:
    # M1 is down 0-200; A (100 min) waits for it: 200-300. The checker agrees.
    inst = with_(instance(job("A", 1, 100)), downtimes=(Downtime("M1", 0, 200),))
    s = METHODS[method](inst)
    assert machine_slot(s, "A") == ("M1", 200, 300)
    assert check_document(document(inst, s), BARE_RULES).valid


@pytest.mark.parametrize("method", METHODS)
def test_a_downtime_needs_no_changeover_around_it(method: str) -> None:
    # A PETG job right after a downtime starts at its end, with no 30-minute gap.
    inst = with_(instance(job("A", 1, 100, material="PETG")), downtimes=(Downtime("M1", 0, 50),))
    assert machine_slot(METHODS[method](inst), "A") == ("M1", 50, 150)


@pytest.mark.parametrize("method", METHODS)
def test_work_goes_to_another_machine_while_one_is_down(method: str) -> None:
    # M1 down for a long time; BIG (M2) is free: A runs there from 0.
    inst = with_(
        instance(job("A", 1, 100), machines=(PRINTER, BIG)), downtimes=(Downtime("M1", 0, 5000),)
    )
    assert machine_slot(METHODS[method](inst), "A") == ("M2", 0, 100)


def test_a_fixed_task_on_a_machine_that_is_down_is_refused() -> None:
    # A print that was lost to the breakdown must not be fixed (planning code's job).
    inst = with_(
        instance(job("A", 1, 100), fixed=(Fixed("A", "M1", 0),)),
        downtimes=(Downtime("M1", 50, 80),),
    )
    with pytest.raises(InstanceError, match="while it is down"):
        edd(inst, BARE)


def test_replanning_an_unchanged_instance_moves_nothing() -> None:
    # Two identical machines, so without the approved plan either would do. With it, every job
    # stays exactly where it was.
    base = instance(job("A", 1, 100), job("B", 2, 100), job("C", 3, 50), machines=(PRINTER, BIG))
    approved = solve(base, CFG)
    previous = tuple(
        Previous(p.job_id, *machine_slot(approved, p.job_id)[:2], p.completion)
        for p in approved.plans
    )
    again = solve(with_(base, previous=previous), CFG)
    assert {p.job_id: machine_slot(again, p.job_id) for p in again.plans} == {
        p.job_id: machine_slot(approved, p.job_id) for p in approved.plans
    }


def test_a_job_stays_on_its_machine_when_it_can() -> None:
    # A was on M2 at 0 in the approved plan. M1 is just as good for A alone, but moving costs.
    inst = with_(
        instance(job("A", 1, 100), machines=(PRINTER, BIG)),
        previous=(Previous("A", "M2", 0, 100),),
    )
    assert machine_slot(solve(inst, CFG), "A") == ("M2", 0, 100)


def test_moving_is_worth_it_when_staying_would_be_late() -> None:
    # A was on M1 at 0, due 120. M1 is now down 0-200: staying means finishing at 300, 180 min
    # late (1000 + 10 x 180 = 2800, plus slip 200 x 5 = 1000). Moving to M2 costs 300. It moves.
    inst = with_(
        instance(job("A", 1, 100, due=120), machines=(PRINTER, BIG)),
        downtimes=(Downtime("M1", 0, 200),),
        previous=(Previous("A", "M1", 0, 100),),
    )
    assert machine_slot(solve(inst, CFG), "A") == ("M2", 0, 100)
