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


# --- Named due-date rules. Expected dates worked out on a calendar by hand. -------------------
# 2026-10-26 is a Monday.

from typing import Any  # noqa: E402

from pydantic import ValidationError  # noqa: E402

from brimline_engine.dates import DueRule, resolve_due  # noqa: E402

MONDAY = date(2026, 10, 26)


@pytest.mark.parametrize(
    ("rule", "today", "expected"),
    [
        ({"kind": "next_weekday", "weekday": "friday"}, MONDAY, date(2026, 10, 30)),
        ({"kind": "next_weekday", "weekday": "monday"}, MONDAY, date(2026, 11, 2)),  # not today
        ({"kind": "next_weekday", "weekday": "friday"}, date(2026, 10, 30), date(2026, 11, 6)),
        ({"kind": "next_weekday", "weekday": "sunday"}, MONDAY, date(2026, 11, 1)),
        ({"kind": "in_days", "count": 10}, MONDAY, date(2026, 11, 5)),
        ({"kind": "in_days", "count": 1}, date(2026, 12, 31), date(2027, 1, 1)),
        ({"kind": "in_weeks", "count": 2}, MONDAY, date(2026, 11, 9)),
        ({"kind": "end_of_month"}, MONDAY, date(2026, 10, 31)),
        ({"kind": "end_of_month"}, date(2028, 2, 3), date(2028, 2, 29)),  # leap year
        ({"kind": "on_date", "month": 11, "day": 6}, MONDAY, date(2026, 11, 6)),
        ({"kind": "on_date", "month": 10, "day": 26}, MONDAY, date(2026, 10, 26)),  # today counts
        ({"kind": "on_date", "month": 1, "day": 15}, MONDAY, date(2027, 1, 15)),  # already past
        ({"kind": "on_date", "year": 2027, "month": 3, "day": 1}, MONDAY, date(2027, 3, 1)),
        ({"kind": "on_date", "month": 2, "day": 30}, MONDAY, None),  # not a real date
        ({"kind": "on_date", "month": 2, "day": 29}, MONDAY, date(2028, 2, 29)),  # next leap day
        ({"kind": "none"}, MONDAY, None),
    ],
)
def test_resolve_due(rule: dict[str, Any], today: date, expected: date | None) -> None:
    assert resolve_due(DueRule.model_validate(rule), today) == expected


def test_a_late_friday_message_counts_from_the_shop_calendar() -> None:
    # 23:30 UTC on Friday 30 Oct is 00:30 on Saturday 31 Oct in Berlin, so "by Friday" is 6 Nov.
    today = shop_today(datetime(2026, 10, 30, 23, 30, tzinfo=UTC), BERLIN)
    assert resolve_due(DueRule(kind="next_weekday", weekday="friday"), today) == date(2026, 11, 6)


@pytest.mark.parametrize(
    "rule",
    [
        {"kind": "next_weekday"},
        {"kind": "in_days"},
        {"kind": "in_days", "count": 0},
        {"kind": "in_weeks", "count": 400},
        {"kind": "none", "count": 3},
        {"kind": "next_weekday", "weekday": "friday", "day": 3},
        {"kind": "on_date", "day": 6},
        {"kind": "on_date", "month": 13, "day": 1},
        {"kind": "soon"},
    ],
)
def test_a_rule_must_mean_exactly_one_thing(rule: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        DueRule.model_validate(rule)
