"""The hosted demo's shop clock (demo_clock.py), worked out by hand. Berlin: summer time (UTC+2) until
Sun 25 Oct 2026 03:00, winter time (UTC+1) after."""

from datetime import UTC, datetime

import pytest

from brimline_engine.demo_clock import shop_time

TZ = "Europe/Berlin"


@pytest.mark.parametrize(
    ("real", "expected"),
    [
        # Sunday evening 1 Nov belongs to the week of Monday 26 Oct: Mon 10:00 CET = 09:00 UTC.
        (datetime(2026, 11, 1, 19, 0, tzinfo=UTC), datetime(2026, 10, 26, 9, 0, tzinfo=UTC)),
        # Wednesday 4 Nov at 04:00 Berlin: the week of Monday 2 Nov.
        (datetime(2026, 11, 4, 3, 0, tzinfo=UTC), datetime(2026, 11, 2, 9, 0, tzinfo=UTC)),
        # Monday 19 Oct, summer time: Mon 10:00 CEST = 08:00 UTC.
        (datetime(2026, 10, 19, 22, 30, tzinfo=UTC), datetime(2026, 10, 19, 8, 0, tzinfo=UTC)),
        # 23:30 UTC on Sunday 25 Oct is already Monday 26 Oct 00:30 in Berlin: the new week.
        (datetime(2026, 10, 25, 23, 30, tzinfo=UTC), datetime(2026, 10, 26, 9, 0, tzinfo=UTC)),
    ],
)
def test_the_demo_clock_is_monday_ten_of_the_shop_week(real: datetime, expected: datetime) -> None:
    assert shop_time(real, "Mon 10:00", TZ) == expected


def test_without_a_demo_clock_it_is_the_real_time() -> None:
    real = datetime(2026, 11, 1, 19, 0, tzinfo=UTC)
    assert shop_time(real, None, TZ) is real


def test_a_malformed_demo_clock_is_refused() -> None:
    from pydantic import ValidationError

    from brimline_engine.settings import Settings

    with pytest.raises(ValidationError):
        Settings(demo_clock="Monday 10am")  # type: ignore[call-arg]
