"""The hosted demo's database (M11): the seed moved to this week, with a plan already approved,
so the board is useful on the first visit. Run by `reset --demo` (nightly, and on deploy).

Dates move by whole weeks, so every order keeps its weekday and its distance from "today";
nothing else in the seed changes. The plan is made and approved by the same code a planner
uses (and checked by the independent checker on the way, as always)."""

import uuid
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import psycopg
from psycopg_pool import ConnectionPool

from brimline_engine.demo import effective_scheduler_config
from brimline_engine.permissions import Actor
from brimline_engine.planning import runs, schedules
from brimline_engine.shop_config import ShopConfig


def _monday(d: date) -> date:
    return d - timedelta(days=d.weekday())


def shifted(cfg: ShopConfig, today: date) -> ShopConfig:
    """The same shop with every date moved by whole weeks so its Monday is this Monday."""
    tz = ZoneInfo(cfg.shop.time_zone)
    seeded = cfg.seed_time.astimezone(tz).date()
    delta = _monday(today) - _monday(seeded)
    return cfg.model_copy(
        update={
            "seed_time": cfg.seed_time + delta,
            "orders": [o.model_copy(update={"due_date": o.due_date + delta}) for o in cfg.orders],
            # Never later than the moved seed date: the seed's prices start a few days after its
            # Monday, which moved forward would put them in the future (no price on day one).
            "price_rules": cfg.price_rules.model_copy(
                update={
                    "effective_from": min(
                        cfg.price_rules.effective_from + delta, (cfg.seed_time + delta).date()
                    )
                }
            ),
        }
    )


def plan_and_approve(app_url: str, now: datetime, tz: str) -> int:
    """Plan day and approve it as the demo planner. Returns the approved schedule's id."""
    cfg = effective_scheduler_config()
    with psycopg.connect(app_url, autocommit=True) as conn:
        row = conn.execute("SELECT id FROM users WHERE code = 'U-PLANNER'").fetchone()
        assert row is not None
        planner = Actor(user_id=int(row[0]), role="planner", customer_id=None)
        run, _ = runs.start_run(conn, planner, f"demo-seed-{uuid.uuid4()}")
    with ConnectionPool(app_url, min_size=1, max_size=2, open=True) as pool:
        runs.execute_run(pool, run.id, now, cfg, tz)
    with psycopg.connect(app_url, autocommit=True) as conn:
        done = runs.get_run(conn, planner, run.id)
        if done.schedule_id is None:
            raise RuntimeError(f"the demo plan did not finish: {done.status} {done.error}")
        schedules.approve(
            conn, planner, done.schedule_id, f"demo-approve-{uuid.uuid4()}", now, cfg, tz
        )
        return done.schedule_id
