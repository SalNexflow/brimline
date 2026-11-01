"""How many grams a job's part uses, and where that number came from (M9).

A person's entry wins; then the job's latest model file, if it passed its checks; then the line
of the order's approved quote. With none of these the job cannot be planned while stock is
limited, and the board says so (docs/DECISIONS.md). The source is shown next to the number.
"""

from dataclasses import dataclass
from typing import Literal

import psycopg

Source = Literal["entered", "file estimate", "quote"]


@dataclass(frozen=True)
class Grams:
    per_part: int | None
    source: Source | None  # None when nothing gives a number


def resolve(entered: int | None, from_file: int | None, from_quote: int | None) -> Grams:
    """The first number in the stated order. Pure, so the order is easy to test."""
    for value, source in (
        (entered, "entered"),
        (from_file, "file estimate"),
        (from_quote, "quote"),
    ):
        if value is not None and value > 0:
            return Grams(value, source)  # type: ignore[arg-type]
    return Grams(None, None)


def job_grams(conn: psycopg.Connection, job_ids: list[int]) -> dict[int, Grams]:
    rows = conn.execute(
        "SELECT j.id, j.grams_per_part,"
        # The latest file of the job counts only if it did not fail its checks, as when files
        # fill in a job's other values (files/service.py).
        "  (SELECT CASE WHEN f.overall <> 'fail' THEN (f.planning->>'grams_per_part')::int END"
        "     FROM files f WHERE f.job_id = j.id ORDER BY f.id DESC LIMIT 1),"
        "  (SELECT l.grams_per_part FROM quotes q"
        "     JOIN quote_lines l ON l.quote_id = q.id AND l.line_no = j.line_no"
        "     WHERE q.order_id = j.order_id AND q.status = 'approved' ORDER BY q.id DESC LIMIT 1)"
        " FROM jobs j WHERE j.id = ANY(%s)",
        (job_ids,),
    ).fetchall()
    return {int(r[0]): resolve(r[1], r[2], r[3]) for r in rows}
