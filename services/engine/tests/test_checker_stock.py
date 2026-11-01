"""Hand-worked cases for the stock rule R20 `material_short` and its R17 items (M9).

Same small test rules as test_checker_cases.py: a job like A is prep 10, machine 100, finish 10.
Grams are chosen so the level can be worked out in your head; each case says it.
"""

from typing import Any

import pytest

from brimline_engine.checker import check_document
from tests.test_checker_cases import RULES, doc, job, std


def stocked(
    d: dict[str, Any], stock: dict[str, int], deliveries: tuple[tuple[str, int, int], ...] = ()
) -> dict[str, Any]:
    d["instance"]["stock"] = stock
    d["instance"]["deliveries"] = [{"material": m, "at": at, "grams": g} for m, at, g in deliveries]
    return d


def g(id_: str, grams: int, **kw: object) -> dict[str, Any]:
    return job(id_, grams_per_part=grams, **kw)


def short(d: dict[str, Any]) -> set[str]:
    r = check_document(d, RULES)
    return {v.job for v in r.violations if v.code == "material_short" and v.job}


def codes(d: dict[str, Any]) -> set[str]:
    return check_document(d, RULES).codes()


def test_enough_stock_is_valid() -> None:
    # A uses 1 x 300 g at minute 10; stock 300 -> level 0 at 10, never below.
    assert codes(stocked(doc([g("A", 300)], [std("A", "M1", 0)]), {"PLA": 300})) == set()


def test_one_gram_too_few_is_short() -> None:
    # Stock 299, A takes 300 at 10 -> level -1.
    d = stocked(doc([g("A", 300)], [std("A", "M1", 0)]), {"PLA": 299})
    r = check_document(d, RULES)
    assert r.codes() == {"material_short"}
    assert r.violations[0].job == "A" and "1 g short" in r.violations[0].detail


def test_quantity_multiplies_grams() -> None:
    # 2 parts x 150 g = 300 g; machine 2 x 100 = 200 min (setup 0) -> machine 10-210.
    a = g("A", 150, quantity=2)
    p = {
        "job_id": "A",
        "machine": "M1",
        "tasks": [
            {"kind": "prep", "start": 0, "end": 10},
            {"kind": "machine", "start": 10, "end": 210},
            {"kind": "finish", "start": 210, "end": 220},
        ],
    }
    assert short(stocked(doc([a], [p]), {"PLA": 300})) == set()
    assert short(stocked(doc([a], [p]), {"PLA": 299})) == {"A"}


def test_a_delivery_at_the_start_minute_counts_one_minute_later_does_not() -> None:
    # Stock 0; A starts its machine task at 10.
    on_time = stocked(doc([g("A", 300)], [std("A", "M1", 0)]), {"PLA": 0}, (("PLA", 10, 300),))
    late = stocked(doc([g("A", 300)], [std("A", "M1", 0)]), {"PLA": 0}, (("PLA", 11, 300),))
    assert short(on_time) == set()
    assert short(late) == {"A"}


def test_a_material_not_in_stock_has_none() -> None:
    assert short(stocked(doc([g("A", 1)], [std("A", "M1", 0)]), {"PETG": 5000})) == {"A"}


def test_two_jobs_at_the_same_minute_share_the_level() -> None:
    # A and B both start machines at 10 (M1, M2): 200 + 200 g from 300 -> level -100 at 10.
    # Both start while the level is below zero, so both are reported.
    d = stocked(
        doc([g("A", 200), g("B", 200)], [std("A", "M1", 0), std("B", "M2", 0)]), {"PLA": 300}
    )
    assert short(d) == {"A", "B"}


def test_the_later_job_is_the_one_short() -> None:
    # A at 10 takes 200 (level 100), B at 130 takes 200 (level -100): only B.
    d = stocked(
        doc([g("A", 200), g("B", 200)], [std("A", "M1", 0), std("B", "M1", 120)]), {"PLA": 300}
    )
    assert short(d) == {"B"}


def test_a_delivery_between_two_jobs_covers_the_second() -> None:
    # Stock 200: A at 10 -> 0. Delivery 200 at 100 -> 200. B at 130 -> 0.
    d = stocked(
        doc([g("A", 200), g("B", 200)], [std("A", "M1", 0), std("B", "M1", 120)]),
        {"PLA": 200},
        (("PLA", 100, 200),),
    )
    assert short(d) == set()


def test_order_of_use_matters_not_only_the_total() -> None:
    # Total supply 400 = total use 400, but A at 10 needs 300 with only 100 on hand.
    d = stocked(
        doc([g("A", 300), g("B", 100)], [std("A", "M1", 0), std("B", "M1", 120)]),
        {"PLA": 100},
        (("PLA", 100, 300),),
    )
    assert short(d) == {"A"}


def test_only_the_short_material_is_reported() -> None:
    d = stocked(
        doc(
            [g("A", 100), g("B", 100, material="PETG")],
            [std("A", "M1", 0), std("B", "M2", 0)],
        ),
        {"PLA": 100, "PETG": 99},
    )
    assert short(d) == {"B"}


def test_unscheduled_and_fixed_jobs_use_nothing() -> None:
    # F is fixed (running since 10 on M1): its material was taken before the stock was stated.
    # U is unscheduled. Stock 100 covers only A on M2.
    fixed = ({"job_id": "F", "machine": "M1", "start": 10},)
    f_plan = {
        "job_id": "F",
        "machine": "M1",
        "tasks": [
            {"kind": "machine", "start": 10, "end": 110},
            {"kind": "finish", "start": 110, "end": 120},
        ],
    }
    d = stocked(
        doc(
            [job("F"), g("U", 5000), g("A", 100)],
            [f_plan, std("A", "M2", 0)],
            unscheduled=("U",),
            fixed=fixed,
        ),
        {"PLA": 100},
    )
    r = check_document(d, RULES)
    assert r.codes() == set()


def test_no_stock_section_means_no_rule() -> None:
    assert codes(doc([g("A", 10**6)], [std("A", "M1", 0)])) == set()


@pytest.mark.parametrize(
    ("stock", "deliveries", "grams"),
    [
        (None, [("PLA", 0, 100)], 100),  # deliveries without stock
        ({"PLA": -1}, [], 100),  # negative stock
        ({"PLA": 0}, [("PLA", 5, 0)], 100),  # a zero-gram delivery
        ({"PLA": 100}, [], 0),  # grams_per_part below 1
        ({"PLA": 100}, [], None),  # stock but the job has no grams
    ],
)
def test_impossible_stock_instances(
    stock: dict[str, int] | None, deliveries: list[tuple[str, int, int]], grams: int | None
) -> None:
    a = job("A") if grams is None else g("A", grams)
    d = doc([a], [std("A", "M1", 0)])
    if stock is not None:
        d["instance"]["stock"] = stock
    d["instance"]["deliveries"] = [
        {"material": m, "at": at, "grams": gr} for m, at, gr in deliveries
    ]
    assert codes(d) == {"bad_instance"}


def test_unscheduled_job_is_suspicious_only_after_its_material_arrives() -> None:
    # U needs 300 g; stock 0, delivery 300 at 6000 (Friday 4am-ish, before the 7-day horizon).
    # It could still fit after 6000, so it is suspicious; without the delivery it is not.
    with_delivery = stocked(
        doc([g("U", 300)], [], unscheduled=("U",)), {"PLA": 0}, (("PLA", 6000, 300),)
    )
    r = check_document(with_delivery, RULES)
    assert [w.job for w in r.warnings] == ["U"]
    # Witness machine start is the first shift minute >= 6000 + prep: Friday shift [5760, 6300),
    # prep would be 5760-5770, but the material is free from 6000, so the machine starts at 6000.
    assert "from 6000" in r.warnings[0].detail
    without = stocked(doc([g("U", 300)], [], unscheduled=("U",)), {"PLA": 0})
    assert check_document(without, RULES).warnings == ()


def test_a_later_planned_use_keeps_an_unscheduled_job_waiting() -> None:
    # Stock 300 now; A (planned at Friday 5770) takes 300. U (300 g) taking the stock before
    # Friday would leave A short, so the material is never free for U: no warning.
    a_plan = std("A", "M1", 5760)
    d = stocked(doc([g("A", 300), g("U", 300)], [a_plan], unscheduled=("U",)), {"PLA": 300})
    assert check_document(d, RULES).warnings == ()
