"""The working calendar: which days a site works, and arithmetic in working days (Phase 9).

A project works on its own working week (Monday to Saturday by default; ISO weekdays, 1 = Monday)
and never on the company's holidays (Poya days and public holidays, kept by the Company Admin).
Durations, float and slip are counted in working days.

Pure functions over plain values: no database, no clock.
"""

from bisect import bisect_left, bisect_right
from dataclasses import dataclass, field
from datetime import date, timedelta

DEFAULT_WORKING_WEEK = "123456"  # Monday to Saturday
# The calendar's horizon: no search or count runs further than this (30 years). It guards against a
# calendar with no working days left, and keeps a runaway forecast from walking towards year 9999.
MAX_SEARCH_DAYS = 366 * 30
ONE_DAY = timedelta(days=1)


class CalendarError(ValueError):
    """The working week is not valid, or no working day could be found."""


def parse_week(text: str) -> frozenset[int]:
    """Parse a working week such as "123456" (Monday to Saturday): each ISO weekday once, at least one."""
    if not text or len(set(text)) != len(text) or any(c not in "1234567" for c in text):
        raise CalendarError("A working week lists ISO weekdays 1 (Monday) to 7 (Sunday), each once.")
    return frozenset(int(c) for c in text)


@dataclass(frozen=True, slots=True)
class WorkCalendar:
    weekdays: frozenset[int]
    holidays: frozenset[date]
    # Holidays that fall on a working weekday, sorted, so a count can subtract them by bisection.
    _days_off: tuple[date, ...] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        if not self.weekdays or not self.weekdays <= frozenset(range(1, 8)):
            raise CalendarError("A working week needs at least one weekday.")
        off = tuple(sorted(d for d in self.holidays if d.isoweekday() in self.weekdays))
        object.__setattr__(self, "_days_off", off)

    def is_working(self, day: date) -> bool:
        return day.isoweekday() in self.weekdays and day not in self.holidays

    def on_or_after(self, day: date) -> date:
        """The first working day on or after ``day``."""
        for _ in range(MAX_SEARCH_DAYS):
            if self.is_working(day):
                return day
            day += ONE_DAY
        raise CalendarError("No working day found.")

    def on_or_before(self, day: date) -> date:
        for _ in range(MAX_SEARCH_DAYS):
            if self.is_working(day):
                return day
            day -= ONE_DAY
        raise CalendarError("No working day found.")

    def shift(self, day: date, count: int) -> date:
        """The ``count``-th working day after ``day`` (before it when negative); 0 returns ``day``.

        Far targets are approached a block of whole weeks at a time (a week never holds more than
        ``len(weekdays)`` working days, so a block never overshoots); the last stretch is walked.
        """
        forward = count > 0
        remaining = abs(count)
        limit = day + timedelta(days=MAX_SEARCH_DAYS if forward else -MAX_SEARCH_DAYS)
        per_week = len(self.weekdays)
        while remaining > 2 * per_week:
            weeks = remaining // per_week - 1
            if forward:
                target = day + timedelta(weeks=weeks)
                if target > limit:
                    raise CalendarError("No working day found.")
                remaining -= self.count(day + ONE_DAY, target)
            else:
                target = day - timedelta(weeks=weeks)
                if target < limit:
                    raise CalendarError("No working day found.")
                remaining -= self.count(target, day - ONE_DAY)
            day = target
        step = ONE_DAY if forward else -ONE_DAY
        while remaining > 0:
            day += step
            if (forward and day > limit) or (not forward and day < limit):
                raise CalendarError("No working day found.")
            if self.is_working(day):
                remaining -= 1
        return day

    def finish(self, start: date, duration: int) -> date:
        """The last day of work that starts on ``start`` and takes ``duration`` working days (>= 1)."""
        return self.shift(self.on_or_after(start), max(duration, 1) - 1)

    def start(self, finish: date, duration: int) -> date:
        """The first day of work that ends on ``finish`` and takes ``duration`` working days (>= 1)."""
        return self.shift(self.on_or_before(finish), -(max(duration, 1) - 1))

    def count(self, first: date, last: date) -> int:
        """Working days from ``first`` to ``last``, both included (0 if ``last`` is before ``first``)."""
        if last < first:
            return 0
        days = (last - first).days + 1
        if days > MAX_SEARCH_DAYS:
            raise CalendarError("The period is too long to count.")
        weeks, extra = divmod(days, 7)
        weekdays = weeks * len(self.weekdays) + sum(
            1 for i in range(extra) if (first + timedelta(days=i)).isoweekday() in self.weekdays
        )
        return weekdays - (bisect_right(self._days_off, last) - bisect_left(self._days_off, first))

    def gap(self, earlier: date, later: date) -> int:
        """Working days from ``earlier`` to ``later``: positive when ``later`` is later, negative if not.

        It counts the working days after ``earlier`` up to and including ``later``, so the gap between
        two consecutive working days is 1 and between a day and itself is 0.
        """
        if later >= earlier:
            return self.count(earlier + ONE_DAY, later)
        return -self.count(later + ONE_DAY, earlier)
