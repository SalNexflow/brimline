"""The hosted demo's shop clock: "now" pinned inside a shift (DEMO_CLOCK, e.g. "Mon 10:00").

A visitor may come at any hour, but a print may only start inside a shift (rule R10). So in the demo,
planning, disruptions, the queues, dispatch and the dispatch watcher read the shop's time as that
weekday and time of the current shop week, shown on every page as "Demo time". The rules themselves do
not change. Signing in, records' creation times and everything else keep the real clock.
"""

from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

DAYS = {"Mon": 0, "Tue": 1, "Wed": 2, "Thu": 3, "Fri": 4, "Sat": 5, "Sun": 6}
PATTERN = r"^(Mon|Tue|Wed|Thu|Fri|Sat|Sun) ([01][0-9]|2[0-3]):[0-5][0-9]$"


def shop_time(real: datetime, setting: str | None, tz: str) -> datetime:
    """The shop's "now": the real time, or with a demo clock, that weekday and time of the week the
    real time falls in (shop time zone), in UTC."""
    if not setting:
        return real
    day, hhmm = setting.split()
    local = real.astimezone(ZoneInfo(tz))
    monday = local.date() - timedelta(days=local.weekday())
    at = datetime.combine(
        monday + timedelta(days=DAYS[day]), time.fromisoformat(hhmm), ZoneInfo(tz)
    )
    return at.astimezone(UTC)
