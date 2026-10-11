"""Phase 9 rules without a database: working calendar, critical path, forecast durations, BR-06.

The networks are small enough to check by hand. Unless a test says otherwise the calendar is Monday
to Friday with no holidays, and 5 January 2026 is a Monday.
"""

import random
from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.rules.calendar import MAX_SEARCH_DAYS, CalendarError, WorkCalendar, parse_week
from app.rules.schedule import (
    Activity,
    CycleError,
    Link,
    ScheduleError,
    analyse,
    creates_cycle,
    is_heavy_rain,
    pour_rain_days,
    remaining_days,
    topological_order,
)

D = Decimal
MON_FRI = WorkCalendar(weekdays=frozenset({1, 2, 3, 4, 5}), holidays=frozenset())
MON = date(2026, 1, 5)


def day(n: int) -> date:
    """5 January 2026 plus n calendar days."""
    return date(2026, 1, 5 + n) if 5 + n <= 31 else date(2026, 2, 5 + n - 31)


# --- Calendar ----------------------------------------------------------------------------------------


def test_the_default_week_is_monday_to_saturday() -> None:
    assert parse_week("123456") == frozenset({1, 2, 3, 4, 5, 6})


@pytest.mark.parametrize("bad", ["", "12345678", "1123", "0123", "abc"])
def test_a_working_week_must_list_weekdays_once(bad: str) -> None:
    with pytest.raises(CalendarError):
        parse_week(bad)


def test_holidays_and_rest_days_are_skipped() -> None:
    poya = date(2026, 1, 7)  # Wednesday
    calendar = WorkCalendar(weekdays=frozenset({1, 2, 3, 4, 5, 6}), holidays=frozenset({poya}))

    assert not calendar.is_working(poya)
    assert not calendar.is_working(date(2026, 1, 11))  # Sunday
    assert calendar.finish(MON, 3) == date(2026, 1, 8)  # Mon, Tue, (Poya), Thu
    assert calendar.finish(MON, 6) == date(2026, 1, 12)  # ... Fri, Sat, (Sun), Mon
    assert calendar.count(MON, date(2026, 1, 11)) == 5
    assert calendar.shift(date(2026, 1, 6), 1) == date(2026, 1, 8)
    assert calendar.shift(date(2026, 1, 8), -1) == date(2026, 1, 6)
    assert calendar.start(date(2026, 1, 8), 3) == MON


def test_gap_counts_working_days_either_way() -> None:
    friday, monday = date(2026, 1, 9), date(2026, 1, 12)

    assert MON_FRI.gap(friday, monday) == 1
    assert MON_FRI.gap(monday, friday) == -1
    assert MON_FRI.gap(friday, friday) == 0
    assert MON_FRI.count(monday, friday) == 0


def test_a_work_start_on_a_rest_day_moves_to_the_next_working_day() -> None:
    assert MON_FRI.on_or_after(date(2026, 1, 10)) == date(2026, 1, 12)  # Saturday -> Monday
    assert MON_FRI.on_or_before(date(2026, 1, 10)) == date(2026, 1, 9)


def test_an_empty_week_is_refused() -> None:
    with pytest.raises(CalendarError):
        WorkCalendar(weekdays=frozenset(), holidays=frozenset())


def test_counts_and_shifts_match_a_day_by_day_walk() -> None:
    """Count and shift jump whole weeks; they must agree with walking the calendar one day at a time."""
    rng = random.Random(9)  # noqa: S311 - a repeatable test sample, not a secret
    for _ in range(300):
        week = frozenset(rng.sample(range(1, 8), rng.randint(1, 7)))
        holidays = frozenset(MON + timedelta(days=rng.randint(-400, 900)) for _ in range(rng.randint(0, 40)))
        calendar = WorkCalendar(weekdays=week, holidays=holidays)
        first = MON + timedelta(days=rng.randint(-200, 200))
        last = first + timedelta(days=rng.randint(-10, 700))
        span = range((last - first).days + 1)
        walked = sum(1 for i in span if calendar.is_working(first + timedelta(days=i)))
        assert calendar.count(first, last) == walked

        steps = rng.randint(-150, 150)
        day, left = first, abs(steps)
        while left:
            day += timedelta(days=1 if steps > 0 else -1)
            left -= calendar.is_working(day)
        assert calendar.shift(first, steps) == day


def test_the_calendar_stops_at_its_horizon() -> None:
    with pytest.raises(CalendarError):
        MON_FRI.shift(MON, 300 * 30)  # more than 30 years of working days
    with pytest.raises(CalendarError):
        MON_FRI.count(MON, MON + timedelta(days=MAX_SEARCH_DAYS))


# --- Critical path ------------------------------------------------------------------------------------


def textbook() -> tuple[list[Activity], list[Link]]:
    """A(3) -> B(2) and A -> C(4); B and C -> D(1). Critical: A, C, D; B has 2 days of float."""
    acts = [
        Activity("A", 3, MON),
        Activity("B", 2, MON),
        Activity("C", 4, MON),
        Activity("D", 1, MON),
    ]
    links = [Link("A", "B"), Link("A", "C"), Link("B", "D"), Link("C", "D")]
    return acts, links


def test_forward_and_backward_pass_on_a_known_network() -> None:
    acts, links = textbook()

    net = analyse(acts, links, MON_FRI)
    t = net.timings

    assert (t["A"].early_start, t["A"].early_finish) == (date(2026, 1, 5), date(2026, 1, 7))
    assert (t["B"].early_start, t["B"].early_finish) == (date(2026, 1, 8), date(2026, 1, 9))
    assert (t["C"].early_start, t["C"].early_finish) == (date(2026, 1, 8), date(2026, 1, 13))
    assert (t["D"].early_start, t["D"].early_finish) == (date(2026, 1, 14), date(2026, 1, 14))
    assert net.finish == date(2026, 1, 14)
    assert (t["B"].late_start, t["B"].late_finish) == (date(2026, 1, 12), date(2026, 1, 13))
    assert {k: v.total_float for k, v in t.items()} == {"A": 0, "B": 2, "C": 0, "D": 0}
    assert [k for k, v in t.items() if v.critical] == ["A", "C", "D"]


def test_a_lag_delays_the_successor_and_can_change_the_critical_path() -> None:
    acts, links = textbook()
    links = [Link("A", "B", lag=3), *links[1:]]

    t = analyse(acts, links, MON_FRI).timings

    assert t["B"].early_start == date(2026, 1, 13)  # Wed 7 finish, 3 days' lag: Thu, Fri, Mon; starts Tue
    assert t["D"].early_start == date(2026, 1, 15)
    assert (t["B"].critical, t["C"].critical) == (True, False)
    assert t["C"].total_float == 1


def test_a_lag_on_a_side_link_cuts_the_predecessors_float() -> None:
    """The backward pass takes the lag off too: A must finish 1 + 2 working days before C starts."""
    acts = [Activity("A", 2, MON), Activity("B", 5, MON), Activity("C", 1, MON)]
    links = [Link("A", "C", lag=2), Link("B", "C")]

    t = analyse(acts, links, MON_FRI).timings

    assert t["C"].early_start == date(2026, 1, 12)  # the day after B finishes on Fri 9
    assert t["A"].late_finish == date(2026, 1, 7)  # Wed: Thu and Fri are the lag, C starts Mon
    assert (t["A"].total_float, t["B"].total_float) == (1, 0)


def test_a_holiday_moves_the_network() -> None:
    acts, links = textbook()
    calendar = WorkCalendar(weekdays=MON_FRI.weekdays, holidays=frozenset({date(2026, 1, 8)}))

    net = analyse(acts, links, calendar)

    assert net.timings["C"].early_start == date(2026, 1, 9)
    assert net.finish == date(2026, 1, 15)


def test_a_planned_start_is_a_start_no_earlier_than() -> None:
    acts = [Activity("A", 2, MON), Activity("B", 2, date(2026, 1, 12))]

    t = analyse(acts, [Link("A", "B")], MON_FRI).timings

    assert t["B"].early_start == date(2026, 1, 12)  # not Wed 7, the day after A
    assert t["A"].total_float == 3  # A may slip to Fri 9 before it delays B


def test_work_under_way_keeps_its_dates() -> None:
    acts = [
        Activity("A", 3, MON, fixed_start=MON, fixed_finish=date(2026, 1, 16)),  # running late
        Activity("B", 2, MON),
    ]

    t = analyse(acts, [Link("A", "B")], MON_FRI).timings

    assert t["A"].early_finish == date(2026, 1, 16)
    assert t["B"].early_start == date(2026, 1, 19)


def test_unconnected_tasks_each_get_float_to_the_end() -> None:
    t = analyse([Activity("A", 5, MON), Activity("B", 2, MON)], [], MON_FRI).timings

    assert (t["A"].total_float, t["B"].total_float) == (0, 3)


def test_an_empty_programme() -> None:
    net = analyse([], [], MON_FRI)

    assert (net.finish, net.timings) == (None, {})


def test_loops_are_found() -> None:
    links = [Link("A", "B"), Link("B", "C"), Link("C", "A")]

    with pytest.raises(CycleError) as raised:
        topological_order(["A", "B", "C", "D"], links)

    assert set(raised.value.members) == {"A", "B", "C"}
    assert creates_cycle(links[:2], "C", "A")
    assert not creates_cycle(links[:2], "A", "C")
    assert creates_cycle([], "A", "A")


@pytest.mark.parametrize("link", [Link("A", "Z"), Link("A", "A")])
def test_bad_links_are_refused(link: Link) -> None:
    with pytest.raises(ScheduleError):
        topological_order(["A", "B"], [link])


# --- Forecast durations -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("pct", "active", "planned", "expected"),
    [
        ("0", 0, 10, 10),  # not started: the planned rate
        ("5", 8, 10, 10),  # under 10%: too early to trust its own rate
        ("40", 3, 10, 6),  # three days in: still the plan
        ("40", 8, 10, 12),  # 5% a day: 60% left takes 12 days
        ("50", 5, 20, 5),  # ahead of plan
        ("10", 50, 10, 100),  # a crawl is capped at ten times the plan
        ("100", 20, 10, 0),
    ],
)
def test_remaining_days(pct: str, active: int, planned: int, expected: int) -> None:
    assert remaining_days(percent_complete=D(pct), active_days=active, planned_duration=planned) == expected


def test_stopped_days_do_not_count_as_work() -> None:
    """BR-11: 40% in 8 working days, then 5 days stopped. The rate stays 5% a day, not 40/13."""
    assert remaining_days(percent_complete=D(40), active_days=8, planned_duration=10) == 12


# --- BR-06 -------------------------------------------------------------------------------------------


@pytest.mark.parametrize(("mm", "heavy"), [("9.9", False), ("10.0", True), ("25", True), (None, False)])
def test_heavy_rain_is_ten_mm_or_more(mm: str | None, heavy: bool) -> None:
    assert is_heavy_rain(D(mm) if mm is not None else None) is heavy


def test_pour_rain_days_are_working_days_in_the_window() -> None:
    rain = {
        date(2026, 1, 6): D("12"),  # Tue, heavy, in the window
        date(2026, 1, 7): D("3"),  # light
        date(2026, 1, 10): D("30"),  # Saturday: not a working day on a Mon-Fri calendar
        date(2026, 1, 20): D("15"),  # after the window
    }

    assert pour_rain_days(MON, date(2026, 1, 16), rain, MON_FRI) == [date(2026, 1, 6)]
