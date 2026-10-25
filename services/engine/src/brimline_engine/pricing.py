"""Quote pricing. Pure functions over typed inputs and dated price rules (hard rule 1).

Per line:  setup + quantity x (grams x material rate + minutes x machine rate + post-processing)
Per quote: sum of lines, then the rush multiplier, rounded half up to whole cents.
All amounts are integer cents, so there is no floating-point rounding anywhere.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class PriceRules:
    rule_set_id: int
    effective_from: date
    setup_cents: int
    rush_multiplier_percent: int
    material_cents_per_gram: Mapping[str, int]
    machine_cents_per_minute: Mapping[str, int]
    post_process_cents_per_part: Mapping[str, int]


@dataclass(frozen=True)
class LineInput:
    part_name: str
    quantity: int | None
    material_code: str | None
    process: str | None
    grams_per_part: int | None
    minutes_per_part: int | None
    post_processing: tuple[str, ...]


@dataclass(frozen=True)
class LinePrice:
    material_cents: int
    machine_cents: int
    post_process_cents: int
    setup_cents: int

    @property
    def total_cents(self) -> int:
        return self.material_cents + self.machine_cents + self.post_process_cents + self.setup_cents


@dataclass(frozen=True)
class QuotePrice:
    rule_set_id: int
    lines: list[LinePrice]
    subtotal_cents: int
    rush_surcharge_cents: int
    total_cents: int


@dataclass(frozen=True)
class PricingPending:
    """Not enough information to price. Lists what is missing, in plain words."""

    missing: list[str]


def rush_total(subtotal_cents: int, percent: int) -> int:
    """subtotal x percent / 100, rounded half up, in integers only."""
    return (subtotal_cents * percent + 50) // 100


def _missing_for(n: int, line: LineInput, rules: PriceRules) -> list[str]:
    missing = [
        f"line {n}: {label}"
        for label, value in (
            ("quantity", line.quantity),
            ("material", line.material_code),
            ("grams per part", line.grams_per_part),
            ("minutes per part", line.minutes_per_part),
        )
        if value is None
    ]
    if line.material_code is not None and line.material_code not in rules.material_cents_per_gram:
        missing.append(f"line {n}: no price rule for material {line.material_code}")
    if line.process is not None and line.process not in rules.machine_cents_per_minute:
        missing.append(f"line {n}: no price rule for process {line.process}")
    missing += [
        f"line {n}: no price rule for post-processing {kind}"
        for kind in line.post_processing
        if kind not in rules.post_process_cents_per_part
    ]
    return missing


def price_quote(
    lines: Sequence[LineInput], rush: bool, rules: PriceRules
) -> QuotePrice | PricingPending:
    if not lines:
        return PricingPending(missing=["no lines"])
    missing = [m for n, line in enumerate(lines, start=1) for m in _missing_for(n, line, rules)]
    if missing:
        return PricingPending(missing=missing)

    priced: list[LinePrice] = []
    for line in lines:
        # _missing_for guarantees these are set; the asserts keep the type checker honest.
        assert line.quantity is not None and line.material_code is not None
        assert line.grams_per_part is not None and line.minutes_per_part is not None
        assert line.process is not None
        q = line.quantity
        priced.append(
            LinePrice(
                material_cents=q
                * line.grams_per_part
                * rules.material_cents_per_gram[line.material_code],
                machine_cents=q
                * line.minutes_per_part
                * rules.machine_cents_per_minute[line.process],
                post_process_cents=q
                * sum(rules.post_process_cents_per_part[kind] for kind in line.post_processing),
                setup_cents=rules.setup_cents,
            )
        )
    subtotal = sum(p.total_cents for p in priced)
    total = rush_total(subtotal, rules.rush_multiplier_percent) if rush else subtotal
    return QuotePrice(
        rule_set_id=rules.rule_set_id,
        lines=priced,
        subtotal_cents=subtotal,
        rush_surcharge_cents=total - subtotal,
        total_cents=total,
    )
