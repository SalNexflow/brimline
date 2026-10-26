"""Shift windows in horizon minutes, and the earliest legal start for each kind of task.

Rules (the same for every scheduler):
- a machine task must START inside a shift, at a minute s with shift_start <= s < shift_end,
  and may run past the end of the shift (prints run overnight);
- a manual task must fit ENTIRELY inside one shift: shift_start <= s and s + duration <= shift_end.
"""

from brimline_engine.scheduling.config import Shifts

MINUTES_PER_DAY = 24 * 60
DAY_START = 8 * 60  # minute 0 of the horizon is Monday 08:00


def _minute_of_day(hhmm: str) -> int:
    hours, minutes = hhmm.split(":")
    return int(hours) * 60 + int(minutes)


def shift_windows(shifts: Shifts) -> tuple[tuple[int, int], ...]:
    """Staffed [start, end) windows over the horizon, in horizon minutes, sorted."""
    windows = []
    for day in range(shifts.horizon_days):
        hours = shifts.weekdays.get(str(day % 7 + 1))
        if hours is None:
            continue
        base = day * MINUTES_PER_DAY - DAY_START
        windows.append((base + _minute_of_day(hours[0]), base + _minute_of_day(hours[1])))
    return tuple(windows)


def horizon_minutes(shifts: Shifts) -> int:
    return shifts.horizon_days * MINUTES_PER_DAY


def earliest_machine_start(t: int, windows: tuple[tuple[int, int], ...]) -> int | None:
    for start, end in windows:
        if t < end:
            return max(t, start)
    return None


def earliest_manual_start(
    t: int, duration: int, windows: tuple[tuple[int, int], ...]
) -> int | None:
    for start, end in windows:
        s = max(t, start)
        if s + duration <= end:
            return s
    return None


def machine_start_ranges(windows: tuple[tuple[int, int], ...]) -> list[tuple[int, int]]:
    """Inclusive [lo, hi] ranges a machine task may start in."""
    return [(start, end - 1) for start, end in windows]


def manual_start_ranges(
    duration: int, windows: tuple[tuple[int, int], ...]
) -> list[tuple[int, int]]:
    """Inclusive [lo, hi] ranges a manual task of this duration may start in."""
    return [(start, end - duration) for start, end in windows if end - duration >= start]
