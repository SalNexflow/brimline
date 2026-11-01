"""Seeded benchmark instances: the shop's six machines, a realistic mix of jobs.

Same seed and size -> the same instance, byte for byte. Mix (invented, stated here so the
benchmark can be judged): ~60 % FDM, ~25 % resin, ~15 % CNC; 15 % rush jobs with tight due
dates; ~10 % large parts that only the large printer takes; ~30 % with post-processing; ~15 %
waiting for a material delivery during the first week; due dates two to nine working days out.
"""

import math
import random
from dataclasses import replace

from brimline_engine.scheduling.calendar import horizon_minutes, shift_windows
from brimline_engine.scheduling.config import SchedulerConfig
from brimline_engine.scheduling.durations import eligible_machines
from brimline_engine.scheduling.model import Delivery, Instance, Job, Machine, Process
from brimline_engine.shop_config import ShopConfig

_MINUTES_PER_PART: dict[str, tuple[int, int]] = {
    "fdm": (20, 150),
    "resin": (30, 90),
    "cnc": (15, 60),
}
_QUANTITY: dict[str, tuple[int, int]] = {"fdm": (1, 24), "resin": (1, 12), "cnc": (1, 6)}


def shop_machines(shop: ShopConfig) -> tuple[Machine, ...]:
    return tuple(
        Machine(
            code=m.code, process=m.process, materials=frozenset(m.materials), build_mm=m.build_mm
        )
        for m in shop.machines
    )


def generate(seed: int, n_jobs: int, shop: ShopConfig, cfg: SchedulerConfig) -> Instance:
    rng = random.Random(seed)  # our own generator: nothing global, fully repeatable
    machines = shop_machines(shop)
    windows = shift_windows(cfg.shifts)
    materials_by_process: dict[Process, list[str]] = {
        p: sorted({mat for m in machines if m.process == p for mat in m.materials})
        for p in ("fdm", "resin", "cnc")
    }
    jobs: list[Job] = []
    for i in range(n_jobs):
        processes: list[Process] = ["fdm", "resin", "cnc"]
        process = rng.choices(processes, weights=[60, 25, 15])[0]
        material = rng.choice(materials_by_process[process])
        large = process == "fdm" and rng.random() < 0.10
        part = (
            (rng.randint(260, 340), rng.randint(40, 200), rng.randint(20, 120))
            if large
            else (rng.randint(20, 180), rng.randint(20, 120), rng.randint(5, 100))
        )
        quantity = rng.randint(*_QUANTITY[process])
        rush = rng.random() < 0.15
        # Due at the end of a working day: rush within 1-3 working days, others 2-9.
        day = rng.randint(1, 3) if rush else rng.randint(2, 9)
        due = windows[min(day, len(windows) - 1)][1]
        # A late delivery always arrives before the due day (DEFECT_LOG #17): otherwise the job
        # is late whatever any scheduler does, which says nothing about the schedulers.
        late_delivery = rng.random() < 0.15 and day >= 2
        release = windows[rng.randint(1, day - 1)][0] + rng.randint(0, 300) if late_delivery else 0
        job = Job(
            id=f"J{i + 1:03d}",
            arrival=i + 1,
            material=material,
            process=process,
            part_mm=part,
            quantity=quantity,
            minutes_per_part=rng.randint(*_MINUTES_PER_PART[process]),
            post_minutes_per_part=rng.randint(2, 10) if rng.random() < 0.30 else 0,
            due=due,
            rush=rush,
            release=release,
        )
        if not eligible_machines(job, machines):  # e.g. a large part in a material FDM-4 lacks
            job = Job(**{**job.__dict__, "part_mm": (100, 80, 40)})
        jobs.append(job)
    return Instance(
        name=f"n{n_jobs}-s{seed}",
        horizon=horizon_minutes(cfg.shifts),
        machines=machines,
        jobs=tuple(jobs),
        shifts=windows,
        staff=cfg.staff.people_per_shift,
    )


# Grams per part by process (invented): small prints, resin parts, aluminium blanks.
_GRAMS_PER_PART: dict[str, tuple[int, int]] = {
    "fdm": (10, 120),
    "resin": (10, 80),
    "cnc": (50, 400),
}
PACK_GRAMS = 1000  # deliveries come in whole 1 kg packs


def with_stock(inst: Instance, seed: int, cover: float = 0.6, slip: int = 0) -> Instance:
    """The same instance with material limits (M9): each job gets grams per part; each material
    has `cover` of its jobs' grams on hand and one delivery with the rest (whole packs), arriving
    on a working day 1-4 (+ `slip` minutes). Its own random stream: the jobs stay the same."""
    rng = random.Random(seed * 7919 + 1)
    windows = inst.shifts
    fixed = {f.job_id for f in inst.fixed}
    jobs = tuple(
        replace(j, grams_per_part=rng.randint(*_GRAMS_PER_PART[j.process])) for j in inst.jobs
    )
    stock: list[tuple[str, int]] = []
    deliveries: list[Delivery] = []
    for material in sorted({j.material for j in jobs}):
        need = sum(j.grams for j in jobs if j.material == material and j.id not in fixed)
        on_hand = math.floor(cover * need)
        stock.append((material, on_hand))
        rest = need - on_hand
        at = windows[rng.randint(1, 4)][0] + rng.randint(0, 240)
        if rest > 0:
            packs = math.ceil(rest / PACK_GRAMS)
            deliveries.append(Delivery(material, at + slip, packs * PACK_GRAMS))
    return replace(
        inst,
        name=f"{inst.name}-stock{round(cover * 100)}" + (f"-slip{slip}" if slip else ""),
        jobs=jobs,
        stock=tuple(stock),
        deliveries=tuple(deliveries),
    )
