"""Shop time and plan minutes.

A plan counts whole minutes from its anchor, Monday 08:00 shop time of the week it was made in
(docs/SCHEDULE_RULES.md). Minutes are wall-clock minutes in the shop's time zone, so every day
is 1440 minutes and 08:00 is always minute 1440 * day: the shifts stay where the people are
when the clocks change. The price: across a clock change, a task's real length differs from
its minute count by an hour (stated in the README's limits).
"""

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

DAY_START = time(8, 0)


def anchor_for(now: datetime, tz: str) -> datetime:
    """Monday 08:00 shop time of the week `now` falls in (in UTC). Before 08:00 on a Monday
    it is still that Monday: minute 0 can lie in the future only by those few hours, and
    plan_start (now) is then negative, which no rule forbids."""
    local = now.astimezone(ZoneInfo(tz))
    monday = local.date() - timedelta(days=local.weekday())
    return datetime.combine(monday, DAY_START, ZoneInfo(tz)).astimezone(UTC)


def _wall(dt: datetime, tz: str) -> datetime:
    return dt.astimezone(ZoneInfo(tz)).replace(tzinfo=None)


def minute_of(dt: datetime, anchor: datetime, tz: str) -> int:
    """The plan minute that `dt` falls in (rounded down)."""
    return int((_wall(dt, tz) - _wall(anchor, tz)) // timedelta(minutes=1))


def minute_at_or_after(dt: datetime, anchor: datetime, tz: str) -> int:
    """The first whole plan minute that is not before `dt`."""
    m = minute_of(dt, anchor, tz)
    return m if at_minute(m, anchor, tz) >= dt else m + 1


def at_minute(minute: int, anchor: datetime, tz: str) -> datetime:
    """The moment (UTC) of a plan minute. In the hour that happens twice when clocks go back,
    the first one is meant."""
    wall = _wall(anchor, tz) + timedelta(minutes=minute)
    return wall.replace(tzinfo=ZoneInfo(tz)).astimezone(UTC)


def due_minute(due: date, day_end: time, anchor: datetime, tz: str) -> int:
    """An order due on a date is due at the end of that day's shift (`day_end`)."""
    return minute_of(datetime.combine(due, day_end, ZoneInfo(tz)), anchor, tz)
