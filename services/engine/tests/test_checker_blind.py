"""Cases written by a fresh-context reviewer who saw only docs/BRIEF.md and config/ (M4).

`checker_blind_cases.json` is kept exactly as the reviewer wrote it, and its rules are in
docs/checker_blind_rules.md. The reviewer's rule ids (B01..B16) map to our codes below. Where we
resolved a difference against the reviewer, the case's expected outcome is overridden here, with
the decision that explains why; the input is never changed.
"""

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

import pytest

from brimline_engine.checker import check_document

CASES: list[dict[str, Any]] = json.loads(
    (Path(__file__).parent / "checker_blind_cases.json").read_text(encoding="utf-8")
)

# Reviewer rule -> the codes in docs/SCHEDULE_RULES.md that cover it.
RULE_MAP: dict[str, set[str]] = {
    "B01": {"missing_job", "duplicate_job", "unknown_job"},
    "B02": {"wrong_tasks", "unknown_machine"},
    "B03": {"past_horizon"},
    "B04": {"wrong_duration"},
    "B05": {"task_order"},
    "B06": {"not_eligible"},
    "B07": {"not_eligible"},
    "B08": {"not_eligible"},
    "B09": {"machine_overlap"},
    "B10": {"changeover"},
    "B11": {"machine_off_shift"},
    "B12": {"manual_off_shift"},
    "B13": {"staff_overload"},
    "B15": {"before_release"},
    "B16": {"fixed_moved"},
}

# Case -> (our expected codes, our expected warnings, the decision that resolved it).
OVERRIDES: dict[str, tuple[set[str], set[str], str]] = {
    # The reviewer read `arrival` as a minute; it is the order jobs came in (FCFS uses it).
    "prep_before_arrival": (set(), set(), "D57"),
    # A fixed (running or done) machine task's prep already happened, so the plan must not list it.
    "fixed_task_moved_one_minute": ({"fixed_moved", "wrong_tasks"}, set(), "D58"),
    # A fixed job may be reported unscheduled (it still blocks its machine); this one could have
    # fitted, so it is flagged as suspicious.
    "fixed_job_dropped_to_unscheduled": (set(), {"J1"}, "D59"),
}


def test_the_reviewer_wrote_enough_cases() -> None:
    assert len(CASES) >= 15
    assert len({c["name"] for c in CASES}) == len(CASES)
    assert set(OVERRIDES) <= {c["name"] for c in CASES}


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["name"])
def test_blind_case(case: dict[str, Any]) -> None:
    result = check_document(case["doc"])
    expected = case["expected"]
    if case["name"] in OVERRIDES:
        codes, warned, _ = OVERRIDES[case["name"]]
        assert result.codes() == codes
        assert {w.job for w in result.warnings} == warned
        return
    assert result.valid == expected["valid"]
    covered: set[str] = set()
    for v in expected["violations"]:
        allowed = RULE_MAP[v["rule"]]
        hits = [x for x in result.violations if x.code in allowed]
        assert hits, f"{v['rule']} not reported; got {result.codes()}"
        if v["job"] is not None:
            assert v["job"] in {x.job for x in hits}
        covered |= allowed
    assert result.codes() <= covered, f"extra violations: {result.codes() - covered}"
    assert result.metrics is not None
    mine = asdict(result.metrics)
    for name, value in expected.get("metrics", {}).items():
        assert mine[name] == value, name
