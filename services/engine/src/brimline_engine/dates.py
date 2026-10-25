"""Date rules, computed in code (never by a model). The shop's calendar is its own time zone."""

from datetime import date, datetime
from zoneinfo import ZoneInfo


def shop_today(now: datetime, time_zone: str) -> date:
    """The calendar date in the shop at the instant `now` (which must be timezone-aware)."""
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    return now.astimezone(ZoneInfo(time_zone)).date()
