"""Phase 11: the dashboard's KPI arithmetic (``app.rules.kpis``)."""

from datetime import date
from decimal import Decimal

from app.rules import kpis
from app.rules.kpis import Progress


def test_progress_kpis_average_only_projects_with_a_programme() -> None:
    result = kpis.progress_kpis(
        [Progress(planned=40.0, actual=30.0, task_count=5), Progress(20.0, 21.0, 3), Progress(90.0, 0.0, 0)]
    )
    assert result.average_actual == 25.5  # (30 + 21) / 2; the project without tasks is left out
    assert result.average_planned == 30.0
    assert result.behind_plan == 1  # 10 points behind; the other is ahead
    assert result.scheduled == 2


def test_behind_plan_needs_more_than_two_points() -> None:
    exactly_two = kpis.progress_kpis([Progress(50.0, 48.0, 1)])
    just_over = kpis.progress_kpis([Progress(50.0, 47.9, 1)])
    assert exactly_two.behind_plan == 0
    assert just_over.behind_plan == 1


def test_progress_kpis_without_programmes() -> None:
    result = kpis.progress_kpis([Progress(10.0, 0.0, 0)])
    assert (result.average_actual, result.average_planned, result.behind_plan, result.scheduled) == (
        None,
        None,
        0,
        0,
    )


def test_weeks_start_on_monday() -> None:
    assert kpis.week_start(date(2026, 10, 12)) == date(2026, 10, 12)  # a Monday
    assert kpis.week_start(date(2026, 10, 18)) == date(2026, 10, 12)  # the Sunday after
    weeks = kpis.trend_weeks(date(2026, 10, 14), weeks=3)
    assert weeks == [date(2026, 9, 28), date(2026, 10, 5), date(2026, 10, 12)]


def test_issue_trend_fills_every_week_and_category() -> None:
    today = date(2026, 10, 14)
    trend = kpis.issue_trend(
        [
            (date(2026, 10, 13), "labour"),
            (date(2026, 10, 12), "labour"),
            (date(2026, 10, 6), "weather"),
            (date(2026, 8, 1), "labour"),  # before the window
            (date(2026, 10, 15), "labour"),  # after today
            (date(2026, 10, 13), "unknown"),  # not a category
        ],
        today,
        ["labour", "weather"],
        weeks=2,
    )
    assert trend == [
        (date(2026, 10, 5), {"labour": 0, "weather": 1}),
        (date(2026, 10, 12), {"labour": 2, "weather": 0}),
    ]


def test_cost_totals_count_projects_forecast_over_budget() -> None:
    totals = kpis.cost_totals(
        [
            (Decimal("100"), Decimal("40"), Decimal("110")),
            (Decimal("200"), Decimal("50"), Decimal("200")),  # exactly on budget is not over
            (Decimal("50"), Decimal("0"), Decimal("45")),
        ]
    )
    assert totals.budget == Decimal("350")
    assert totals.committed == Decimal("90")
    assert totals.forecast_final == Decimal("355")
    assert totals.over_budget == 1


def test_final_cost_range_moves_the_budget_by_the_overrun_range() -> None:
    low, high = kpis.final_cost_range(Decimal("1000000"), -2.5, 7.25)
    assert low == Decimal("975000.00")
    assert high == Decimal("1072500.00")
