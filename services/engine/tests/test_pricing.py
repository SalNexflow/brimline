"""Pricing, checked against totals worked out by hand (hard rule 10).

Rates used below (invented, like everything in the shop):
  setup 1500 cents per line; PETG-BLACK 4 c/g; PLA-WHITE 3 c/g; RESIN-GREY 12 c/g;
  fdm 6 c/min; resin 9 c/min; sanding 200 c/part; painting 350 c/part; rush 150 %.
"""

from datetime import date

import pytest

from brimline_engine.pricing import (
    LineInput,
    PriceRules,
    PricingPending,
    price_quote,
    rush_total,
)

RULES = PriceRules(
    rule_set_id=1,
    effective_from=date(2026, 10, 25),
    setup_cents=1500,
    rush_multiplier_percent=150,
    material_cents_per_gram={"PETG-BLACK": 4, "PLA-WHITE": 3, "RESIN-GREY": 12},
    machine_cents_per_minute={"fdm": 6, "resin": 9, "cnc": 45},
    post_process_cents_per_part={"sanding": 200, "painting": 350},
)

PHONE_STANDS = LineInput(
    part_name="Phone stand",
    quantity=20,
    material_code="PETG-BLACK",
    process="fdm",
    grams_per_part=35,
    minutes_per_part=90,
    post_processing=("sanding",),
)


def test_one_line_by_hand() -> None:
    # material 20 x 35 g x 4 c = 2800; machine 20 x 90 min x 6 c = 10800;
    # sanding 20 x 200 = 4000; setup 1500. Line total 19100.
    result = price_quote([PHONE_STANDS], rush=False, rules=RULES)
    assert not isinstance(result, PricingPending)
    line = result.lines[0]
    assert (line.material_cents, line.machine_cents, line.post_process_cents, line.setup_cents) == (
        2800,
        10800,
        4000,
        1500,
    )
    assert line.total_cents == 19100
    assert (result.subtotal_cents, result.rush_surcharge_cents, result.total_cents) == (
        19100,
        0,
        19100,
    )
    assert result.rule_set_id == 1


def test_two_lines_and_rush_by_hand() -> None:
    trays = LineInput(
        part_name="Model tray",
        quantity=6,
        material_code="RESIN-GREY",
        process="resin",
        grams_per_part=18,
        minutes_per_part=40,
        post_processing=("sanding", "painting"),
    )
    # trays: material 6 x 18 x 12 = 1296; machine 6 x 40 x 9 = 2160; post 6 x (200+350) = 3300;
    # setup 1500. Line 8256. Subtotal 19100 + 8256 = 27356.
    # Rush 150 %: 27356 x 1.5 = 41034, so surcharge 13678.
    result = price_quote([PHONE_STANDS, trays], rush=True, rules=RULES)
    assert not isinstance(result, PricingPending)
    assert [line.total_cents for line in result.lines] == [19100, 8256]
    assert (result.subtotal_cents, result.rush_surcharge_cents, result.total_cents) == (
        27356,
        13678,
        41034,
    )


@pytest.mark.parametrize(
    ("subtotal", "percent", "expected"),
    [
        (100, 150, 150),
        (101, 150, 152),  # 151.5 rounds half up to 152
        (333, 150, 500),  # 499.5 -> 500
        (1, 100, 1),
        (0, 150, 0),
        (12345, 125, 15431),  # 15431.25 -> 15431
    ],
)
def test_rush_rounds_half_up_to_whole_cents(subtotal: int, percent: int, expected: int) -> None:
    assert rush_total(subtotal, percent) == expected


def test_missing_inputs_leave_the_price_pending_and_say_why() -> None:
    incomplete = LineInput(
        part_name="Bracket",
        quantity=None,
        material_code="PLA-WHITE",
        process="fdm",
        grams_per_part=None,
        minutes_per_part=12,
        post_processing=(),
    )
    result = price_quote([PHONE_STANDS, incomplete], rush=False, rules=RULES)
    assert result == PricingPending(missing=["line 2: quantity", "line 2: grams per part"])


def test_a_material_without_a_rate_is_pending_not_free() -> None:
    gold = LineInput(
        part_name="Trophy",
        quantity=1,
        material_code="GOLD",
        process="fdm",
        grams_per_part=10,
        minutes_per_part=10,
        post_processing=(),
    )
    assert price_quote([gold], rush=False, rules=RULES) == PricingPending(
        missing=["line 1: no price rule for material GOLD"]
    )


def test_an_unknown_post_processing_kind_is_pending() -> None:
    odd = LineInput(**{**PHONE_STANDS.__dict__, "post_processing": ("gold_leaf",)})
    assert price_quote([odd], rush=False, rules=RULES) == PricingPending(
        missing=["line 1: no price rule for post-processing gold_leaf"]
    )


def test_a_quote_with_no_lines_is_pending() -> None:
    assert price_quote([], rush=False, rules=RULES) == PricingPending(missing=["no lines"])


def test_pricing_takes_no_model_output() -> None:
    # Hard rule 1, made structural: the only inputs are typed lines, a rush flag, and rules
    # loaded from the database. There is no parameter through which model text could arrive.
    import inspect

    assert list(inspect.signature(price_quote).parameters) == ["lines", "rush", "rules"]
