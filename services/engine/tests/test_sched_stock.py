"""Material stock in every scheduling method (M9), on tiny instances worked out by hand.

Bare durations (tests/sched_cases.py): a machine task lasts quantity x minutes per part and
nothing else; one shift always open. Every schedule is also passed to the independent checker.
"""

from collections.abc import Callable
from dataclasses import replace

import pytest

from brimline_engine.checker import check_document
from brimline_engine.scheduling.baselines import edd, fcfs
from brimline_engine.scheduling.cpsat import solve
from brimline_engine.scheduling.export import document
from brimline_engine.scheduling.model import Delivery, Fixed, Instance, Schedule
from brimline_engine.scheduling.validation import InstanceError
from tests.sched_cases import BIG, PRINTER, instance, job
from tests.test_checker_mutations import BARE_CFG, BARE_RULES
from tests.test_sched_plan_start import machine_slots

METHODS: dict[str, Callable[[Instance], Schedule]] = {
    "fcfs": lambda i: fcfs(i, BARE_CFG.durations),
    "edd": lambda i: edd(i, BARE_CFG.durations),
    "cpsat": lambda i: solve(i, BARE_CFG),
}
TWO = (PRINTER, BIG)


def stocked(inst: Instance, stock: dict[str, int], *deliveries: Delivery) -> Instance:
    return replace(inst, stock=tuple(sorted(stock.items())), deliveries=deliveries)


def run(method: str, inst: Instance) -> Schedule:
    s = METHODS[method](inst)
    result = check_document(document(inst, s), BARE_RULES)
    assert result.valid, result.violations
    return s


@pytest.mark.parametrize("method", METHODS)
def test_the_second_job_waits_for_the_delivery(method: str) -> None:
    # Two free machines, A and B 100 min, 300 g each. Stock 300, 300 more at minute 500:
    # one starts at 0, the other at 500 (not at 0, which it would without the stock limit).
    inst = stocked(
        instance(
            job("A", 1, 100, grams_per_part=300), job("B", 2, 100, grams_per_part=300), machines=TWO
        ),
        {"PLA": 300},
        Delivery("PLA", 500, 300),
    )
    starts = sorted(start for start, _ in machine_slots(run(method, inst)).values())
    assert starts == [0, 500]


@pytest.mark.parametrize("method", METHODS)
def test_without_a_stock_limit_both_start_at_once(method: str) -> None:
    inst = instance(
        job("A", 1, 100, grams_per_part=300), job("B", 2, 100, grams_per_part=300), machines=TWO
    )
    assert sorted(s for s, _ in machine_slots(run(method, inst)).values()) == [0, 0]


@pytest.mark.parametrize("method", METHODS)
def test_two_jobs_share_what_is_there_at_once(method: str) -> None:
    # 2 parts x 100 g = 200 g and 100 g: together 300 = the stock, so both start at 0.
    inst = stocked(
        instance(
            job("A", 1, 50, quantity=2, grams_per_part=100),
            job("B", 2, 100, grams_per_part=100),
            machines=TWO,
        ),
        {"PLA": 300},
    )
    assert sorted(s for s, _ in machine_slots(run(method, inst)).values()) == [0, 0]


@pytest.mark.parametrize("method", METHODS)
def test_material_that_never_comes_leaves_the_job_unscheduled(method: str) -> None:
    # 0 g of PETG and no delivery: P cannot run; A (PLA, enough) runs at 0.
    inst = stocked(
        instance(
            job("A", 1, 100, grams_per_part=10),
            job("P", 2, 100, material="PETG", grams_per_part=10),
        ),
        {"PLA": 10},
    )
    s = run(method, inst)
    assert s.unscheduled == ("P",)
    assert machine_slots(s) == {"A": (0, 100)}
    # The checker agrees nothing could have been done: no "suspicious" warning.
    assert check_document(document(inst, s), BARE_RULES).warnings == ()


@pytest.mark.parametrize("method", METHODS)
def test_a_running_print_takes_nothing_more(method: str) -> None:
    # F is running on M1 since 0 (its material was taken already); A needs all 300 g and runs
    # on M2 at 0. If F counted, A would be short.
    inst = stocked(
        instance(
            job("F", 1, 100, grams_per_part=300),
            job("A", 2, 100, grams_per_part=300),
            machines=TWO,
            fixed=(Fixed("F", "M1", 0),),
        ),
        {"PLA": 300},
    )
    assert machine_slots(run(method, inst))["A"] == (0, 100)


@pytest.mark.parametrize("method", METHODS)
def test_a_later_job_does_not_take_what_an_earlier_placed_one_needs(method: str) -> None:
    # One machine. A (due 100, 300 g) and B (due 9000, 300 g); stock 300, 300 more at 1000.
    # A takes the stock at 0; B must wait for the delivery at 1000 even though M1 is free
    # from 100.
    inst = stocked(
        instance(
            job("A", 1, 100, due=100, grams_per_part=300), job("B", 2, 100, grams_per_part=300)
        ),
        {"PLA": 300},
        Delivery("PLA", 1000, 300),
    )
    assert machine_slots(run(method, inst)) == {"A": (0, 100), "B": (1000, 1100)}


def test_cpsat_gives_scarce_material_to_the_job_that_would_be_late() -> None:
    # First come first served gives the 300 g to A (arrived first, due late) and B (due 150)
    # waits for the delivery at 500: B late by 450. CP-SAT gives it to B: A waits, still on time.
    inst = stocked(
        instance(
            job("A", 1, 100, due=9000, grams_per_part=300),
            job("B", 2, 100, due=150, grams_per_part=300),
            machines=TWO,
        ),
        {"PLA": 300},
        Delivery("PLA", 500, 300),
    )
    first_come = machine_slots(run("fcfs", inst))
    assert first_come["A"][0] == 0 and first_come["B"][0] == 500
    best = machine_slots(run("cpsat", inst))
    assert best["B"][0] == 0 and best["A"][0] == 500


def test_stock_instances_must_be_complete() -> None:
    with pytest.raises(InstanceError, match="no grams"):
        fcfs(stocked(instance(job("A", 1, 100)), {"PLA": 5}), BARE_CFG.durations)
    with pytest.raises(InstanceError, match="deliveries without stock"):
        fcfs(
            replace(instance(job("A", 1, 100)), deliveries=(Delivery("PLA", 0, 1),)),
            BARE_CFG.durations,
        )
    with pytest.raises(InstanceError, match="negative"):
        fcfs(stocked(instance(job("A", 1, 100, grams_per_part=1)), {"PLA": -1}), BARE_CFG.durations)


def test_the_export_carries_stock_only_when_there_is_some() -> None:
    plain = document(instance(job("A", 1, 100)), Schedule("x", (), ("A",)))
    assert "stock" not in plain["instance"] and "grams_per_part" not in plain["instance"]["jobs"][0]
    inst = stocked(instance(job("A", 1, 100, grams_per_part=7)), {"PLA": 5}, Delivery("PLA", 60, 9))
    doc = document(inst, Schedule("x", (), ("A",)))["instance"]
    assert doc["stock"] == {"PLA": 5}
    assert doc["deliveries"] == [{"material": "PLA", "at": 60, "grams": 9}]
    assert doc["jobs"][0]["grams_per_part"] == 7
