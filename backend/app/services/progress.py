"""Planned and actual progress: pure functions, no database, easy to test.

Weighted progress
    Each task carries a weight: its share of the contract, in percent. Project progress is the
    weighted mean of task progress, divided by the total weight, so the curve still ends at 100 %
    when the weights do not add up to exactly 100.

Planned curve
    Within a task, planned work is spread evenly over its calendar days (a task from 1 to 10 March
    is 50 % planned on the end of 5 March). Summing straight lines with different weights and dates
    gives the familiar S-curve.

Actual progress
    The weighted mean of each task's reported percent complete.
"""

from bisect import bisect_right
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

WEEK = timedelta(days=7)


@dataclass(frozen=True, slots=True)
class TaskPlan:
    planned_start: date
    planned_end: date
    weight: Decimal
    percent_complete: Decimal = Decimal(0)


def _total_weight(tasks: Iterable[TaskPlan]) -> Decimal:
    return sum((t.weight for t in tasks), Decimal(0))


def planned_fraction(task: TaskPlan, on: date) -> float:
    """Share of the task planned to be done by the *end* of ``on`` (0.0 to 1.0)."""
    days = (task.planned_end - task.planned_start).days + 1
    done = (on - task.planned_start).days + 1
    return min(max(done / days, 0.0), 1.0)


def planned_percent(tasks: Sequence[TaskPlan], on: date) -> float:
    total = _total_weight(tasks)
    if total <= 0:
        return 0.0
    weighted = sum(float(t.weight) * planned_fraction(t, on) for t in tasks)
    return round(weighted / float(total) * 100, 2)


def actual_percent(tasks: Sequence[TaskPlan]) -> float:
    total = _total_weight(tasks)
    if total <= 0:
        return 0.0
    weighted = sum(t.weight * t.percent_complete for t in tasks)
    return round(float(weighted / total), 2)


def week_dates(start: date, end: date) -> list[date]:
    """Weekly points from ``start`` to ``end``, always including ``end`` itself."""
    if end < start:
        return [start]
    points = []
    current = start
    while current < end:
        points.append(current)
        current += WEEK
    points.append(end)
    return points


@dataclass(frozen=True, slots=True)
class CurvePoint:
    on: date
    planned: float
    actual: float | None


def progress_curve(
    tasks: Sequence[TaskPlan],
    *,
    start: date,
    end: date,
    today: date,
    snapshots: Sequence[tuple[date, float]],
) -> list[CurvePoint]:
    """Planned percent for every week, with the actual percent known on each date up to today.

    ``snapshots`` is the recorded history of actual progress (one value per day, any order). A week
    shows the latest snapshot on or before it; weeks before the first snapshot show 0 % once the
    project has started. Today's point always shows the live value from the tasks.
    """
    history = sorted(snapshots)
    history_days = [day for day, _ in history]
    points: list[CurvePoint] = []
    dates = week_dates(start, end)
    if start <= today <= end and today not in dates:
        dates = sorted([*dates, today])

    for on in dates:
        actual: float | None = None
        if on == today:
            actual = actual_percent(tasks)
        elif on < today:
            index = bisect_right(history_days, on)  # latest snapshot on or before this date
            actual = history[index - 1][1] if index else 0.0
        points.append(CurvePoint(on=on, planned=planned_percent(tasks, on), actual=actual))
    return points
