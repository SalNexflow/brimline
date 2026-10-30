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


def test_failure_reasons_are_the_same_in_config_engine_and_database() -> None:
    import re
    from typing import get_args

    from brimline_engine.costing.config import costing_config
    from brimline_engine.planning.queues import FailureReason
    from brimline_engine.settings import REPO_ROOT

    operator_reasons = costing_config().failure_reasons
    assert list(get_args(FailureReason)) == operator_reasons
    sql = (REPO_ROOT / "db" / "migrations" / "0012_costing.sql").read_text(encoding="utf-8")
    listed = re.search(r"failure_reason IN\s*\(([^)]*)\)", sql)
    assert listed is not None
    in_database = re.findall(r"'([a-z_]+)'", listed.group(1))
    assert in_database == [*operator_reasons, "machine_down", "order_cancelled"]
