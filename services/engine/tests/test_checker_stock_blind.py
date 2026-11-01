"""Stock cases written by a fresh-context reviewer who saw only docs/SCHEDULE_RULES.md and
config/scheduler.toml, never the code (M9). `checker_stock_blind_cases.json` is kept as written.
"""

import json
from pathlib import Path
from typing import Any

import pytest

from brimline_engine.checker import check_document

CASES: list[dict[str, Any]] = json.loads(
    (Path(__file__).parent / "checker_stock_blind_cases.json").read_text(encoding="utf-8")
)


def test_the_reviewer_wrote_enough_cases() -> None:
    assert len(CASES) >= 12
    assert len({c["name"] for c in CASES}) == len(CASES)


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["name"])
def test_blind_stock_case(case: dict[str, Any]) -> None:
    result = check_document(case["doc"])
    expected = case["expected"]
    assert result.valid == expected["valid"]
    assert result.codes() == set(expected["codes"])
    short = {v.job for v in result.violations if v.code == "material_short"}
    assert short == set(expected["short_jobs"])
