"""The quoted-versus-actual report and the under-quote flag. Pure functions over recorded outcomes.

A job type is a material (which also fixes the process). A type is flagged when, among its
finished quoted jobs,

  1. there are at least `min_jobs` of them, and
  2. more of them cost over `threshold_ratio` x their estimate than chance explains, if the
     type's typical (median) overrun were the threshold or less: a one-sided sign test. With
     no bias, each job would land above or below the threshold's median like a coin flip; the
     flag needs the chance of seeing this many above by luck to be under `alpha`.

Rule 2 needs more than half the jobs over the threshold, so a flagged type's median overrun is
always above it. Testing against the threshold, not against "no overrun", is what keeps a type
that runs a little over (10 %) from being flagged however many jobs it has. The report suggests
a price rule to review; it never changes one (hard rule 7: a person decides).
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from fractions import Fraction
from math import comb
from statistics import median

from pydantic import BaseModel

from brimline_engine.costing.config import FlagRule


@dataclass(frozen=True)
class JobRow:
    """One finished job's recorded outcome (job_outcomes)."""

    label: str  # the job ("BL-0004 line 2 Phone stand"), or the synthetic history's own label
    material_code: str
    process: str
    estimated_cents: int | None  # None: the order did not come from a quote
    actual_cents: int | None
    estimated_minutes: int
    actual_seconds: int
    attempts: int
    failed_attempts: int
    failure_reasons: tuple[str, ...]
    grams_assumed: int
    synthetic: bool
    finished_at: datetime


class TypeSummary(BaseModel):
    material_code: str
    process: str
    jobs: int  # finished jobs of this type
    quoted_jobs: int  # of them, with a quote to compare the cost against
    over_threshold: int  # quoted jobs that cost more than threshold x estimate
    p_value: float | None  # the sign test's chance of this many by luck; None without quoted jobs
    median_cost_ratio: float | None
    median_time_ratio: float | None
    attempts: int
    failed_attempts: int
    synthetic_jobs: int  # of the quoted jobs, seeded history (said in `reason`)
    flagged: bool
    reason: str  # plain words: why flagged, or why not
    suggestion: str | None  # "Review the price rule for X" when flagged; never applied by code


class JobLine(BaseModel):
    label: str
    material_code: str
    estimated_cents: int | None
    actual_cents: int | None
    cost_ratio: float | None  # actual / estimated cost; None without a quote
    estimated_minutes: int
    actual_minutes: float
    attempts: int
    failure_reasons: list[str]
    grams_assumed: int
    synthetic: bool
    finished_at: datetime


class CostReport(BaseModel):
    currency: str  # ISO 4217; every amount is in its minor unit (cents)
    threshold_ratio: float
    min_jobs: int
    alpha: float
    types: list[TypeSummary]
    jobs: list[JobLine]
    synthetic_jobs: int  # seeded history, labelled on the page
    not_quoted_jobs: int


def sign_test_p(n: int, k: int) -> Fraction:
    """Chance of k or more heads in n fair coin flips: sum of C(n, i) / 2^n for i >= k. Exact."""
    return Fraction(sum(comb(n, i) for i in range(k, n + 1)), 2**n)


def _over(row: JobRow, threshold: Fraction) -> bool:
    assert row.estimated_cents is not None and row.actual_cents is not None
    # actual / estimated > threshold, without division: exact for any integers.
    return row.actual_cents * threshold.denominator > row.estimated_cents * threshold.numerator


def summarise(material: str, rows: Sequence[JobRow], rule: FlagRule) -> TypeSummary:
    threshold = Fraction(str(rule.threshold_ratio))
    quoted = [r for r in rows if r.estimated_cents and r.actual_cents is not None]
    n = len(quoted)
    k = sum(_over(r, threshold) for r in quoted)
    p = sign_test_p(n, k) if n else None
    flagged = n >= rule.min_jobs and p is not None and p < Fraction(str(rule.alpha))
    pct = round((rule.threshold_ratio - 1) * 100)
    cost_ratios = [Fraction(r.actual_cents or 0, r.estimated_cents or 1) for r in quoted]
    time_ratios = [
        Fraction(r.actual_seconds, 60 * r.estimated_minutes) for r in rows if r.estimated_minutes
    ]
    med_cost = float(median(cost_ratios)) if cost_ratios else None
    if n < rule.min_jobs:
        reason = f"{n} quoted job(s) finished; at least {rule.min_jobs} are needed to tell."
    elif flagged:
        reason = (
            f"{k} of {n} jobs cost more than {pct} % over their quote (median "
            f"{_signed_pct(med_cost)}); that many by chance is unlikely (p = {float(p or 0):.3f}, "
            f"under {rule.alpha})."
        )
    else:
        reason = (
            f"{k} of {n} jobs cost more than {pct} % over their quote (median "
            f"{_signed_pct(med_cost)}); not more than chance explains (p = {float(p or 0):.3f})."
        )
    synthetic = sum(r.synthetic for r in quoted)
    if synthetic:
        # The flag counts every quoted job alike; say how much of it is made-up history.
        reason += f" {synthetic} of the {n} quoted jobs are synthetic history."
    return TypeSummary(
        material_code=material,
        process=rows[0].process,
        jobs=len(rows),
        quoted_jobs=n,
        over_threshold=k,
        p_value=float(p) if p is not None else None,
        median_cost_ratio=med_cost,
        median_time_ratio=float(median(time_ratios)) if time_ratios else None,
        attempts=sum(r.attempts for r in rows),
        failed_attempts=sum(r.failed_attempts for r in rows),
        synthetic_jobs=synthetic,
        flagged=flagged,
        reason=reason,
        suggestion=f"Review the price rule for {material}." if flagged else None,
    )


def _signed_pct(ratio: float | None) -> str:
    if ratio is None:
        return "n/a"
    return f"{(ratio - 1) * 100:+.0f} %"


def build(rows: Sequence[JobRow], rule: FlagRule, currency: str = "EUR") -> CostReport:
    by_type: dict[str, list[JobRow]] = {}
    for r in rows:
        by_type.setdefault(r.material_code, []).append(r)
    types = [summarise(m, by_type[m], rule) for m in sorted(by_type)]
    # Flagged types first, then by name, so what needs a look is at the top.
    types.sort(key=lambda t: (not t.flagged, t.material_code))
    return CostReport(
        currency=currency,
        threshold_ratio=rule.threshold_ratio,
        min_jobs=rule.min_jobs,
        alpha=rule.alpha,
        types=types,
        jobs=[
            JobLine(
                label=r.label,
                material_code=r.material_code,
                estimated_cents=r.estimated_cents,
                actual_cents=r.actual_cents,
                cost_ratio=(
                    r.actual_cents / r.estimated_cents
                    if r.estimated_cents and r.actual_cents is not None
                    else None
                ),
                estimated_minutes=r.estimated_minutes,
                actual_minutes=round(r.actual_seconds / 60, 1),
                attempts=r.attempts,
                failure_reasons=list(r.failure_reasons),
                grams_assumed=r.grams_assumed,
                synthetic=r.synthetic,
                finished_at=r.finished_at,
            )
            for r in sorted(rows, key=lambda r: r.finished_at, reverse=True)
        ],
        synthetic_jobs=sum(r.synthetic for r in rows),
        not_quoted_jobs=sum(not r.estimated_cents for r in rows),
    )
