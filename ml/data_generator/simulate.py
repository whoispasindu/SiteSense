"""Synthetic construction projects, simulated week by week, for training the risk model.

Real project histories are hard to get, so v1 of the risk model is trained on simulated projects.
Every assumption is written down here (and summarised in ``ASSUMPTIONS.md``); weather comes from
real Open-Meteo rainfall (``rainfall.csv``). The output is one row per project per week: the
features the app can compute from live data at that point, and the project's final outcome.

    python -m data_generator.simulate --projects 300 --seed 2026

How a project is simulated
    Work is measured in "planned weeks": a project planned for W weeks needs W weeks of work at
    full efficiency. Each week the project advances by its *efficiency* (1.0 = on plan), and its
    progress percent follows the same S-curve as the plan. Efficiency is reduced by heavy rain,
    crew shortages and late material deliveries, and varies with a hidden site-management quality
    that the model never sees, only its symptoms (missed reports, late deliveries, crew levels).
    Cost follows progress, plus price drift, time-related overheads when the project runs late,
    expediting for late deliveries, rework and variations.

Nothing here comes from a real contractor yet: see ``ASSUMPTIONS.md`` for what to validate.
"""

from __future__ import annotations

import argparse
import csv
import math
import sys
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

import numpy as np

HERE = Path(__file__).parent
RAINFALL = HERE / "rainfall.csv"
DEFAULT_OUTPUT = HERE.parent / "data" / "snapshots.csv"

# --- Shared definitions (mirrored in backend/app/ai/risk/features.py) --------------------------------

PROJECT_TYPES = ("residential", "commercial", "mixed_use", "industrial", "institutional")
HEAVY_RAIN_MM = 10.0  # BR-06: heavy rain is 10 mm or more in a day
WORKING_DAYS = 6  # Monday to Saturday, the usual site week in Sri Lanka

# Rain (see ASSUMPTIONS.md). Share of a working day lost by the day's rain, highest band first.
RAIN_BANDS: tuple[tuple[float, float], ...] = ((25.0, 0.8), (HEAVY_RAIN_MM, 0.45), (2.0, 0.1))
RAIN_LINGER = 0.25  # share of the next day also lost after heavy rain (wet ground, dewatering, access)
# ASSUMPTION, NOT MEASURED: the share of the town's usual rain loss for the month that programmes
# allow for. Half means programmes under-allow for the monsoon, as Sri Lankan delay surveys suggest.
# Replace with contractor figures when available. The model card reports the results at 0.75 too.
RAIN_ALLOWANCE = 0.5
# Sensitivity by share of the work done, as (up to, factor): earthworks and substructure, the
# frame, closed in.
RAIN_STAGES: tuple[tuple[float, float], ...] = ((0.3, 1.2), (0.6, 1.0), (1.0, 0.4))
# Base pace of work against the programme, before rain, crew and materials (1.0 = exactly on plan).
# Calibrated (``--calibrate``) so the median project ends 10% of its planned duration late, as in
# risk model v1: the rain assumptions change what explains delay, not how late projects are.
BASE_PACE = 1.096
TARGET_MEDIAN_DELAY_PCT = 10.0

FEATURES = (
    "elapsed_pct",  # days since start / planned duration x 100 (over 100 once past the planned end)
    "planned_duration_days",
    "progress_gap_pct",  # actual minus planned progress, percentage points
    "progress_rate_trend",  # change in the progress gap per week over the last three weeks
    "late_deliveries_count",  # deliveries that arrived after, or are still overdue past, the expected date
    "avg_lateness_days",  # mean lateness of those deliveries
    "rain_days_next_14",  # forecast days with heavy rain in the next 14 days
    "wet_days_ahead",  # heavy-rain working days expected, from the local climate, until the planned end
    "budget_variance_pct",  # committed cost against the budgeted value of the same work, % over
    "crew_vs_plan_pct",  # average reported crew over the last 14 days against the planned crew, %
    "missing_reports_14",  # working days in the last 14 days without a daily report (BR-07)
    "issues_material_14",  # confirmed material-delay issues in reports of the last 14 days (Phase 7)
    "issues_safety_14",  # confirmed safety issues in the last 14 days
    "issues_design_14",  # confirmed design or drawing issues in the last 14 days
    "contract_value_m",  # LKR millions
    *(f"type_{t}" for t in PROJECT_TYPES),
)
TARGETS = ("delay_days", "overrun_pct")


def s_curve(fraction: float) -> float:
    """Planned share of work done at a share of planned time: a smooth S (slow start and finish)."""
    f = min(max(fraction, 0.0), 1.0)
    return f * f * (3.0 - 2.0 * f)


def risk_score(delay_days: float, overrun_pct: float, planned_duration_days: float) -> int:
    """0 to 100: the worse of schedule and cost. 25% late or 20% over budget scores 100.

    Mirrored in backend/app/ai/risk/scoring.py. BR-10 bands: 70+ High, 40 to 69 Medium.
    """
    delay_part = delay_days / (0.25 * planned_duration_days) if planned_duration_days > 0 else 0.0
    cost_part = overrun_pct / 20.0
    return round(100 * min(max(delay_part, cost_part, 0.0), 1.0))


# --- Weather --------------------------------------------------------------------------------------


def load_rainfall(path: Path = RAINFALL) -> dict[str, dict[date, float]]:
    series: dict[str, dict[date, float]] = {}
    with path.open(encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            series.setdefault(row["town"], {})[date.fromisoformat(row["date"])] = float(row["rain_mm"])
    return series


# --- One project ----------------------------------------------------------------------------------


@dataclass
class Delivery:
    expected: date
    arrives: date


@dataclass
class Project:
    id: int
    project_type: str
    town: str
    start: date
    contract_value_m: float
    planned_weeks: int
    planned_crew: int
    quality: float  # hidden site-management quality, 0 to 1
    supplier_reliability: float  # chance a delivery arrives on time
    price_drift: float  # material price change over the project, fraction
    deliveries: list[Delivery] = field(default_factory=list)


def draw_project(rng: np.random.Generator, project_id: int, towns: list[str], last_start: date) -> Project:
    kind = str(rng.choice(PROJECT_TYPES, p=[0.35, 0.25, 0.15, 0.15, 0.10]))
    value = float(np.clip(rng.lognormal(math.log(450), 0.8), 60, 4000))
    # Bigger jobs take longer, with diminishing returns; industrial sheds are quicker, institutions slower.
    type_factor = {"industrial": 0.85, "institutional": 1.1}.get(kind, 1.0)
    weeks = round((24 + 15 * math.log(value / 60 + 1)) * type_factor * rng.uniform(0.9, 1.1))
    first_start = date(2013, 1, 7)
    start = first_start + timedelta(days=int(rng.integers(0, (last_start - first_start).days)))
    start -= timedelta(days=start.weekday())  # projects start on a Monday
    quality = float(rng.beta(5, 2))  # most sites are run reasonably well; a tail is not
    return Project(
        id=project_id,
        project_type=kind,
        town=str(rng.choice(towns)),
        start=start,
        contract_value_m=round(value, 1),
        planned_weeks=weeks,
        planned_crew=int(np.clip(round(10 + value / 12), 8, 250)),
        quality=quality,
        supplier_reliability=float(np.clip(rng.beta(6, 2) * (0.75 + 0.35 * quality), 0.3, 0.98)),
        price_drift=float(rng.normal(0.02, 0.03)),
    )


@dataclass
class Week:
    on: date  # the snapshot date: end of the week (Sunday)
    features: dict[str, float]


def lost_day(mm: float, yesterday_mm: float = 0.0) -> float:
    """Share of a working day lost to its own rain, plus the lingering effect of heavy rain the day before."""
    own = next((share for floor, share in RAIN_BANDS if mm >= floor), 0.0)
    linger = RAIN_LINGER if yesterday_mm >= HEAVY_RAIN_MM else 0.0
    return min(own + linger, 1.0)


def rain_on(rain: dict[date, float], day: date) -> float:
    """A day's rain, and the day before's (for the lingering effect)."""
    return lost_day(rain.get(day, 0.0), rain.get(day - timedelta(days=1), 0.0))


def normal_lost_by_month(rain: dict[date, float]) -> dict[int, float]:
    """The town's average share of a day lost to rain, per calendar month (what a programme allows for)."""
    totals: dict[int, list[float]] = {}
    for day in rain:
        totals.setdefault(day.month, []).append(rain_on(rain, day))
    return {month: float(np.mean(values)) for month, values in totals.items()}


def stage_sensitivity(stage: float) -> float:
    return next((factor for upto, factor in RAIN_STAGES if stage < upto), RAIN_STAGES[-1][1])


def heavy_rain_climate(rain: dict[date, float]) -> dict[int, float]:
    """The town's share of days with heavy rain, per calendar month (its long-term climate).

    Rounded to 4 decimals: the backend scores with exactly these numbers (``rain_climate.json``).
    """
    days: dict[int, list[bool]] = {}
    for day, mm in rain.items():
        days.setdefault(day.month, []).append(mm >= HEAVY_RAIN_MM)
    return {month: round(float(np.mean(values)), 4) for month, values in sorted(days.items())}


def wet_days_ahead(climate: dict[int, float], today: date, planned_end: date) -> float:
    """Heavy-rain working days (Mon to Sat) expected from tomorrow to the planned end, from the climate.

    Never less than the next 28 days, so a project past its planned end still sees the season ahead.
    Mirrored in backend/app/ai/risk/features.py.
    """
    last = max(planned_end, today + timedelta(days=28))
    total = 0.0
    day = today + timedelta(days=1)
    while day <= last:
        if day.weekday() < WORKING_DAYS:
            total += climate[day.month]
        day += timedelta(days=1)
    return total


def simulate(
    project: Project,
    rain: dict[date, float],
    normal_lost: dict[int, float],
    climate: dict[int, float],
    rng: np.random.Generator,
) -> tuple[list[Week], dict[str, float]]:
    """Run one project to completion. Returns weekly feature snapshots and the final outcome."""
    W = float(project.planned_weeks)
    planned_days = project.planned_weeks * 7
    planned_end = project.start + timedelta(days=planned_days - 1)
    budget = project.contract_value_m * 0.82  # cost budget: contract value less margin and contingency
    overhead_per_week = 0.10 * budget / W  # time-related costs (site staff, cranes, hoarding), 10% of budget

    work = 0.0  # planned weeks of work done
    required = W  # grows with variations
    cost_extra = 0.0  # overheads past the plan, expediting, variations (LKR millions)
    expediting = 0.0  # the part of cost_extra paid on material orders (visible in the app's commitments)
    rework = 0.04 * (1 - project.quality) ** 1.5  # share of cost redone on poorly run sites
    crew_ratio = 1.0
    shortage_weeks = 0
    gap_history: list[float] = []
    daily_crew: list[float | None] = []  # one entry per working day; None = no report filed
    late_seen: dict[int, float] = {}  # delivery index -> lateness in days (delivered late or overdue)
    weeks: list[Week] = []
    finished_at: float | None = None
    week = 0
    report_miss = 0.02 + 0.30 * (1 - project.quality) ** 2
    design_heat = 0.0  # raised by a variation: RFIs and drawing changes follow it for a few weeks
    # Issue counts use their own random stream, so adding them (Phase 7) left every simulated project,
    # and its outcome, exactly as in risk model v1.0: only the new inputs differ.
    issue_rng = np.random.default_rng(10_000 + project.id)
    issue_history: list[tuple[int, int, int]] = []  # (material, safety, design) issues per week

    while finished_at is None and week < 3 * W:
        week_start = project.start + timedelta(weeks=week)
        stage = work / required

        # Deliveries for this week's work, on the expected date or late.
        if 0.05 < stage < 0.92:
            for _ in range(rng.poisson(0.6 + project.contract_value_m / 800)):
                expected = week_start + timedelta(days=int(rng.integers(0, 6)))
                late = 0
                if rng.random() > project.supplier_reliability:
                    late = 1 + round(rng.gamma(2.0, 3.0) * (1.5 - project.quality))
                project.deliveries.append(Delivery(expected, expected + timedelta(days=late)))

        # Rain: heavy days lose most of a day's work, wet days a little. Programmes allow for part of the
        # usual weather of the town and month (RAIN_ALLOWANCE), so rain beyond that slows the job (and a
        # dry spell helps). The effect depends on the stage: less once the building is closed in.
        lost = sum(rain_on(rain, week_start + timedelta(days=d)) for d in range(WORKING_DAYS))
        excess = lost - WORKING_DAYS * RAIN_ALLOWANCE * normal_lost[week_start.month]
        rain_factor = 1 - (excess / WORKING_DAYS) * stage_sensitivity(stage)

        # Crew: drifts around a level set by management quality, with occasional shortages.
        if shortage_weeks == 0 and rng.random() < 0.04 + 0.04 * (1 - project.quality):
            shortage_weeks = int(rng.integers(2, 7))
        target = (1.0 - 0.15 * (1 - project.quality)) * (rng.uniform(0.6, 0.8) if shortage_weeks else 1.0)
        crew_ratio = 0.6 * crew_ratio + 0.4 * target + rng.normal(0, 0.03)
        shortage_weeks = max(shortage_weeks - 1, 0)
        crew_factor = min(max(crew_ratio, 0.2), 1.1) ** 0.7

        # Materials: each delivery still overdue this week holds some work up.
        week_end = week_start + timedelta(days=6)
        overdue = sum(1 for d in project.deliveries if d.expected <= week_end and d.arrives > week_end)
        material_factor = 1 - min(0.04 * overdue, 0.4)

        base = rng.normal(BASE_PACE + 0.12 * (project.quality - 0.7), 0.03)
        efficiency = max(base * rain_factor * crew_factor * material_factor + rng.normal(0, 0.04), 0.05)

        # Variations: extra scope (work and cost) the original plan never had.
        if rng.random() < 0.012:
            extra = rng.uniform(0.02, 0.08)
            required += extra * W
            cost_extra += extra * budget
            design_heat += 1.5

        before = work
        work += efficiency
        if week + 1 > W:
            cost_extra += overhead_per_week  # every week past the planned end costs overheads
        if work >= required:
            finished_at = week + (required - before) / efficiency

        # Expediting and standing time for deliveries that turned up late this week.
        for i, d in enumerate(project.deliveries):
            lateness = (min(d.arrives, week_end) - d.expected).days
            if d.expected <= week_end and lateness > 0:
                if week_start <= d.arrives <= week_end:
                    charge = 0.0002 * budget * (d.arrives - d.expected).days / 7
                    cost_extra += charge
                    expediting += charge
                late_seen[i] = float(max(late_seen.get(i, 0.0), lateness))

        # What the app would have recorded this week.
        filed_days = 0
        for _ in range(WORKING_DAYS):
            filed = rng.random() > report_miss
            daily_crew.append(project.planned_crew * crew_ratio * rng.normal(1, 0.08) if filed else None)
            filed_days += filed
        # Issues the engineers tag and confirm in their reports (only in reports that were filed):
        # material delays follow overdue deliveries, safety issues follow poor site management, and
        # design issues follow variations.
        filed_share = filed_days / WORKING_DAYS
        issue_history.append(
            (
                int(issue_rng.poisson((0.1 + 0.5 * overdue) * filed_share)),
                int(issue_rng.poisson((0.05 + 0.6 * (1 - project.quality) ** 2) * filed_share)),
                int(issue_rng.poisson((0.08 + design_heat) * filed_share)),
            )
        )
        design_heat *= 0.6
        recent_issues = issue_history[-2:]

        done_fraction = min(work / required, 1.0)
        snapshot = week_start + timedelta(days=6)
        elapsed_days = (snapshot - project.start).days + 1
        planned_pct = 100 * s_curve(elapsed_days / planned_days)
        actual_pct = 100 * s_curve(done_fraction) + rng.normal(0, 1.0)  # reported progress is approximate
        actual_pct = min(max(actual_pct, 0.0), 100.0)
        gap = actual_pct - planned_pct
        gap_history.append(gap)
        span = min(3, len(gap_history) - 1)
        trend = (gap - gap_history[-1 - span]) / span if span else 0.0

        # Cost variance the app can see: what has been committed on material orders against the
        # budgeted value of the same quantities. Price drift, rework and expediting show up here;
        # time-related overheads do not (the app does not track site overheads yet).
        cost_index = 1 + project.price_drift * done_fraction
        committed_work = budget * done_fraction
        if committed_work > 0.02 * budget:
            variance_pct = ((cost_index * (1 + rework) - 1) + expediting / committed_work) * 100
            variance_pct += rng.normal(0, 1.5)
        else:
            variance_pct = 0.0  # too little committed yet to say

        last_12 = daily_crew[-12:]
        reported = [c for c in last_12 if c is not None]
        crew_pct = (np.mean(reported) / project.planned_crew - 1) * 100 if reported else 0.0

        forecast = 0
        for d in range(1, 15):
            heavy = rain.get(snapshot + timedelta(days=d), 0.0) >= HEAVY_RAIN_MM
            if rng.random() < 0.15:  # a 14-day forecast is often wrong
                heavy = not heavy
            forecast += int(heavy)

        lateness = list(late_seen.values())
        features = {
            "elapsed_pct": 100 * elapsed_days / planned_days,
            "planned_duration_days": float(planned_days),
            "progress_gap_pct": gap,
            "progress_rate_trend": trend,
            "late_deliveries_count": float(len(lateness)),
            "avg_lateness_days": float(np.mean(lateness)) if lateness else 0.0,
            "rain_days_next_14": float(forecast),
            "wet_days_ahead": wet_days_ahead(climate, snapshot, planned_end),
            "budget_variance_pct": variance_pct,
            "crew_vs_plan_pct": float(crew_pct),
            "missing_reports_14": float(sum(1 for c in last_12 if c is None)),
            "issues_material_14": float(sum(w[0] for w in recent_issues)),
            "issues_safety_14": float(sum(w[1] for w in recent_issues)),
            "issues_design_14": float(sum(w[2] for w in recent_issues)),
            "contract_value_m": project.contract_value_m,
            **{f"type_{t}": float(project.project_type == t) for t in PROJECT_TYPES},
        }
        if finished_at is None and week >= 1:  # a snapshot for every week the project is still running
            weeks.append(Week(snapshot, features))
        week += 1

    if finished_at is None:  # stopped at three times the plan: treat as finishing now
        finished_at = float(week)
    delay_days = (finished_at - W) * 7
    final_cost = budget * (1 + project.price_drift) * (1 + rework) + cost_extra
    overrun_pct = (final_cost - budget) / budget * 100
    outcome = {"delay_days": round(delay_days, 1), "overrun_pct": round(overrun_pct, 2)}
    return weeks, outcome


# --- All projects ---------------------------------------------------------------------------------


def generate(n_projects: int, seed: int, rainfall: dict[str, dict[date, float]]) -> list[dict[str, object]]:
    rng = np.random.default_rng(seed)
    towns = sorted(rainfall)
    normals = {town: normal_lost_by_month(series) for town, series in rainfall.items()}
    climates = {town: heavy_rain_climate(series) for town, series in rainfall.items()}
    last_rain_day = min(max(days) for days in rainfall.values())
    rows: list[dict[str, object]] = []
    for project_id in range(1, n_projects + 1):
        # Leave room for the plan and a long overrun inside the rainfall history.
        project = draw_project(rng, project_id, towns, last_rain_day - timedelta(days=4 * 365))
        town = project.town
        weeks, outcome = simulate(project, rainfall[town], normals[town], climates[town], rng)
        score = risk_score(outcome["delay_days"], outcome["overrun_pct"], project.planned_weeks * 7)
        for w in weeks:
            rows.append(
                {
                    "project_id": project.id,
                    "snapshot_date": w.on.isoformat(),
                    "town": project.town,
                    "project_type": project.project_type,
                    **{k: round(v, 4) for k, v in w.features.items()},
                    **outcome,
                    "final_score": score,
                    "quality": round(project.quality, 3),  # hidden: for analysis only, never a feature
                }
            )
    return rows


def median_delay_pct(rows: list[dict[str, object]]) -> float:
    """Median final delay as % of the planned duration, one value per project."""
    finals = {r["project_id"]: r for r in rows}.values()
    return float(
        np.median([100 * float(r["delay_days"]) / float(r["planned_duration_days"]) for r in finals])
    )


def calibrate_pace(n_projects: int, seed: int, rainfall: dict[str, dict[date, float]]) -> float:
    """The BASE_PACE giving a median delay of TARGET_MEDIAN_DELAY_PCT, found by bisection, to 3 decimals."""
    global BASE_PACE
    saved = BASE_PACE
    low, high = 0.9, 1.3
    try:
        while high - low > 0.0005:
            BASE_PACE = (low + high) / 2
            if median_delay_pct(generate(n_projects, seed, rainfall)) > TARGET_MEDIAN_DELAY_PCT:
                low = BASE_PACE  # still too late: work faster
            else:
                high = BASE_PACE
        return round((low + high) / 2, 3)
    finally:
        BASE_PACE = saved


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--projects", type=int, default=300)
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--calibrate", action="store_true", help="print the BASE_PACE for the target delay")
    args = parser.parse_args(argv)

    if args.calibrate:
        pace = calibrate_pace(args.projects, args.seed, load_rainfall())
        print(
            f"BASE_PACE = {pace} gives a median delay of {TARGET_MEDIAN_DELAY_PCT}% of the planned duration"
        )
        return 0

    rows = generate(args.projects, args.seed, load_rainfall())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    projects = {r["project_id"] for r in rows}
    print(f"Wrote {len(rows)} weekly snapshots for {len(projects)} projects to {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
