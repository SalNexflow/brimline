from datetime import UTC, date, datetime

import pytest

from brimline_engine.dates import shop_today

BERLIN = "Europe/Berlin"


def test_late_evening_utc_is_already_tomorrow_in_berlin() -> None:
    # Summer time ends 2026-10-25 01:00 UTC, so 23:30 UTC that day is 00:30 CET on the 26th.
    assert shop_today(datetime(2026, 10, 25, 23, 30, tzinfo=UTC), BERLIN) == date(2026, 10, 26)


def test_one_hour_earlier_is_still_the_same_day() -> None:
    assert shop_today(datetime(2026, 10, 25, 22, 30, tzinfo=UTC), BERLIN) == date(2026, 10, 25)


def test_during_summer_time_the_offset_is_two_hours() -> None:
    # 22:30 UTC in July is 00:30 CEST the next day.
    assert shop_today(datetime(2026, 7, 1, 22, 30, tzinfo=UTC), BERLIN) == date(2026, 7, 2)


def test_naive_datetimes_are_refused() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        shop_today(datetime(2026, 10, 25, 12, 0), BERLIN)
