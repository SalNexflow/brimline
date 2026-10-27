"""Time phrases from disruption messages, resolved by code in shop time (never by a model).

The model copies a time exactly as written ("until 5pm", "bis 17 Uhr", "mañana a las 9"); this
module turns it into a moment, from when the message arrived. It is a small, explicit grammar,
and it refuses rather than guesses:

- a phrase it cannot read completely is `unknown` (the planner is asked);
- a vague phrase ("later", "soon") is `unknown`;
- a numeric date that is valid in two readings (12/11: 12 November or 11 December) is
  `needs_confirmation`, with both readings, and nothing is chosen;
- a clock time without a day means today, or tomorrow if it has already passed; except for
  when something started ("down since 15:00"), which may well be in the past;
- a day without a time means the start of that day's shift;
- a bare hour from 1 to 7 ("till 3") means the afternoon: the shop is closed at 3 in the night.

Supported words are English, German, Spanish and French (tests/test_planning_when.py).
"""

import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

Kind = Literal["time", "none", "unknown", "needs_confirmation"]


@dataclass(frozen=True)
class Resolved:
    kind: Kind
    at: datetime | None = None  # in UTC, when kind is "time"
    readings: tuple[datetime, ...] = ()  # the candidate moments, when kind is "needs_confirmation"
    note: str = ""  # why, in plain words, when it is not a time

    @staticmethod
    def unknown(note: str) -> "Resolved":
        return Resolved("unknown", note=note)


# --- Words --------------------------------------------------------------------------------------

FILLER = {
    "until",
    "till",
    "til",
    "untill",
    "by",
    "at",
    "around",
    "about",
    "approx",
    "approximately",
    "ca",
    "from",
    "since",
    "seit",
    "desde",
    "depuis",
    "on",
    "the",
    "of",
    "o'clock",
    "oclock",
    "back",
    "done",
    "ready",
    "bis",
    "um",
    "ab",
    "gegen",
    "etwa",
    "am",
    "uhr",
    "hasta",
    "a",
    "las",
    "la",
    "el",
    "de",
    "del",
    "sobre",
    "para",
    "jusqu'à",
    "jusqu'a",
    "jusqu",
    "à",
    "vers",
    "le",
    "du",
    "pour",
    "dès",
}
VAGUE = {
    "later",
    "soon",
    "while",
    "sometime",
    "asap",
    "shortly",
    "afternoon",
    "evening",
    "tonight",
    "unknown",
    "später",
    "bald",
    "nachmittag",
    "abend",
    "luego",
    "pronto",
    "tarde",
    "bientôt",
    "plus",
    "tard",
    "après-midi",
    "soir",
    "tbd",
    "idk",
    "?",
}
# Said as several words; each becomes "morning" before anything else is read.
MORNING_PHRASES = (
    "de la mañana",
    "de la manana",
    "por la mañana",
    "por la manana",
    "in the morning",
    "du matin",
    "le matin",
)
NOW = {"now", "jetzt", "sofort", "ahora", "maintenant", "immediately", "right"}
TODAY = {"today", "heute", "hoy", "aujourd'hui", "aujourdhui"}
TOMORROW = {"tomorrow", "tmrw", "tmr", "morgen", "mañana", "manana", "demain"}
MORNING = {"morning", "früh", "frueh", "vormittag", "matin"}
END_OF_DAY = {
    "eod",
    "close",
    "closing",
    "feierabend",
    "dienstschluss",
    "schichtende",
    "cierre",
    "fermeture",
}
END_OF_DAY_PHRASES = (
    "end of day",
    "end of the day",
    "end of shift",
    "end of the shift",
    "close of business",
    "fin del día",
    "fin del dia",
    "fin de journée",
    "fin de journee",
    "fin de la journée",
    "fin de la journee",
    "ende des tages",
    "tagesende",
)
NOON = {"noon", "midday", "mittag", "mittags", "mediodía", "mediodia", "midi"}
WEEKDAYS: dict[str, int] = {}
for i, names in enumerate(
    (
        ("monday", "mon", "montag", "lunes", "lundi"),
        ("tuesday", "tue", "tues", "dienstag", "martes", "mardi"),
        ("wednesday", "wed", "mittwoch", "miércoles", "miercoles", "mercredi"),
        ("thursday", "thu", "thur", "thurs", "donnerstag", "jueves", "jeudi"),
        ("friday", "fri", "freitag", "viernes", "vendredi"),
        ("saturday", "sat", "samstag", "sábado", "sabado", "samedi"),
        ("sunday", "sun", "sonntag", "domingo", "dimanche"),
    )
):
    for name in names:
        WEEKDAYS[name] = i
MONTHS: dict[str, int] = {}
for i, names in enumerate(
    (
        ("january", "jan", "januar", "jänner", "enero", "janvier", "janv"),
        ("february", "feb", "februar", "febrero", "février", "fevrier", "févr"),
        ("march", "mar", "märz", "maerz", "marzo", "mars"),
        ("april", "apr", "abril", "avril"),
        ("may", "mai", "mayo"),
        ("june", "jun", "juni", "junio", "juin"),
        ("july", "jul", "juli", "julio", "juillet"),
        ("august", "aug", "agosto", "août", "aout"),
        ("september", "sep", "sept", "septiembre", "septembre"),
        ("october", "oct", "okt", "oktober", "octubre", "octobre"),
        ("november", "nov", "noviembre", "novembre"),
        ("december", "dec", "dez", "dezember", "diciembre", "décembre", "decembre"),
    ),
    start=1,
):
    for name in names:
        MONTHS[name] = i
WORD_NUMBERS = {
    "a": 1,
    "an": 1,
    "one": 1,
    "eine": 1,
    "einer": 1,
    "una": 1,
    "un": 1,
    "une": 1,
    "two": 2,
    "zwei": 2,
    "dos": 2,
    "deux": 2,
    "three": 3,
    "drei": 3,
    "tres": 3,
    "trois": 3,
}


# --- Parsing ------------------------------------------------------------------------------------


@dataclass
class _Parts:
    day: date | None = None
    days: tuple[date, ...] = ()  # two readings of an ambiguous date
    clock: time | None = None
    end_of_day: bool = False
    morning: bool = False
    relative: timedelta | None = None
    now: bool = False


def _valid(y: int, m: int, d: int) -> date | None:
    try:
        return date(y, m, d)
    except ValueError:
        return None


def _nearest(month: int, day: int, today: date, past_ok: bool) -> date | None:
    """A date without a year: the next one not in the past, or, for when something started
    (past_ok), the most recent one not in the future."""
    years = (today.year - 1, today.year) if past_ok else (today.year, today.year + 1)
    for year in reversed(years) if past_ok else years:
        found = _valid(year, month, day)
        if found is not None and (found <= today if past_ok else found >= today):
            return found
    return None


def _take(pattern: str, text: str) -> tuple[re.Match[str] | None, str]:
    m = re.search(pattern, text)
    if m is None:
        return None, text
    return m, (text[: m.start()] + " " + text[m.end() :])


def _parse(phrase: str, today: date, past_ok: bool = False) -> _Parts | str:
    """The parts of a phrase, or the reason it cannot be read."""
    text = " " + phrase.lower().replace(",", " ").replace(";", " ") + " "
    parts = _Parts()

    for ending in END_OF_DAY_PHRASES:
        if ending in text:
            parts.end_of_day = True
            text = text.replace(ending, " ")

    # "in 2 hours", "in einer Stunde", "dans 2 heures", "en 2 horas", and "another 2 hours",
    # "noch 2 Stunden", "encore 2 heures" (d10 on the dev set), or "2 more hours", "2 hours more"
    unit_words = r"(min|mins|minutes?|minuten|minutos?|h|hrs?|hours?|stunden?|std|horas?|heures?)"
    count_word = r"(\d+(?:[.,]5)?|[a-zäéè]+)"
    m, text = _take(
        rf"\b(?:in|dans|en|another|noch|encore|otras?)\s+{count_word}\s*{unit_words}\b", text
    )
    if m is None:
        m, text = _take(rf"\b{count_word}\s*more\s+{unit_words}\b", text)
    if m is None:
        m, text = _take(rf"\b{count_word}\s*{unit_words}\s+(?:more|más|mas|de plus)\b", text)
    if m is not None:
        raw = m.group(1).replace(",", ".")
        count = float(raw) if re.fullmatch(r"\d+(\.5)?", raw) else WORD_NUMBERS.get(raw)
        if count is None:
            return f"cannot read the number in '{m.group(0).strip()}'"
        unit = 1 if m.group(2).startswith("m") else 60  # minutes, or hours in any language
        parts.relative = timedelta(minutes=count * unit)
    m, text = _take(
        r"\b(?:in\s+)?(?:half an hour|einer halben stunde|media hora|une demi-heure)\b", text
    )
    if m is not None:
        parts.relative = timedelta(minutes=30)

    # Morning phrases first, so "de la mañana" is not read as "tomorrow" and "heute morgen"
    # (this morning) not as "tomorrow" (review of M6).
    for spoken in MORNING_PHRASES:
        text = text.replace(spoken, " morning ")
    text = re.sub(
        r"\b(heute|" + "|".join(sorted(WEEKDAYS, key=len, reverse=True)) + r")\s+morgen\b",
        r"\1 morning",
        text,
    )

    def set_day(found: date, source: str) -> str | None:
        if parts.day is not None and parts.day != found:
            return f"'{phrase}' names two different days ({parts.day:%a %d %b} and {found:%a %d %b}, {source})"
        parts.day = found
        return None

    # Numeric dates, only where they cannot be a time: "12/11", "12/11/2026", "03.11.",
    # "03.11.2026". "3.11" or "10.10" without a final dot could be a date or a time: refused.
    m, text = _take(r"\b(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?(?=\s)", text)
    if m is None:
        m, text = _take(r"\b(\d{1,2})\.(\d{1,2})\.(\d{2,4})?(?=\s)", text)
    if m is not None:
        a, b = int(m.group(1)), int(m.group(2))
        year = int(m.group(3)) if (m.lastindex or 0) >= 3 and m.group(3) else None
        if year is not None and year < 100:
            year += 2000

        def reading(day_: int, month: int) -> date | None:
            return _valid(year, month, day_) if year else _nearest(month, day_, today, past_ok)

        found = {d for d in (reading(a, b), reading(b, a)) if d is not None}
        if not found:
            return f"'{m.group(0).strip()}' is not a date"
        if len(found) == 2:
            parts.days = tuple(sorted(found))
        elif (problem := set_day(found.pop(), "date")) is not None:
            return problem
    if re.search(r"\b(0?[1-9]|1[0-2])\.(0?[1-9]|1[0-2])(?=\s)(?!\s*(?:uhr|h)\b)", text):
        return f"'{phrase}' could be a date or a time; write it as 10/11 or 10:10"
    month_names = "|".join(sorted(map(re.escape, MONTHS), key=len, reverse=True))
    m, text = _take(rf"\b(\d{{1,2}})\.?\s*(?:de\s+)?({month_names})\.?(?:\s+(\d{{4}}))?\b", text)
    if m is None:
        m, text = _take(rf"\b({month_names})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?\b", text)
        if m is not None:
            month, day_, year_txt = MONTHS[m.group(1)], int(m.group(2)), None
    else:
        month, day_, year_txt = MONTHS[m.group(2)], int(m.group(1)), m.group(3)
    if m is not None:
        found_day = (
            _valid(int(year_txt), month, day_)
            if year_txt
            else _nearest(month, day_, today, past_ok)
        )
        if found_day is None:
            return f"'{m.group(0).strip()}' is not a date"
        if (problem := set_day(found_day, "date")) is not None:
            return problem

    # A day of the month on its own ("le 3", "el 12", "the 3rd") is not a time.
    if re.search(r"\b(?:le|el|the|den|der|am|du)\s+\d{1,2}(?:st|nd|rd|th|er|\.)?(?=\s)", text):
        return f"'{phrase}' gives a day of the month without the month"

    # Clock times: "17:00", "17.30", "5pm", "5 p.m.", "17 uhr", "17h", "17h30", "9 am". Without
    # am/pm, 1 to 7 o'clock means the afternoon (the shop is closed at night) unless a morning
    # word says otherwise; decided after the words are read, so "tomorrow morning at 7" is 07:00.
    hour: int | None = None
    minute = 0
    explicit = False
    m, text = _take(r"\b(\d{1,2})\s*(?:[:.h]\s*(\d{2}))?\s*(a\.?m\.?|p\.?m\.?)(?=\s)", text)
    if m is not None:
        hour, minute = int(m.group(1)), int(m.group(2) or 0)
        if not 1 <= hour <= 12 or minute > 59:
            return f"'{m.group(0).strip()}' is not a time"
        hour = (hour % 12) + (12 if m.group(3).startswith("p") else 0)
        explicit = True
    else:
        m, text = _take(r"\b(\d{1,2})\s*(?::|h|\.)\s*(\d{2})\b", text)
        if m is None:
            m, text = _take(r"\b(\d{1,2})\s*(?:uhr|h)\b", text)
            explicit = m is not None  # "7 Uhr" is 07:00 as written
        if m is None:
            m, text = _take(r"(?<=\s)(\d{1,2})(?=\s)", text)
        if m is not None:
            hour = int(m.group(1))
            minute = int(m.group(2)) if m.lastindex and m.lastindex >= 2 and m.group(2) else 0
            if hour > 23 or minute > 59 or (hour == 0 and not explicit and minute == 0):
                return f"'{m.group(0).strip()}' is not a time"

    words = [w.strip(".!") for w in text.split()]
    leftover = []
    for w in words:
        if not w:
            continue
        if w in VAGUE:
            return f"'{phrase}' is too vague to plan with"
        if w in NOW:
            parts.now = True
        elif w in TODAY:
            if (problem := set_day(today, "today")) is not None:
                return problem
        elif w in TOMORROW:
            if (problem := set_day(today + timedelta(days=1), "tomorrow")) is not None:
                return problem
        elif w in WEEKDAYS:
            if parts.day is not None:  # a weekday next to a date must agree with it
                if parts.day.weekday() != WEEKDAYS[w]:
                    return f"'{phrase}': {parts.day:%d %b} is not a {w}"
                continue
            if past_ok:  # when something started: the most recent such day, today included
                parts.day = today - timedelta(days=(today.weekday() - WEEKDAYS[w]) % 7)
            else:  # strictly after today
                parts.day = today + timedelta(days=(WEEKDAYS[w] - today.weekday() - 1) % 7 + 1)
        elif w in NOON:
            hour, minute, explicit = 12, 0, True
        elif w in MORNING:
            parts.morning = True
        elif w in END_OF_DAY:
            parts.end_of_day = True
        elif w in FILLER:
            continue
        else:
            leftover.append(w)
    if leftover:
        return f"cannot read '{' '.join(leftover)}' in '{phrase}'"
    if hour is not None:
        if not explicit and 1 <= hour <= 7 and not parts.morning:
            hour += 12  # "till 3", "back at 3:30": the afternoon
        if parts.morning and hour >= 12:
            return f"'{phrase}' says morning but gives {hour}:{minute:02d}"
        parts.clock = time(hour, minute)
    return parts


def _shift_bounds(day: date, shifts: dict[str, tuple[str, str]]) -> tuple[time, time]:
    hours = shifts.get(str(day.isoweekday()))
    if hours is None:
        return time(8, 0), time(17, 0)  # a closed day: ordinary hours
    return time.fromisoformat(hours[0]), time.fromisoformat(hours[1])


def resolve(
    phrase: str | None,
    received: datetime,
    tz: str,
    shifts: dict[str, tuple[str, str]],
    *,
    past_ok: bool = False,
) -> Resolved:
    """The moment a phrase means, from when the message was received (see the module doc)."""
    if phrase is None or not phrase.strip():
        return Resolved("none")
    zone = ZoneInfo(tz)
    local = received.astimezone(zone)
    parsed = _parse(phrase, local.date(), past_ok)
    if isinstance(parsed, str):
        return Resolved.unknown(parsed)
    p = parsed

    if p.relative is not None:
        if p.day or p.days or p.clock or p.end_of_day:
            return Resolved.unknown(f"'{phrase}' mixes a duration with a date or time")
        return Resolved("time", received + p.relative)
    if p.now and not (p.day or p.days or p.clock or p.end_of_day):
        return Resolved("time", received)

    def at(day: date) -> datetime:
        start, end = _shift_bounds(day, shifts)
        clock = p.clock or (end if p.end_of_day else start)
        return datetime.combine(day, clock, zone)

    if p.days:
        return Resolved(
            "needs_confirmation",
            readings=tuple(at(d).astimezone(ZoneInfo("UTC")) for d in p.days),
            note=f"'{phrase}' can be read as {p.days[0]:%d %b} or {p.days[1]:%d %b}",
        )
    if p.day is None and p.clock is None and not p.end_of_day and not p.morning:
        return Resolved.unknown(f"'{phrase}' has no time in it")
    if p.day is not None:
        moment = at(p.day)
    else:
        moment = at(local.date())
        if moment <= local and not past_ok:  # already passed today: the same time tomorrow
            moment = at(local.date() + timedelta(days=1))
    if past_ok and moment > local:
        return Resolved.unknown(f"'{phrase}' is after the message was sent")
    if not past_ok and moment <= local:
        return Resolved.unknown(f"'{phrase}' is already in the past")
    return Resolved("time", moment.astimezone(ZoneInfo("UTC")))
