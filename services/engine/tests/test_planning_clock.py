"""Plan minutes and shop time, including the clock change. Expected values worked out by hand:
Europe/Berlin is UTC+2 in summer time and UTC+1 after the last Sunday of October (2026-10-25,
03:00 summer time becomes 02:00)."""

from datetime import UTC, date, datetime, time

from brimline_engine.planning.clock import (
    anchor_for,
    at_minute,
    due_minute,
    minute_at_or_after,
    minute_of,
)

TZ = "Europe/Berlin"


def test_anchor_is_monday_0800_shop_time_of_the_same_week() -> None:
    # Wednesday 2026-10-28 14:00 UTC (15:00 in Berlin): the week's Monday is 2026-10-26, and
    # 08:00 in Berlin (winter time, UTC+1) is 07:00 UTC.
    assert anchor_for(datetime(2026, 10, 28, 14, 0, tzinfo=UTC), TZ) == datetime(
        2026, 10, 26, 7, 0, tzinfo=UTC
    )
    # Sunday night still belongs to the week that started on Monday.
    assert anchor_for(datetime(2026, 11, 1, 22, 0, tzinfo=UTC), TZ) == datetime(
        2026, 10, 26, 7, 0, tzinfo=UTC
    )


def test_minutes_are_wall_clock_minutes_from_the_anchor() -> None:
    anchor = datetime(2026, 10, 26, 7, 0, tzinfo=UTC)  # Monday 08:00 Berlin
    # Tuesday 08:00 Berlin = 07:00 UTC is minute 1440.
    tuesday = datetime(2026, 10, 27, 7, 0, tzinfo=UTC)
    assert minute_of(tuesday, anchor, TZ) == 1440
    assert at_minute(1440, anchor, TZ) == tuesday
    # 30 seconds past a minute rounds down, and the first minute not before it is the next one.
    assert minute_of(datetime(2026, 10, 26, 7, 5, 30, tzinfo=UTC), anchor, TZ) == 5
    assert minute_at_or_after(datetime(2026, 10, 26, 7, 5, 30, tzinfo=UTC), anchor, TZ) == 6
    assert minute_at_or_after(datetime(2026, 10, 26, 7, 5, tzinfo=UTC), anchor, TZ) == 5


def test_across_the_clock_change_shifts_stay_at_0800_shop_time() -> None:
    # Week of Monday 2026-10-19: summer time, 08:00 Berlin = 06:00 UTC. The clocks go back on
    # Sunday the 25th, so the next Monday 08:00 Berlin is 07:00 UTC, yet still minute 7 x 1440.
    anchor = anchor_for(datetime(2026, 10, 21, 12, 0, tzinfo=UTC), TZ)
    assert anchor == datetime(2026, 10, 19, 6, 0, tzinfo=UTC)
    assert at_minute(7 * 1440, anchor, TZ) == datetime(2026, 10, 26, 7, 0, tzinfo=UTC)
    assert minute_of(datetime(2026, 10, 26, 7, 0, tzinfo=UTC), anchor, TZ) == 7 * 1440


def test_an_order_is_due_at_the_end_of_its_day() -> None:
    anchor = datetime(2026, 10, 26, 7, 0, tzinfo=UTC)
    # Due Thursday 2026-10-29 at 17:00: 3 days and 9 hours after Monday 08:00.
    assert due_minute(date(2026, 10, 29), time(17, 0), anchor, TZ) == 3 * 1440 + 540
    # An order due before this week is already late: a negative minute.
    assert due_minute(date(2026, 10, 23), time(17, 0), anchor, TZ) == -3 * 1440 + 540
