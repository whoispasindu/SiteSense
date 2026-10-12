"""Portfolio KPI arithmetic (Phase 11): pure functions, so the numbers on the dashboard are tested alone.

The service gathers rows; these functions turn them into the figures the tiles and charts show.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

BEHIND_POINTS = 2.0  # a programme more than this many points behind plan counts as "behind" (the dashboard)
TREND_WEEKS = 8


@dataclass(frozen=True, slots=True)
class Progress:
    planned: float
    actual: float
    task_count: int


@dataclass(frozen=True, slots=True)
class ProgressKpis:
    average_actual: float | None  # None when no project has a programme
    average_planned: float | None
    behind_plan: int
    scheduled: int


def progress_kpis(rows: Iterable[Progress]) -> ProgressKpis:
    """Average progress across projects that have a programme, and how many are behind plan."""
    scheduled = [r for r in rows if r.task_count > 0]
    if not scheduled:
        return ProgressKpis(None, None, 0, 0)
    n = len(scheduled)
    return ProgressKpis(
        average_actual=round(sum(r.actual for r in scheduled) / n, 1),
        average_planned=round(sum(r.planned for r in scheduled) / n, 1),
        behind_plan=sum(1 for r in scheduled if r.actual - r.planned < -BEHIND_POINTS),
        scheduled=n,
    )


def week_start(day: date) -> date:
    """The Monday of ``day``'s week."""
    return day - timedelta(days=day.weekday())


def trend_weeks(today: date, weeks: int = TREND_WEEKS) -> list[date]:
    """The Mondays of the last ``weeks`` weeks, oldest first, ending with this week."""
    this_week = week_start(today)
    return [this_week - timedelta(weeks=weeks - 1 - i) for i in range(weeks)]


def issue_trend(
    issues: Iterable[tuple[date, str]], today: date, categories: Sequence[str], weeks: int = TREND_WEEKS
) -> list[tuple[date, dict[str, int]]]:
    """Confirmed issues per week and category. ``issues`` are (report date, category).

    Every week and every category appears, with zeros, so the chart's axes never jump. Issues
    outside the window are ignored.
    """
    starts = trend_weeks(today, weeks)
    table: dict[date, dict[str, int]] = {start: dict.fromkeys(categories, 0) for start in starts}
    for day, category in issues:
        bucket = table.get(week_start(day))
        if bucket is not None and category in bucket and day <= today:
            bucket[category] += 1
    return [(start, table[start]) for start in starts]


@dataclass(frozen=True, slots=True)
class CostTotals:
    budget: Decimal
    committed: Decimal
    forecast_final: Decimal
    over_budget: int  # projects forecast to finish above budget


def cost_totals(rows: Iterable[tuple[Decimal, Decimal, Decimal]]) -> CostTotals:
    """Sum (budget, committed, forecast final) across projects; count those forecast over budget."""
    budget = committed = final = Decimal(0)
    over = 0
    for b, c, f in rows:
        budget += b
        committed += c
        final += f
        if f > b:
            over += 1
    return CostTotals(budget, committed, final, over)


def final_cost_range(
    budget: Decimal, overrun_low_pct: float, overrun_high_pct: float
) -> tuple[Decimal, Decimal]:
    """The risk model's likely final cost: the budget moved by the low and high ends of the overrun range."""
    cent = Decimal("0.01")
    low = budget * (Decimal(1) + Decimal(str(overrun_low_pct)) / 100)
    high = budget * (Decimal(1) + Decimal(str(overrun_high_pct)) / 100)
    return low.quantize(cent), high.quantize(cent)
