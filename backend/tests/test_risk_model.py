"""Risk model v1: the JSON scorer, its validation, and the score, band and driver rules (no database)."""

import copy
import json
import math
from pathlib import Path
from typing import Any

import pytest

from app.ai.risk import model, scoring
from app.ai.risk.features import FEATURE_NAMES

GAP = FEATURE_NAMES.index("progress_gap_pct")


def doc(delay_trees: list[Any] | None = None, overrun_trees: list[Any] | None = None) -> dict[str, Any]:
    """A tiny valid model document: by default a constant 10 days and 2%."""
    return {
        "format": "sitesense-gbdt-v1",
        "version": "0.0.1",
        "features": list(FEATURE_NAMES),
        "targets": {
            "delay_days": {"trees": delay_trees or [[[-1, 0, -1, -1, 10.0]]]},
            "overrun_pct": {"trees": overrun_trees or [[[-1, 0, -1, -1, 2.0]]]},
        },
    }


def vector(**values: float) -> tuple[float, ...]:
    return tuple(values.get(name, 0.0) for name in FEATURE_NAMES)


# --- The shipped model ------------------------------------------------------------------------------


def test_shipped_model_reproduces_lightgbm_exactly() -> None:
    """The golden rows hold LightGBM's own predictions from training: the JSON scorer must agree."""
    shipped = model.current()

    assert len(shipped.golden) >= 20
    for row in shipped.golden:
        delay, overrun = shipped.predict(tuple(row["x"]))
        assert delay.value == pytest.approx(row["delay_days"], abs=1e-9)
        assert overrun.value == pytest.approx(row["overrun_pct"], abs=1e-9)


def test_contributions_add_up_to_the_prediction() -> None:
    shipped = model.current()
    for row in shipped.golden:
        for prediction in shipped.predict(tuple(row["x"])):
            assert len(prediction.contributions) == len(FEATURE_NAMES)
            assert prediction.base + sum(prediction.contributions) == pytest.approx(
                prediction.value, abs=1e-9
            )


def test_shipped_model_uses_the_feature_builders_features_in_order() -> None:
    shipped = model.current()

    assert shipped.features == FEATURE_NAMES
    assert shipped.version == model.CURRENT_VERSION
    assert "synthetic" in shipped.training["data"]


def test_falling_behind_never_lowers_the_delay_forecast() -> None:
    """Trained with a monotone constraint: more behind plan can only mean more delay."""
    shipped = model.current()
    base = list(shipped.golden[0]["x"])
    previous = math.inf
    for gap in (-30, -20, -10, -5, 0, 5, 10):
        base[GAP] = gap
        delay, _ = shipped.predict(tuple(base))
        assert delay.value <= previous + 1e-9
        previous = delay.value


# --- Scoring a document -----------------------------------------------------------------------------


def test_trees_go_left_at_or_below_the_threshold() -> None:
    split = [[GAP, -5.0, 1, 2, 20.0], [-1, 0, -1, -1, 40.0], [-1, 0, -1, -1, 5.0]]
    m = model.parse(doc(delay_trees=[split]))

    assert m.predict(vector(progress_gap_pct=-5.0))[0].value == 40.0  # exactly the threshold: left
    assert m.predict(vector(progress_gap_pct=-4.99))[0].value == 5.0
    delay, _ = m.predict(vector(progress_gap_pct=-12))
    assert delay.base == 20.0
    assert delay.contributions[GAP] == 20.0  # the split moved the forecast from 20 to 40


def test_predict_refuses_bad_vectors() -> None:
    m = model.parse(doc())

    with pytest.raises(model.ModelError, match="Expected"):
        m.predict((1.0, 2.0))
    with pytest.raises(model.ModelError, match="finite"):
        m.predict(vector(progress_gap_pct=math.nan))
    with pytest.raises(model.ModelError, match="finite"):
        m.predict(vector(elapsed_pct=math.inf))


def _broken(change: str) -> dict[str, Any]:
    d = doc()
    split = [[GAP, 0.0, 1, 2, 1.0], [-1, 0, -1, -1, 2.0], [-1, 0, -1, -1, 0.0]]
    d["targets"]["delay_days"]["trees"] = [copy.deepcopy(split)]
    tree = d["targets"]["delay_days"]["trees"][0]
    if change == "format":
        d["format"] = "pickle"
    elif change == "no features":
        d["features"] = []
    elif change == "missing target":
        del d["targets"]["overrun_pct"]
    elif change == "extra target":
        d["targets"]["anything"] = d["targets"]["delay_days"]
    elif change == "empty trees":
        d["targets"]["delay_days"]["trees"] = []
    elif change == "unknown feature":
        tree[0][0] = len(FEATURE_NAMES)
    elif change == "child before parent":  # would let a walk loop forever
        tree[1] = [GAP, 0.0, 0, 2, 1.0]
    elif change == "child out of range":
        tree[0][3] = 9
    elif change == "short node":
        tree[1] = [-1, 0, 2.0]
    elif change == "text in node":
        tree[1] = [-1, 0, -1, -1, "2.0"]
    elif change == "boolean in node":
        tree[1] = [-1, 0, -1, -1, True]
    elif change == "infinite value":
        tree[1] = [-1, 0, -1, -1, math.inf]
    elif change == "too many trees":
        d["targets"]["delay_days"]["trees"] = [[[-1, 0, -1, -1, 0.0]]] * (model.MAX_TREES + 1)
    return d


@pytest.mark.parametrize(
    "change",
    [
        "format", "no features", "missing target", "extra target", "empty trees", "unknown feature",
        "child before parent", "child out of range", "short node", "text in node", "boolean in node",
        "infinite value", "too many trees",
    ],
)  # fmt: skip
def test_malformed_model_files_are_refused(change: str) -> None:
    with pytest.raises(model.ModelError):
        model.parse(_broken(change))


def test_unreadable_model_files_are_refused(tmp_path: Path) -> None:
    bad = tmp_path / "risk.json"
    bad.write_text("{not json", encoding="utf-8")

    with pytest.raises(model.ModelError, match="Cannot read"):
        model.load(bad)
    with pytest.raises(model.ModelError, match="Cannot read"):
        model.load(tmp_path / "missing.json")


def test_a_valid_file_loads(tmp_path: Path) -> None:
    good = tmp_path / "risk.json"
    good.write_text(json.dumps(doc()), encoding="utf-8")

    loaded = model.load(good)

    assert loaded.predict(vector())[0].value == 10.0
    assert loaded.version == "0.0.1"


# --- Score, bands and drivers -------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("delay", "overrun", "planned", "expected"),
    [
        (0, 0, 400, 0),
        (-30, -5, 400, 0),  # early and under budget: never below zero
        (40, 0, 400, 40),  # 10% late
        (70, 0, 400, 70),  # 17.5% late: High
        (100, 0, 400, 100),  # 25% late
        (300, 0, 400, 100),  # capped
        (0, 8, 400, 40),  # 8% over budget
        (0, 14, 400, 70),
        (20, 14, 400, 70),  # the worse of the two counts
        (10, 0, 0, 0),  # no planned duration: delay cannot be scaled
    ],
)
def test_risk_score(delay: float, overrun: float, planned: float, expected: int) -> None:
    assert scoring.risk_score(delay, overrun, planned) == expected


@pytest.mark.parametrize(
    ("score", "level"), [(0, "low"), (39, "low"), (40, "medium"), (69, "medium"), (70, "high"), (100, "high")]
)
def test_br10_bands(score: int, level: str) -> None:
    assert scoring.level(score) == level


def test_drivers_rank_by_score_points_and_merge_project_type() -> None:
    signals = {"progress_gap_pct": -8.0, "late_deliveries_count": 3.0, "rain_days_next_14": 2.0}
    values = dict.fromkeys(FEATURE_NAMES, 0.0) | signals | {"type_commercial": 1.0}
    delay = dict.fromkeys(FEATURE_NAMES, 0.0) | {"progress_gap_pct": 30.0, "rain_days_next_14": 0.1}
    overrun = dict.fromkeys(FEATURE_NAMES, 0.0) | {
        "late_deliveries_count": 3.0,
        "type_commercial": 0.6,
        "type_industrial": 0.6,
    }

    out = scoring.drivers(
        FEATURE_NAMES, values, tuple(delay.values()), tuple(overrun.values()), planned_duration_days=400
    )

    # 30 days on a 400-day job is 30 points; 3% overrun is 15 points; type 1.2% is 6 points.
    assert [d.feature for d in out] == ["progress_gap_pct", "late_deliveries_count", "project_type"]
    assert out[0].label == "Progress against plan"
    assert out[0].value == "8.0 points behind"
    assert out[0].kind == "signal"
    assert out[2].value == "commercial"
    assert out[2].kind == "context"
    assert out[2].overrun_pct == pytest.approx(1.2)
    assert all(d.feature != "rain_days_next_14" for d in out)  # under half a point: not shown


def test_drivers_are_limited() -> None:
    contributions = tuple(5.0 for _ in FEATURE_NAMES)

    out = scoring.drivers(
        FEATURE_NAMES,
        dict.fromkeys(FEATURE_NAMES, 1.0),
        contributions,
        contributions,
        planned_duration_days=100,
    )

    assert len(out) == 6


@pytest.mark.parametrize(
    ("feature", "value", "text"),
    [
        ("progress_gap_pct", -4.0, "4.0 points behind"),
        ("progress_gap_pct", 2.5, "2.5 points ahead"),
        ("progress_gap_pct", 0.2, "on plan"),
        ("progress_rate_trend", -0.6, "falling 0.6 points a week"),
        ("progress_rate_trend", 0.05, "steady"),
        ("late_deliveries_count", 1, "1 order line late"),
        ("late_deliveries_count", 2, "2 order lines late"),
        ("avg_lateness_days", 6.5, "6.5 days on average"),
        ("avg_lateness_days", 0, "none late"),
        ("rain_days_next_14", 6, "6 days in the next 14"),
        ("budget_variance_pct", 3.1, "+3.1%"),
        ("crew_vs_plan_pct", -12, "-12% over the last 14 days"),
        ("missing_reports_14", 1, "1 day in the last 14"),
        ("issues_safety_14", 2, "2 issues in the last 14 days"),
        ("issues_design_14", 1, "1 issue in the last 14 days"),
        ("elapsed_pct", 48.2, "48% of the planned duration"),
        ("planned_duration_days", 364, "52 weeks"),
        ("contract_value_m", 380, "LKR 380 M"),
    ],
)
def test_drivers_describe_values_in_words(feature: str, value: float, text: str) -> None:
    assert scoring.describe(feature, {feature: value}) == text
