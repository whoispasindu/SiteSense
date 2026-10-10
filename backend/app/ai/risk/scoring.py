"""From model outputs to what people see: the 0 to 100 score, the BR-10 band, and the drivers.

Pure functions (no database), mirrored in ``ml/data_generator/simulate.py`` where the training
labels are made, so the score means the same thing in training and in the app.

Score
    The worse of schedule and cost: 25% of the planned duration late, or 20% over budget, scores
    100. So a project forecast 10% late scores 40 (Medium), and one 17.5% late or 14% over budget
    scores 70 (High).

BR-10 bands
    70 or more is High (and alerts the project manager), 40 to 69 Medium, under 40 Low.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Level = Literal["low", "medium", "high"]
HIGH = 70
MEDIUM = 40
FULL_DELAY_SHARE = 0.25  # 25% late scores 100
FULL_OVERRUN_PCT = 20.0  # 20% over budget scores 100


def risk_score(delay_days: float, overrun_pct: float, planned_duration_days: float) -> int:
    delay_part = delay_days / (FULL_DELAY_SHARE * planned_duration_days) if planned_duration_days > 0 else 0.0
    cost_part = overrun_pct / FULL_OVERRUN_PCT
    return round(100 * min(max(delay_part, cost_part, 0.0), 1.0))


def level(score: int) -> Level:
    """BR-10."""
    if score >= HIGH:
        return "high"
    if score >= MEDIUM:
        return "medium"
    return "low"


# --- Drivers ---------------------------------------------------------------------------------------

# Signals are things the site can act on; context (size, type, how far along) explains the
# baseline but is not something to fix.
_LABELS: dict[str, tuple[str, str]] = {
    "progress_gap_pct": ("Progress against plan", "signal"),
    "progress_rate_trend": ("Progress trend", "signal"),
    "late_deliveries_count": ("Late deliveries", "signal"),
    "avg_lateness_days": ("Delivery lateness", "signal"),
    "rain_days_next_14": ("Heavy rain forecast", "signal"),
    "budget_variance_pct": ("Committed cost against budget", "signal"),
    "crew_vs_plan_pct": ("Crew against plan", "signal"),
    "missing_reports_14": ("Missing daily reports", "signal"),
    "elapsed_pct": ("Time elapsed", "context"),
    "planned_duration_days": ("Planned duration", "context"),
    "contract_value_m": ("Contract size", "context"),
    "project_type": ("Project type", "context"),
}


def _plural(n: float, word: str) -> str:
    count = round(n)
    return f"{count} {word}" if count == 1 else f"{count} {word}s"


def describe(feature: str, values: dict[str, float]) -> str:
    """The feature's value in words, as a site team would say it."""
    v = values.get(feature, 0.0)
    if feature == "progress_gap_pct":
        if abs(v) < 0.5:
            return "on plan"
        return f"{abs(v):.1f} points {'behind' if v < 0 else 'ahead'}"
    if feature == "progress_rate_trend":
        if abs(v) < 0.1:
            return "steady"
        return f"{'falling' if v < 0 else 'gaining'} {abs(v):.1f} points a week"
    if feature == "late_deliveries_count":
        return _plural(v, "order line") + " late"
    if feature == "avg_lateness_days":
        return f"{v:.1f} days on average" if v else "none late"
    if feature == "rain_days_next_14":
        return _plural(v, "day") + " in the next 14"
    if feature == "budget_variance_pct":
        return f"{v:+.1f}%"
    if feature == "crew_vs_plan_pct":
        return f"{v:+.0f}% over the last 14 days"
    if feature == "missing_reports_14":
        return _plural(v, "day") + " in the last 14"
    if feature == "elapsed_pct":
        return f"{v:.0f}% of the planned duration"
    if feature == "planned_duration_days":
        return f"{v / 7:.0f} weeks"
    if feature == "contract_value_m":
        return f"LKR {v:,.0f} M"
    if feature == "project_type":
        kind = next((k.removeprefix("type_") for k, x in values.items() if k.startswith("type_") and x), "")
        return kind.replace("_", " ")
    return f"{v:g}"


@dataclass(frozen=True, slots=True)
class Driver:
    feature: str
    label: str
    kind: str
    value: str
    delay_days: float  # how much this factor moved the delay forecast
    overrun_pct: float  # and the overrun forecast

    def as_dict(self) -> dict[str, object]:
        return {
            "feature": self.feature,
            "label": self.label,
            "kind": self.kind,
            "value": self.value,
            "delay_days": round(self.delay_days, 1),
            "overrun_pct": round(self.overrun_pct, 2),
        }


def drivers(
    features: tuple[str, ...],
    values: dict[str, float],
    delay_contributions: tuple[float, ...],
    overrun_contributions: tuple[float, ...],
    *,
    planned_duration_days: float,
    limit: int = 6,
) -> list[Driver]:
    """The factors that moved the forecast most, largest first, on the score's scale.

    Delay and overrun effects are compared in score points (the same scales as ``risk_score``), so
    a factor that adds 10 days to a 100-day job ranks above one that adds 10 days to a 2-year job.
    The project-type columns are combined into one "Project type" factor.
    """
    combined: dict[str, list[float]] = {}
    for name, d, o in zip(features, delay_contributions, overrun_contributions, strict=True):
        key = "project_type" if name.startswith("type_") else name
        entry = combined.setdefault(key, [0.0, 0.0])
        entry[0] += d
        entry[1] += o
    delay_points = 100 / (FULL_DELAY_SHARE * planned_duration_days) if planned_duration_days > 0 else 0.0
    cost_points = 100 / FULL_OVERRUN_PCT

    def weight(item: tuple[str, list[float]]) -> float:
        d, o = item[1]
        return max(abs(d) * delay_points, abs(o) * cost_points)

    ranked = sorted(combined.items(), key=weight, reverse=True)
    out = []
    for name, (d, o) in ranked[:limit]:
        if max(abs(d) * delay_points, abs(o) * cost_points) < 0.5:  # under half a point: not worth showing
            break
        label, kind = _LABELS.get(name, (name, "context"))
        out.append(Driver(name, label, kind, describe(name, values), d, o))
    return out
