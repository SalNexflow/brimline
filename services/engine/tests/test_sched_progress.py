"""The progress callback only watches the search: the same instance must give the identical
schedule with and without it (M5 requirement)."""

from brimline_engine.scheduling.baselines import edd
from brimline_engine.scheduling.config import load_scheduler_config
from brimline_engine.scheduling.cpsat import Progress, solve
from brimline_engine.scheduling.generator import generate
from brimline_engine.shop_config import load_shop_config

CFG = load_scheduler_config()


def test_the_same_plan_with_and_without_the_progress_callback() -> None:
    # 40 jobs and a 2 s limit: big enough that the search finds several schedules, so a callback
    # that disturbed it would show.
    inst = generate(2, 40, load_shop_config(), CFG)
    hint = edd(inst, CFG.durations)
    seen: list[Progress] = []
    watched = solve(inst, CFG, hint=hint, deterministic_time=2.0, on_progress=seen.append)
    plain = solve(inst, CFG, hint=hint, deterministic_time=2.0)
    assert watched.plans == plain.plans
    assert watched.unscheduled == plain.unscheduled
    assert len(seen) >= 2  # it really reported, more than once
    assert all(0 <= p.work_done <= 1 for p in seen)
    assert [p.objective for p in seen] == sorted((p.objective for p in seen), reverse=True)
    assert seen[-1].objective == watched.info["solver_objective"]
