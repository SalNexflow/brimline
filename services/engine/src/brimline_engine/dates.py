"""Date rules, computed in code (never by a model). The shop's calendar is its own time zone.

A model reading "need it by Friday" does not return a date. It picks a named rule
(next_weekday: friday), and resolve_due() turns that into a date from the moment the message
arrived. The rules and their meaning:

  none          no deadline was given
  on_date       a calendar date; year only if the customer wrote one, else the next such
                date that is not in the past
  next_weekday  the next such weekday strictly after today ("by Friday" said on a Friday means
                the Friday a week later)
  in_days       today plus N days        in_weeks  today plus 7 x N days
  end_of_month  the last day of the current month
"""

import calendar
from datetime import date, datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, model_validator

Weekday = Literal["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
WEEKDAYS: tuple[Weekday, ...] = (
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
)
DueKind = Literal["none", "on_date", "next_weekday", "in_days", "in_weeks", "end_of_month"]

# Which fields each kind uses. All others must be null, so a rule means exactly one thing.
_FIELDS: dict[str, set[str]] = {
    "none": set(),
    "on_date": {"month", "day"},  # year optional
    "next_weekday": {"weekday"},
    "in_days": {"count"},
    "in_weeks": {"count"},
    "end_of_month": set(),
}


def shop_today(now: datetime, time_zone: str) -> date:
    """The calendar date in the shop at the instant `now` (which must be timezone-aware)."""
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    return now.astimezone(ZoneInfo(time_zone)).date()


class DueRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: DueKind
    year: int | None = None
    month: int | None = None
    day: int | None = None
    weekday: Weekday | None = None
    count: int | None = None

    @model_validator(mode="after")
    def fields_match_kind(self) -> "DueRule":
        needed = _FIELDS[self.kind]
        allowed = needed | ({"year"} if self.kind == "on_date" else set())
        given = {
            f for f in ("year", "month", "day", "weekday", "count") if getattr(self, f) is not None
        }
        if missing := needed - given:
            raise ValueError(f"{self.kind} needs {sorted(missing)}")
        if extra := given - allowed:
            raise ValueError(f"{self.kind} does not use {sorted(extra)}")
        if self.count is not None and not 1 <= self.count <= 365:
            raise ValueError("count must be between 1 and 365")
        if self.month is not None and not 1 <= self.month <= 12:
            raise ValueError("month must be between 1 and 12")
        if self.day is not None and not 1 <= self.day <= 31:
            raise ValueError("day must be between 1 and 31")
        return self


def _valid_date(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None  # e.g. 30 February: not a date, so the deadline stays unknown


def resolve_due(rule: DueRule, today: date) -> date | None:
    """The deadline the rule describes, or None if there is none or it is not a real date."""
    match rule.kind:
        case "none":
            return None
        case "on_date":
            assert rule.month is not None and rule.day is not None
            if rule.year is not None:
                return _valid_date(rule.year, rule.month, rule.day)
            # The next year in which this day exists and is not in the past. Eight years always
            # reaches a 29 February (DEFECT_LOG #12: trying only two years missed leap days).
            for year in range(today.year, today.year + 9):
                candidate = _valid_date(year, rule.month, rule.day)
                if candidate is not None and candidate >= today:
                    return candidate
            return None  # e.g. 30 February exists in no year
        case "next_weekday":
            assert rule.weekday is not None
            ahead = (WEEKDAYS.index(rule.weekday) - today.weekday()) % 7
            return today + timedelta(days=ahead or 7)
        case "in_days":
            assert rule.count is not None
            return today + timedelta(days=rule.count)
        case "in_weeks":
            assert rule.count is not None
            return today + timedelta(weeks=rule.count)
        case "end_of_month":
            return date(today.year, today.month, calendar.monthrange(today.year, today.month)[1])
