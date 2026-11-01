"""Material stock over time, for the greedy baselines (M9). The CP-SAT model states the same
rule as a reservoir constraint (cpsat.py); the checker has its own copy (rule R20).

The level of a material at minute t = its stock + deliveries arrived by t - the grams of every
placed job whose machine task starts at or before t. It must never fall below zero.
"""

from brimline_engine.scheduling.model import Instance, Job

# (machine start, material, grams) of each job already placed that takes from stock.
Uses = list[tuple[int, str, int]]


def level(instance: Instance, uses: Uses, material: str, t: int) -> int:
    arrived = sum(d.grams for d in instance.deliveries if d.material == material and d.at <= t)
    used = sum(g for s, m, g in uses if m == material and s <= t)
    return instance.stock_of(material) + arrived - used


def free_from(instance: Instance, uses: Uses, job: Job) -> int | None:
    """The earliest minute from which this job can take its grams without leaving any later
    moment short (placed jobs keep theirs); None if that never happens. With no stock limit,
    or enough from the start, it is plan_start."""
    if instance.stock is None:
        return instance.plan_start
    # The level only changes at these minutes; walk back from the last one while it stays
    # high enough. Before the first of them the level is the stock itself.
    times = sorted(
        {d.at for d in instance.deliveries if d.material == job.material}
        | {s for s, m, _ in uses if m == job.material}
    )
    candidate: int | None = None
    for t in reversed(times):
        if level(instance, uses, job.material, t) < job.grams:
            return None if candidate is None else max(candidate, instance.plan_start)
        candidate = t
    if instance.stock_of(job.material) >= job.grams:
        return instance.plan_start
    return None if candidate is None else max(candidate, instance.plan_start)
