"""Quoted versus actual (M10): costs, the sign test and the under-quote flag. Every expected value
is worked out by hand in the comments, not taken from the code's output (hard rule 10)."""

from datetime import UTC, datetime
from fractions import Fraction

import pytest

from brimline_engine.costing.config import FlagRule
from brimline_engine.costing.outcome import (
    Attempt,
    Estimate,
    Rates,
    estimated_cents,
    machine_cents,
    outcome,
)
from brimline_engine.costing.report import JobRow, build, sign_test_p, summarise

RATES = Rates(setup_cents=1500, material_cents_per_gram=7, machine_cents_per_minute=5)
TEN_STANDS = Estimate(quantity=10, grams_per_part=20, minutes_per_part=60)
RULE = FlagRule(threshold_ratio=1.15, min_jobs=5, alpha=0.05)
T = datetime(2026, 10, 1, tzinfo=UTC)


def test_the_estimate_uses_the_quotes_own_formula() -> None:
    # 1500 setup + 10 x (20 g x 7 c + 60 min x 5 c) = 1500 + 10 x 440 = 5900 cents.
    assert estimated_cents(TEN_STANDS, RATES) == 5900


def test_machine_time_rounds_half_up_in_cents() -> None:
    # 90 s at 5 c/min = 7.5 c -> 8; 89 s = 7.42 c -> 7; 3600 s = 300 c exactly.
    assert machine_cents(90, 5) == 8
    assert machine_cents(89, 5) == 7
    assert machine_cents(3600, 5) == 300


def test_a_failed_attempt_is_part_of_the_actual_cost() -> None:
    done = Attempt(machine_seconds=650 * 60, grams_used=210, failed=False)
    failed = Attempt(machine_seconds=120 * 60, grams_used=None, failed=True)
    # Done: 1500 + 210 g x 7 = 1470 + 650 min x 5 = 3250 -> 6220.
    assert outcome(TEN_STANDS, RATES, [done]).actual_cents == 6220
    # Failed, grams not recorded so the quoted 200 g are assumed: 1500 + 1400 + 600 = 3500.
    both = outcome(TEN_STANDS, RATES, [failed, done])
    assert both.actual_cents == 6220 + 3500
    assert both.estimated_cents == 5900  # the estimate does not move: a reprint is the shop's cost
    assert (both.attempts, both.failed_attempts, both.grams_assumed) == (2, 1, 1)
    assert (both.actual_grams, both.estimated_grams) == (410, 200)
    assert (both.actual_seconds, both.estimated_minutes) == (770 * 60, 600)


def test_a_job_with_no_attempt_is_refused() -> None:
    with pytest.raises(ValueError):
        outcome(TEN_STANDS, RATES, [])


@pytest.mark.parametrize(
    ("n", "k", "expected"),
    [
        (5, 5, Fraction(1, 32)),  # all five over: one way in 32
        (5, 4, Fraction(6, 32)),  # C(5,4) + C(5,5) = 5 + 1
        (10, 9, Fraction(11, 1024)),  # C(10,9) + C(10,10) = 10 + 1
        (10, 8, Fraction(56, 1024)),  # 45 + 10 + 1
        (4, 4, Fraction(1, 16)),
        (0, 0, Fraction(1)),
    ],
)
def test_sign_test_probabilities(n: int, k: int, expected: Fraction) -> None:
    assert sign_test_p(n, k) == expected


def jobs(ratios: list[float], material: str = "TPU-BLACK", quoted: bool = True) -> list[JobRow]:
    """Jobs estimated at 10000 cents that cost ratio x 10000."""
    return [
        JobRow(
            label=f"job {i}",
            material_code=material,
            process="fdm",
            estimated_cents=10_000 if quoted else None,
            actual_cents=round(10_000 * r) if quoted else None,
            estimated_minutes=100,
            actual_seconds=round(6000 * r),
            attempts=1,
            failed_attempts=0,
            failure_reasons=(),
            grams_assumed=0,
            synthetic=False,
            finished_at=T,
        )
        for i, r in enumerate(ratios)
    ]


def test_five_jobs_all_well_over_are_flagged() -> None:
    # 5 of 5 over 1.15: p = 1/32 = 0.031 < 0.05.
    s = summarise("TPU-BLACK", jobs([1.2] * 5), RULE)
    assert s.flagged and s.over_threshold == 5 and s.p_value == pytest.approx(1 / 32)
    assert s.suggestion == "Review the price rule for TPU-BLACK."
    assert "5 of 5" in s.reason


def test_four_jobs_are_too_few_however_far_over() -> None:
    s = summarise("TPU-BLACK", jobs([1.5] * 4), RULE)
    assert not s.flagged and s.suggestion is None and "at least 5" in s.reason
    # Only the minimum refuses here: with alpha 0.1, 4 of 4 (p = 1/16 = 0.0625) would pass.
    loose = FlagRule(threshold_ratio=1.15, min_jobs=5, alpha=0.1)
    assert not summarise("TPU-BLACK", jobs([1.5] * 4), loose).flagged
    assert summarise("TPU-BLACK", jobs([1.5] * 5), loose).flagged


def test_a_type_ten_percent_over_is_never_flagged_however_many_jobs() -> None:
    # Every one of 40 jobs is 10 % over: none is over 15 %, so k = 0.
    s = summarise("TPU-BLACK", jobs([1.10] * 40), RULE)
    assert not s.flagged and s.over_threshold == 0


def test_exactly_at_the_threshold_is_not_over() -> None:
    # 11500 / 10000 = 1.15 exactly: not more than 1.15.
    assert summarise("TPU-BLACK", jobs([1.15] * 40), RULE).over_threshold == 0


def test_the_sign_test_boundary_with_ten_jobs() -> None:
    # 8 of 10 over: p = 56/1024 = 0.055, not under 0.05. 9 of 10: 11/1024 = 0.011, flagged.
    assert not summarise("TPU-BLACK", jobs([1.3] * 8 + [1.0] * 2), RULE).flagged
    assert summarise("TPU-BLACK", jobs([1.3] * 9 + [1.0]), RULE).flagged


def test_jobs_without_a_quote_count_for_time_not_for_the_flag() -> None:
    rows = jobs([1.5] * 3) + jobs([1.5] * 10, quoted=False)
    s = summarise("TPU-BLACK", rows, RULE)
    assert (s.jobs, s.quoted_jobs, s.flagged) == (13, 3, False)
    assert s.median_time_ratio == pytest.approx(1.5)


def test_the_report_puts_flagged_types_first_and_counts_synthetic_history() -> None:
    rows = jobs([1.0] * 6, "AL-6061") + jobs([1.4] * 6, "TPU-BLACK")
    rows += [
        JobRow(
            **{**rows[0].__dict__, "label": "history", "synthetic": True, "estimated_cents": None}
        )
    ]
    r = build(rows, RULE)
    assert [t.material_code for t in r.types] == ["TPU-BLACK", "AL-6061"]
    assert [t.flagged for t in r.types] == [True, False]
    assert (r.synthetic_jobs, r.not_quoted_jobs) == (1, 1)


# --- The acceptance scenarios (the full grid is `make eval`; this is the quick check) ----------


def test_the_seeded_scenario_flags_exactly_the_biased_type_and_its_control_nothing() -> None:
    from brimline_engine.evals.costing import seeded_scenarios

    assert seeded_scenarios() == {"biased": ["TPU-BLACK"], "control": []}


def test_ten_percent_over_and_no_bias_are_never_flagged_on_dev_seeds() -> None:
    from brimline_engine.costing.config import costing_config
    from brimline_engine.costing.scenario import history
    from brimline_engine.shop_config import load_shop_config

    shop, cfg = load_shop_config(), costing_config()
    for seed in range(30):  # dev seeds; the reported numbers use held-out seeds 10000+
        for bias in (1.0, 1.10):
            rows = history(
                shop,
                cfg.scenario,
                seed=seed,
                jobs_per_type=40,
                biased="TPU-BLACK",
                bias=bias,
                end=T,
            )
            assert not [t.material_code for t in build(rows, cfg.flag).types if t.flagged]
