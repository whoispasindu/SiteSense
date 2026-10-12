"""The what-if planner's recovery actions (Phase 10): what each one changes in the model's inputs.

The risk model predicts; it does not know causes. So the planner offers only actions that move
inputs which really slow work in the simulation the model learnt from (crew, late materials, rain),
and every one of those inputs has a fixed direction in the model (monotone constraints), so no action
can make a forecast worse. Symptoms such as missed reports are offered as plain advice instead: the
model would show a fake improvement if they were "fixed".

Each action has a planned change (the project owner's figures). Real actions rarely deliver all of
it, so an action's effect is given as a range: from half its planned change to all of it.

Pure functions over the feature values; no database.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass

CREW_CAP = 10.0  # a site can stretch its crew to at most 10% over plan
HALF, FULL = 0.5, 1.0  # the two ends of an action's effect


def _crew(points: float) -> Callable[[dict[str, float], float], None]:
    def apply(values: dict[str, float], strength: float) -> None:
        current = values["crew_vs_plan_pct"]
        values["crew_vs_plan_pct"] = max(current, min(current + points * strength, CREW_CAP))

    return apply


def _expedite(values: dict[str, float], strength: float) -> None:
    keep = 1 - 0.5 * strength  # halves late deliveries and lateness at full strength
    values["late_deliveries_count"] *= keep
    values["avg_lateness_days"] *= keep


def _protect(values: dict[str, float], strength: float) -> None:
    values["wet_days_ahead"] *= 1 - 0.3 * strength
    values["rain_days_next_14"] *= 1 - 0.5 * strength


@dataclass(frozen=True, slots=True)
class Action:
    id: str
    label: str
    description: str
    inputs: tuple[str, ...]  # the model inputs it changes
    apply: Callable[[dict[str, float], float], None]


CATALOGUE: tuple[Action, ...] = (
    Action(
        "add_crew",
        "Add a crew",
        "Bring in another gang: crew against plan up 20 points, to at most 10% over plan.",
        ("crew_vs_plan_pct",),
        _crew(20.0),
    ),
    Action(
        "work_sundays",
        "Work Sundays",
        "Work a seventh day: crew against plan up 15 points, to at most 10% over plan.",
        ("crew_vs_plan_pct",),
        _crew(15.0),
    ),
    Action(
        "expedite_materials",
        "Expedite late materials",
        "Chase or switch suppliers for overdue orders: late deliveries and their lateness halved.",
        ("late_deliveries_count", "avg_lateness_days"),
        _expedite,
    ),
    Action(
        "weather_protection",
        "Weather protection",
        "Covers, dewatering and wet-weather sequencing: the wet season ahead counts 30% less, the "
        "heavy-rain forecast 50% less.",
        ("wet_days_ahead", "rain_days_next_14"),
        _protect,
    ),
)
BY_ID: dict[str, Action] = {a.id: a for a in CATALOGUE}


def applied(values: Mapping[str, float], action_ids: list[str], strength: float) -> dict[str, float]:
    """The feature values after the actions, each delivering ``strength`` (0.5 to 1) of its change."""
    out = dict(values)
    for action_id in action_ids:
        BY_ID[action_id].apply(out, strength)
    return out


@dataclass(frozen=True, slots=True)
class Advice:
    id: str
    label: str
    text: str


def advice(values: Mapping[str, float]) -> list[Advice]:
    """Management actions worth taking, shown as advice only: they change no forecast here."""
    out = []
    missing = round(values.get("missing_reports_14", 0.0))
    if missing:
        out.append(
            Advice(
                "file_reports",
                "File every daily report",
                f"{missing} working {'day' if missing == 1 else 'days'} in the last 14 had no report. "
                "Reports keep the forecast and "
                "the record honest. The model reads missing reports as a sign of how a site is run, "
                "not as a cause, so filing them changes no forecast here.",
            )
        )
    issues = round(
        sum(values.get(k, 0.0) for k in ("issues_material_14", "issues_safety_14", "issues_design_14"))
    )
    if issues:
        out.append(
            Advice(
                "follow_up_issues",
                "Follow up open issues",
                f"{issues} {'issue was' if issues == 1 else 'issues were'} confirmed in the last 14 days. "
                "Close them out with the people "
                "responsible. Like missed reports, the model reads them as symptoms, so this changes no "
                "forecast here.",
            )
        )
    return out


def describe_change(action: Action, before: Mapping[str, float], after: Mapping[str, float]) -> str:
    """What the action does to its inputs, in words, at full strength."""
    parts = []
    for name in action.inputs:
        a, b = before.get(name, 0.0), after.get(name, 0.0)
        if name == "crew_vs_plan_pct":
            parts.append(f"crew {a:+.0f}% to {b:+.0f}% against plan")
        elif name == "late_deliveries_count":
            parts.append(f"late order lines {a:.0f} to {b:.1f}")
        elif name == "avg_lateness_days":
            parts.append(f"lateness {a:.1f} to {b:.1f} days")
        elif name == "wet_days_ahead":
            parts.append(f"wet days ahead {a:.0f} to {b:.0f}")
        elif name == "rain_days_next_14":
            parts.append(f"heavy-rain days forecast {a:.0f} to {b:.1f}")
    unchanged = all(abs(before.get(n, 0.0) - after.get(n, 0.0)) < 1e-9 for n in action.inputs)
    return "nothing to change: " + ", ".join(parts) if unchanged else ", ".join(parts)
