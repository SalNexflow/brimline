"""Scoring of the file-checker eval, on hand-made rows whose counts are known."""

from typing import Any

from brimline_engine.evals.files import score

PASS = dict.fromkeys(
    ("parse", "units", "watertight", "fits", "walls", "overhangs", "loose_parts"), "pass"
)


def row(
    rid: str, expected: dict[str, str], overall: str, got: dict[str, str], got_overall: str
) -> dict[str, Any]:
    return {
        "id": rid,
        "expected": PASS | expected,
        "overall": overall,
        "got": PASS | got,
        "got_overall": got_overall,
        "reasons": {},
        "size_mm": [1, 2, 3],
        "got_size_mm": [1, 2, 3.001],
        "seconds": 0.1,
    }


def test_false_pass_and_warning_only_are_counted_apart() -> None:
    rows = [
        row("a", {"walls": "fail"}, "fail", {}, "pass"),  # broken, passed: a false pass
        row("b", {"walls": "fail"}, "fail", {"walls": "warn"}, "warn"),  # broken, only a warning
        row("c", {"fits": "fail"}, "fail", {"fits": "fail"}, "fail"),  # caught
        row("d", {}, "pass", {"loose_parts": "fail"}, "fail"),  # false alarm
    ]
    s = score(rows)
    assert (s["n"], s["broken"], s["false_pass"], s["broken_as_warn"]) == (4, 3, 1, 1)
    assert (s["labelled_pass"], s["false_alarm"], s["overall_agreement"]) == (1, 1, 1)
    walls = s["per_check"]["walls"]
    assert (
        walls["agreement"],
        walls["labelled_fail"],
        walls["false_pass"],
        walls["fail_as_warn"],
    ) == (2, 2, 1, 1)
    assert s["size_within_0_01_mm"] == 4
    assert len(s["disagreements"]) == 3
