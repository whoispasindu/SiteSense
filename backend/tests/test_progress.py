"""Planned and actual progress calculations (the Phase 3 unit tests)."""

from datetime import date
from decimal import Decimal

from app.services.progress import (
    TaskPlan,
    actual_percent,
    planned_fraction,
    planned_percent,
    progress_curve,
    week_dates,
)


def task(start: str, end: str, weight: str, done: str = "0") -> TaskPlan:
    return TaskPlan(date.fromisoformat(start), date.fromisoformat(end), Decimal(weight), Decimal(done))


def test_planned_fraction_is_linear_over_calendar_days() -> None:
    t = task("2026-03-01", "2026-03-10", "10")  # 10 days

    assert planned_fraction(t, date(2026, 2, 28)) == 0.0
    assert planned_fraction(t, date(2026, 3, 1)) == 0.1  # end of the first day
    assert planned_fraction(t, date(2026, 3, 5)) == 0.5
    assert planned_fraction(t, date(2026, 3, 10)) == 1.0
    assert planned_fraction(t, date(2026, 4, 1)) == 1.0


def test_one_day_task_is_done_at_the_end_of_its_day() -> None:
    milestone = task("2026-03-05", "2026-03-05", "5")

    assert planned_fraction(milestone, date(2026, 3, 4)) == 0.0
    assert planned_fraction(milestone, date(2026, 3, 5)) == 1.0


def test_planned_percent_weights_tasks() -> None:
    tasks = [
        task("2026-03-01", "2026-03-10", "30"),  # 100 % planned by 10 March
        task("2026-03-11", "2026-03-20", "70"),  # 0 % planned by 10 March
    ]

    assert planned_percent(tasks, date(2026, 3, 10)) == 30.0
    assert planned_percent(tasks, date(2026, 3, 15)) == 30.0 + 70 * 0.5
    assert planned_percent(tasks, date(2026, 3, 20)) == 100.0


def test_weights_need_not_sum_to_100() -> None:
    tasks = [task("2026-03-01", "2026-03-10", "1"), task("2026-03-11", "2026-03-20", "3")]

    assert planned_percent(tasks, date(2026, 3, 10)) == 25.0
    assert planned_percent(tasks, date(2026, 3, 20)) == 100.0


def test_actual_percent_is_weighted_by_task() -> None:
    tasks = [task("2026-03-01", "2026-03-10", "20", "100"), task("2026-03-11", "2026-03-20", "80", "25")]

    assert actual_percent(tasks) == 20 + 80 * 0.25


def test_no_tasks_or_zero_weight_gives_zero() -> None:
    assert planned_percent([], date(2026, 3, 1)) == 0.0
    assert actual_percent([]) == 0.0
    assert actual_percent([task("2026-03-01", "2026-03-02", "0", "50")]) == 0.0


def test_week_dates_include_the_end() -> None:
    assert week_dates(date(2026, 3, 1), date(2026, 3, 20)) == [
        date(2026, 3, 1), date(2026, 3, 8), date(2026, 3, 15), date(2026, 3, 20),
    ]  # fmt: skip
    assert week_dates(date(2026, 3, 1), date(2026, 3, 1)) == [date(2026, 3, 1)]
    assert week_dates(date(2026, 3, 5), date(2026, 3, 1)) == [date(2026, 3, 5)]


def test_curve_uses_snapshot_history_and_live_value_today() -> None:
    tasks = [task("2026-03-01", "2026-03-28", "100", "40")]
    snapshots = [(date(2026, 3, 9), 15.0), (date(2026, 3, 2), 5.0)]  # unordered on purpose

    curve = progress_curve(
        tasks, start=date(2026, 3, 1), end=date(2026, 3, 28), today=date(2026, 3, 18), snapshots=snapshots
    )

    by_day = {p.on: p for p in curve}
    assert by_day[date(2026, 3, 1)].actual == 0.0  # before the first snapshot
    assert by_day[date(2026, 3, 8)].actual == 5.0  # latest snapshot on or before 8 March
    assert by_day[date(2026, 3, 15)].actual == 15.0
    assert by_day[date(2026, 3, 18)].actual == 40.0  # today: live from the tasks
    assert by_day[date(2026, 3, 22)].actual is None  # the future has no actual
    assert by_day[date(2026, 3, 28)].planned == 100.0
    assert [p.on for p in curve] == sorted(p.on for p in curve)


def test_curve_planned_values_rise_monotonically() -> None:
    tasks = [
        task("2026-01-05", "2026-02-15", "10"),
        task("2026-02-01", "2026-06-30", "55"),
        task("2026-05-01", "2026-09-30", "35"),
    ]

    curve = progress_curve(
        tasks, start=date(2026, 1, 5), end=date(2026, 9, 30), today=date(2026, 1, 1), snapshots=[]
    )

    planned = [p.planned for p in curve]
    assert planned == sorted(planned)
    assert planned[-1] == 100.0
    assert all(p.actual is None for p in curve)  # today is before the start
