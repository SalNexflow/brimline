"""The shop's hours are written in two config files: shop.toml (seeded into the database, shown
to people) and scheduler.toml (what plans and the checker use). They must say the same."""

from brimline_engine.scheduling.config import load_scheduler_config
from brimline_engine.shop_config import load_shop_config


def test_shop_hours_are_the_same_in_both_config_files() -> None:
    shop = {
        str(day): (s.starts.strftime("%H:%M"), s.ends.strftime("%H:%M"))
        for s in load_shop_config().shifts
        for day in s.weekdays
    }
    scheduler = {
        day: tuple(hours) for day, hours in load_scheduler_config().shifts.weekdays.items()
    }
    assert shop == scheduler
