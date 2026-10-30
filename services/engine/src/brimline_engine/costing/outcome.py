"""What one finished job cost against its quote. Pure functions, integer cents (hard rule 1).

Both sides use the same rates, the price rule set the quote was priced with, so a later price
change cannot look like an overrun; the difference is how much more material and machine time
the job really used:

  estimated = setup + quantity x (grams x material rate + minutes x machine rate)
  actual    = for every attempt, failed ones included:
              setup + grams used x material rate + machine seconds x machine rate / 60

Post-processing fees and the rush surcharge are the same on both sides, so they are left out.
A failed attempt is the shop's cost, never the customer's: it is counted in `actual` only.
"""

from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class Rates:
    """The quote's own rates for this job's material and process."""

    setup_cents: int
    material_cents_per_gram: int
    machine_cents_per_minute: int


@dataclass(frozen=True)
class Estimate:
    quantity: int
    grams_per_part: int
    minutes_per_part: int


@dataclass(frozen=True)
class Attempt:
    """One go at the job: its print or machining time, the grams the operator recorded (None when
    not recorded), and whether it failed."""

    machine_seconds: int
    grams_used: int | None
    failed: bool


@dataclass(frozen=True)
class Outcome:
    estimated_cents: int
    actual_cents: int
    estimated_minutes: int
    actual_seconds: int
    estimated_grams: int
    actual_grams: int
    grams_assumed: int  # attempts whose grams were not recorded, so the quoted grams were used
    attempts: int
    failed_attempts: int


def estimated_cents(e: Estimate, r: Rates) -> int:
    return r.setup_cents + e.quantity * (
        e.grams_per_part * r.material_cents_per_gram
        + e.minutes_per_part * r.machine_cents_per_minute
    )


def machine_cents(seconds: int, cents_per_minute: int) -> int:
    """seconds x rate / 60, rounded half up, in integers only."""
    return (seconds * cents_per_minute + 30) // 60


def outcome(e: Estimate, r: Rates, attempts: Sequence[Attempt]) -> Outcome:
    """The job's estimate against every attempt it took. An attempt with no recorded grams is
    taken to have used the quoted grams for the whole job (counted in `grams_assumed`, so the
    report can say how many values are assumed rather than measured)."""
    if not attempts:
        raise ValueError("a finished job has at least one attempt")
    quoted_grams = e.quantity * e.grams_per_part
    actual = 0
    grams = 0
    for a in attempts:
        used = quoted_grams if a.grams_used is None else a.grams_used
        grams += used
        actual += (
            r.setup_cents
            + used * r.material_cents_per_gram
            + machine_cents(a.machine_seconds, r.machine_cents_per_minute)
        )
    return Outcome(
        estimated_cents=estimated_cents(e, r),
        actual_cents=actual,
        estimated_minutes=e.quantity * e.minutes_per_part,
        actual_seconds=sum(a.machine_seconds for a in attempts),
        estimated_grams=quoted_grams,
        actual_grams=grams,
        grams_assumed=sum(a.grams_used is None for a in attempts),
        attempts=len(attempts),
        failed_attempts=sum(a.failed for a in attempts),
    )
