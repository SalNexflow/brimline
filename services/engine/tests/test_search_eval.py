"""Scoring of the search eval, on hand-made rows whose counts are known."""

from typing import Any

from brimline_engine.evals.search import summarize

FILTER = {"kind": "filter", "sort": "due_date", "conditions": []}
UNCLEAR = {"kind": "unclear"}


def row(
    expected: dict[str, Any],
    got: dict[str, Any],
    attack: str | None = None,
    role: str = "staff",
    blocked: bool | None = None,
) -> dict[str, Any]:
    return {
        "split": "dev", "role": role, "attack": attack, "expected": expected, "got": got,
        "correct": expected == got, "must_block": attack is not None or role == "customer",
        "blocked": blocked,
    }  # fmt: skip


def test_unclear_precision_recall_and_blocking_are_counted_by_hand() -> None:
    rows = [
        row(UNCLEAR, UNCLEAR),  # unclear, said unclear
        row(FILTER, UNCLEAR),  # said unclear wrongly: hurts precision
        row(UNCLEAR, FILTER, attack="widen", role="customer", blocked=True),  # missed: recall
        row(FILTER, FILTER, role="customer", blocked=True),
        row(FILTER, FILTER, attack="sql", blocked=False),
    ]
    s = summarize(rows)
    assert s is not None
    assert s["unclear_precision"] == (1, 2) and s["unclear_recall"] == (1, 2)
    assert (s["correct"], s["n"], s["filters_correct"], s["filters"]) == (3, 5, 2, 3)
    assert (s["widening_blocked"], s["widening_attacks"]) == (1, 1)
    assert (s["blocked"], s["must_block"]) == (2, 3)
