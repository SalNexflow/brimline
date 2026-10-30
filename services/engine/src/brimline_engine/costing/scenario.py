"""Synthetic history of finished jobs, for the eval and the demo seed. Deterministic per seed.

Every job type's actual/quoted varies job to job (log-normal noise, config/costing.toml), some
attempts fail part way and are reprinted, and one type can be given a real bias: it truly takes
`bias` times its quoted machine time and material. The control scenario has no bias. Prices use
the shop's own rules (config/shop.toml), so the costs are on the same scale as the app's.
"""

import random
from datetime import datetime, timedelta

from brimline_engine.costing.config import Scenario
from brimline_engine.costing.outcome import Attempt, Estimate, Rates, outcome
from brimline_engine.costing.report import JobRow
from brimline_engine.shop_config import Process, ShopConfig


def rates_for(shop: ShopConfig, material: str, process: Process) -> Rates:
    p = shop.price_rules
    return Rates(
        setup_cents=p.setup_cents,
        material_cents_per_gram=p.material_cents_per_gram[material],
        machine_cents_per_minute=p.machine_minute_cents[process],
    )


def materials(shop: ShopConfig) -> list[tuple[str, Process]]:
    """(code, process) for every material the shop prices."""
    return [
        (m.code, m.process)
        for m in shop.materials
        if m.code in shop.price_rules.material_cents_per_gram
    ]


def _job(
    rng: random.Random,
    material: str,
    process: Process,
    true_ratio: float,
    rates: Rates,
    s: Scenario,
) -> tuple[Estimate, list[Attempt]]:
    e = Estimate(
        quantity=rng.randint(1, 20),
        grams_per_part=rng.randint(10, 200),
        minutes_per_part=rng.randint(20, 240),
    )
    full_seconds = e.quantity * e.minutes_per_part * 60 * true_ratio
    full_grams = e.quantity * e.grams_per_part * true_ratio
    attempts: list[Attempt] = []
    while len(attempts) < s.max_attempts - 1 and rng.random() < s.failure_chance:
        share = rng.uniform(s.failed_share_min, s.failed_share_max)
        attempts.append(
            Attempt(
                machine_seconds=max(1, round(full_seconds * share)),
                grams_used=max(1, round(full_grams * share)),
                failed=True,
            )
        )
    attempts.append(
        Attempt(
            machine_seconds=max(1, round(full_seconds * rng.lognormvariate(0, s.time_noise_sigma))),
            grams_used=max(1, round(full_grams * rng.lognormvariate(0, s.grams_noise_sigma))),
            failed=False,
        )
    )
    return e, attempts


def history(
    shop: ShopConfig,
    s: Scenario,
    *,
    seed: int,
    jobs_per_type: int,
    biased: str | None,
    bias: float,
    end: datetime,
) -> list[JobRow]:
    """`jobs_per_type` finished, quoted jobs of every material, finished over the weeks before
    `end`. With `biased` set, that material really takes `bias` x its quote."""
    rng = random.Random(seed)
    rows: list[JobRow] = []
    for material, process in materials(shop):
        rates = rates_for(shop, material, process)
        true_ratio = bias if material == biased else 1.0
        for i in range(jobs_per_type):
            e, attempts = _job(rng, material, process, true_ratio, rates, s)
            o = outcome(e, rates, attempts)
            rows.append(
                JobRow(
                    label=f"History {material} #{i + 1}",
                    material_code=material,
                    process=process,
                    estimated_cents=o.estimated_cents,
                    actual_cents=o.actual_cents,
                    estimated_minutes=o.estimated_minutes,
                    actual_seconds=o.actual_seconds,
                    attempts=o.attempts,
                    failed_attempts=o.failed_attempts,
                    failure_reasons=("warping",) * o.failed_attempts,
                    grams_assumed=o.grams_assumed,
                    synthetic=True,
                    finished_at=end - timedelta(hours=rng.randint(24, 24 * 56)),
                )
            )
    return rows
