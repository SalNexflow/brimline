"""Time phrases resolved by code (M6). Expected moments worked out by hand.

The message arrives on Tuesday 2026-11-03 at 15:20 in Berlin (winter time, UTC+1). Shifts:
Mon-Fri 08:00-17:00, Saturday 09:00-13:00, no Sunday.
"""

from datetime import UTC, datetime, timedelta, timezone

import pytest

from brimline_engine.planning.when import resolve
from brimline_engine.scheduling.config import load_scheduler_config

TZ = "Europe/Berlin"
SHIFTS = load_scheduler_config().shifts.weekdays
RECEIVED = datetime(2026, 11, 3, 15, 20, tzinfo=timezone(timedelta(hours=1)))
BERLIN = timezone(timedelta(hours=1))


def berlin(month: int, day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, month, day, hour, minute, tzinfo=BERLIN).astimezone(UTC)


@pytest.mark.parametrize(
    ("phrase", "expected"),
    [
        # Clock times today; one that has passed means tomorrow.
        ("until 5pm", berlin(11, 3, 17)),
        ("5 p.m.", berlin(11, 3, 17)),
        ("17:00", berlin(11, 3, 17)),
        ("bis 17 Uhr", berlin(11, 3, 17)),
        ("17h30", berlin(11, 3, 17, 30)),
        ("hasta las 16.45", berlin(11, 3, 16, 45)),
        ("until 9am", berlin(11, 4, 9)),  # 09:00 has passed today
        ("till 3", berlin(11, 4, 15)),  # a bare 3 is 15:00, and 15:00 has passed today
        ("till 4", berlin(11, 3, 16)),
        ("noon", berlin(11, 4, 12)),
        # Ends of day and shifts.
        ("end of day", berlin(11, 3, 17)),
        ("bis Feierabend", berlin(11, 3, 17)),
        ("fin de journée", berlin(11, 3, 17)),
        # Days.
        ("tomorrow", berlin(11, 4, 8)),
        ("tomorrow morning", berlin(11, 4, 8)),
        ("morgen früh", berlin(11, 4, 8)),
        ("mañana a las 10", berlin(11, 4, 10)),
        ("demain 14h", berlin(11, 4, 14)),
        ("Thursday", berlin(11, 5, 8)),
        ("Freitag 12:00", berlin(11, 6, 12)),
        ("Saturday", berlin(11, 7, 9)),  # Saturday's shift starts at 09:00
        ("saturday end of day", berlin(11, 7, 13)),
        ("Tuesday", berlin(11, 10, 8)),  # strictly after today: next week's Tuesday
        # Written-out dates, in four languages.
        ("12 Nov", berlin(11, 12, 8)),
        ("Nov 12 at 2pm", berlin(11, 12, 14)),
        ("12. November 10 Uhr", berlin(11, 12, 10)),
        ("12 de noviembre", berlin(11, 12, 8)),
        ("12 novembre", berlin(11, 12, 8)),
        # A numeric date valid in one reading only.
        ("25/11", berlin(11, 25, 8)),
        ("25.11.", berlin(11, 25, 8)),
        # Durations.
        ("in 2 hours", RECEIVED.astimezone(UTC) + timedelta(hours=2)),
        ("in 30 min", RECEIVED.astimezone(UTC) + timedelta(minutes=30)),
        ("in einer Stunde", RECEIVED.astimezone(UTC) + timedelta(hours=1)),
        ("dans 2 heures", RECEIVED.astimezone(UTC) + timedelta(hours=2)),
        ("now", RECEIVED.astimezone(UTC)),
        # "Another" and "more" (found on the dev set: d10, "needs another 2 hours").
        ("another 2 hours", RECEIVED.astimezone(UTC) + timedelta(hours=2)),
        ("2 more hours", RECEIVED.astimezone(UTC) + timedelta(hours=2)),
        ("noch 2 Stunden", RECEIVED.astimezone(UTC) + timedelta(hours=2)),
        ("encore 2 heures", RECEIVED.astimezone(UTC) + timedelta(hours=2)),
        ("another 45 min", RECEIVED.astimezone(UTC) + timedelta(minutes=45)),
        # "For" a while, from when it was reported (the live demo's example, which works at any
        # hour unlike "until 5pm"): received 15:20, so 19:20 and 16:50.
        ("for 4 hours", berlin(11, 3, 19, 20)),
        ("for 90 min", berlin(11, 3, 16, 50)),
    ],
)
def test_phrases_resolve_to_the_moment_they_mean(phrase: str, expected: datetime) -> None:
    r = resolve(phrase, RECEIVED, TZ, SHIFTS)
    assert (r.kind, r.at) == ("time", expected), r.note


@pytest.mark.parametrize("phrase", ["12/11", "03.11.", "5/6"])
def test_a_date_valid_in_two_readings_needs_confirmation(phrase: str) -> None:
    # 12/11 is 12 November or 11 December; nothing is chosen.
    r = resolve(phrase, RECEIVED, TZ, SHIFTS)
    assert r.kind == "needs_confirmation" and r.at is None
    assert len(r.readings) == 2


def test_both_readings_are_offered() -> None:
    r = resolve("12/11", RECEIVED, TZ, SHIFTS)
    assert r.readings == (berlin(11, 12, 8), berlin(12, 11, 8))


def test_the_same_day_and_month_is_one_reading() -> None:
    assert resolve("11/11", RECEIVED, TZ, SHIFTS).at == berlin(11, 11, 8)


@pytest.mark.parametrize(
    "phrase",
    ["later", "soon", "for a while", "this afternoon", "später", "pronto", "plus tard", "asap"],
)
def test_vague_phrases_are_not_guessed(phrase: str) -> None:
    assert resolve(phrase, RECEIVED, TZ, SHIFTS).kind == "unknown"


@pytest.mark.parametrize(
    "phrase",
    ["after the delivery truck", "31/02", "25:00", "when Bob is back", "in some hours"],
)
def test_anything_it_cannot_read_completely_is_unknown(phrase: str) -> None:
    assert resolve(phrase, RECEIVED, TZ, SHIFTS).kind == "unknown"


def test_no_phrase_is_no_time() -> None:
    assert resolve(None, RECEIVED, TZ, SHIFTS).kind == "none"
    assert resolve("  ", RECEIVED, TZ, SHIFTS).kind == "none"


def test_a_start_time_in_the_past_stays_today() -> None:
    # "down since 15:00", received at 15:20: it went down 20 minutes ago, not tomorrow.
    r = resolve("since 15:00", RECEIVED, TZ, SHIFTS, past_ok=True)
    assert r.at == berlin(11, 3, 15)


# --- Found by the fresh-context review of M6: these were read as wrong times ------------------


@pytest.mark.parametrize(
    ("phrase", "expected"),
    [
        # A morning word keeps an early hour in the morning.
        ("tomorrow morning at 7", berlin(11, 4, 7)),
        ("demain matin à 6", berlin(11, 4, 6)),
        ("morgen früh um 6", berlin(11, 4, 6)),
        ("mañana a las 6 de la mañana", berlin(11, 4, 6)),
        # Without one, 1 to 7 o'clock is the afternoon in both forms.
        ("back at 3:30", berlin(11, 3, 15, 30)),
        ("until 5:30", berlin(11, 3, 17, 30)),
        ("bis 7 Uhr", berlin(11, 4, 7)),  # "Uhr" is the hour as written; 07:00 has passed
        # "morgen" after a day word means morning.
        ("bis Montag morgen", berlin(11, 9, 8)),
        # Times written with a dot.
        ("bis 17.30", berlin(11, 3, 17, 30)),
        ("bis 9.05 Uhr", berlin(11, 4, 9, 5)),
        # A weekday that agrees with the date.
        ("Thursday 5 November", berlin(11, 5, 8)),
    ],
)
def test_review_cases_resolve_to_what_was_meant(phrase: str, expected: datetime) -> None:
    r = resolve(phrase, RECEIVED, TZ, SHIFTS)
    assert (r.kind, r.at) == ("time", expected), r.note


@pytest.mark.parametrize(
    "phrase",
    [
        "until 10.10",  # a date or 10:10?
        "3.11",
        "le 3",  # a day of the month without the month
        "el 12",
        "Friday 3 November",  # 3 Nov is a Tuesday
        "tomorrow 15 Nov",  # two different days
        "until tonight",
        "till 0",
        "heute morgen um 14",  # morning, but 14:00
        "12/11/2025",  # in the past
    ],
)
def test_review_cases_are_refused_not_guessed(phrase: str) -> None:
    r = resolve(phrase, RECEIVED, TZ, SHIFTS)
    assert r.kind != "time", (phrase, r.at)


@pytest.mark.parametrize(
    ("phrase", "expected"),
    [
        ("since monday", berlin(11, 2, 8)),  # the most recent Monday
        ("seit 25.10.", berlin(10, 25, 8)),  # only one valid reading; last month, not next year
        ("since 9am", berlin(11, 3, 9)),
    ],
)
def test_a_start_looks_backwards(phrase: str, expected: datetime) -> None:
    r = resolve(phrase, RECEIVED, TZ, SHIFTS, past_ok=True)
    assert (r.kind, r.at) == ("time", expected), r.note


def test_a_start_after_the_message_is_refused() -> None:
    # Received at 15:20: "since 4" is 16:00 today, after the message was sent.
    assert resolve("since 4", RECEIVED, TZ, SHIFTS, past_ok=True).kind == "unknown"
