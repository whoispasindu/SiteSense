"""Risk model v2: the JSON scorer (trees, lines, likely ranges, SHAP), its validation, and the score,
band and driver rules (no database)."""

import copy
import itertools
import json
import math
from pathlib import Path
from typing import Any

import pytest

from app.ai.risk import model, scoring
from app.ai.risk.features import FEATURE_NAMES

GAP = FEATURE_NAMES.index("progress_gap_pct")
ELAPSED = FEATURE_NAMES.index("elapsed_pct")
PLANNED = FEATURE_NAMES.index("planned_duration_days")
N = len(FEATURE_NAMES)
NO_RANGE = {
    "features": list(model.RANGE_FEATURES),
    "p10": {"intercept": 0, "coef": [0, 0]},
    "p90": {"intercept": 0, "coef": [0, 0]},
}


def leaf(value: float, count: float = 10) -> list[float]:
    return [-1, 0, -1, -1, value, count]


def trees_target(*trees: list[list[float]], span: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"kind": "trees", "point": {"trees": list(trees)}, "range": span or copy.deepcopy(NO_RANGE)}


def line_target(intercept: float, coef: list[float], mean: list[float] | None = None) -> dict[str, Any]:
    point = {"intercept": intercept, "coef": coef, "mean": mean or [0.0] * N}
    return {"kind": "linear", "point": point, "range": copy.deepcopy(NO_RANGE)}


def doc(delay: dict[str, Any] | None = None, overrun: dict[str, Any] | None = None) -> dict[str, Any]:
    """A tiny valid model document: by default a constant 10 days and 2%, with no range width."""
    return {
        "format": "sitesense-risk-v2",
        "version": "0.0.1",
        "features": list(FEATURE_NAMES),
        "targets": {
            "delay_days": delay or trees_target([leaf(10.0)]),
            "overrun_pct": overrun or trees_target([leaf(2.0)]),
        },
    }


def vector(**values: float) -> tuple[float, ...]:
    return tuple(values.get(name, 0.0) for name in FEATURE_NAMES)


# --- The shipped model ------------------------------------------------------------------------------


def test_shipped_model_reproduces_lightgbm_exactly() -> None:
    """Golden rows hold the training code's own outputs: forecasts, ranges, SHAP values and base."""
    shipped = model.current()

    assert len(shipped.golden) >= 20
    for row in shipped.golden:
        for prediction, name in zip(
            shipped.predict(tuple(row["x"])), ("delay_days", "overrun_pct"), strict=True
        ):
            expected = row[name]
            assert prediction.value == pytest.approx(expected["point"], abs=1e-9)
            assert prediction.low == pytest.approx(
                min(expected["p10"], expected["point"], expected["p90"]), abs=1e-9
            )
            assert prediction.high == pytest.approx(
                max(expected["p10"], expected["point"], expected["p90"]), abs=1e-9
            )
            assert prediction.base == pytest.approx(expected["base"], abs=1e-9)
            assert prediction.contributions == pytest.approx(expected["contributions"], abs=1e-9)


def test_contributions_add_up_and_the_range_holds_the_forecast() -> None:
    shipped = model.current()
    for row in shipped.golden:
        for prediction in shipped.predict(tuple(row["x"])):
            assert len(prediction.contributions) == N
            assert prediction.base + sum(prediction.contributions) == pytest.approx(
                prediction.value, abs=1e-9
            )
            assert prediction.low <= prediction.value <= prediction.high


def test_shipped_model_uses_the_feature_builders_features_in_order() -> None:
    shipped = model.current()

    assert shipped.features == FEATURE_NAMES
    assert shipped.version == model.CURRENT_VERSION
    assert "synthetic" in shipped.training["data"]


def test_falling_behind_never_lowers_the_forecast_or_its_range() -> None:
    """Monotone constraints, and range offsets that do not depend on the gap."""
    shipped = model.current()
    base = list(shipped.golden[0]["x"])
    previous = (math.inf, math.inf, math.inf)
    for gap in (-30, -20, -10, -5, 0, 5, 10):
        base[GAP] = gap
        delay, _ = shipped.predict(tuple(base))
        assert (delay.value, delay.low, delay.high) <= tuple(p + 1e-9 for p in previous)
        previous = (delay.value, delay.low, delay.high)


def test_ranges_are_wider_with_more_of_the_programme_to_run() -> None:
    shipped = model.current()
    early = list(shipped.golden[0]["x"])
    late = list(early)
    early[ELAPSED], late[ELAPSED] = 10.0, 90.0

    (d_early, _), (d_late, _) = shipped.predict(tuple(early)), shipped.predict(tuple(late))

    assert d_early.high - d_early.low > d_late.high - d_late.low


# --- Scoring a document -----------------------------------------------------------------------------


def test_trees_go_left_at_or_below_the_threshold() -> None:
    split = [[GAP, -5.0, 1, 2, 20.0, 20], leaf(40.0, 10), leaf(0.0, 10)]
    m = model.parse(doc(delay=trees_target(split)))

    assert m.predict(vector(progress_gap_pct=-5.0))[0].value == 40.0  # exactly the threshold: left
    assert m.predict(vector(progress_gap_pct=-4.99))[0].value == 0.0
    delay, _ = m.predict(vector(progress_gap_pct=-12))
    assert delay.base == 20.0  # half the training rows go each way
    assert delay.contributions[GAP] == 20.0


def test_tree_shap_equals_shapley_values_by_brute_force() -> None:
    """On a small tree with a repeated feature and uneven counts, TreeSHAP must equal the exact
    Shapley values of the path-dependent expectation, computed over every subset of features."""
    a, b, c = 0, 1, 2  # three features of a 3-feature model
    tree = [
        [a, 0.5, 1, 6, 0.0, 100],
        [b, 0.5, 2, 5, 0.0, 60],
        [a, 0.2, 3, 4, 0.0, 45],
        [-1, 0, -1, -1, 3.0, 20],
        [-1, 0, -1, -1, 7.0, 25],
        [-1, 0, -1, -1, -2.0, 15],
        [c, 0.3, 7, 8, 0.0, 40],
        [-1, 0, -1, -1, 11.0, 10],
        [-1, 0, -1, -1, 5.0, 30],
    ]
    parsed = model._tree(tree, 3)
    x = (0.1, 0.7, 0.9)

    def expectation(known: set[int], node: int = 0) -> float:
        f = parsed.feature[node]
        if f < 0:
            return parsed.value[node]
        left, right = parsed.left[node], parsed.right[node]
        if f in known:
            return expectation(known, left if x[f] <= parsed.threshold[node] else right)
        weight = parsed.count[node]
        return (
            parsed.count[left] * expectation(known, left) + parsed.count[right] * expectation(known, right)
        ) / weight

    exact = []
    for i in range(3):
        others = [j for j in range(3) if j != i]
        total = 0.0
        for size in range(3):
            for subset in itertools.combinations(others, size):
                weight = math.factorial(size) * math.factorial(3 - size - 1) / math.factorial(3)
                total += weight * (expectation({*subset, i}) - expectation(set(subset)))
        exact.append(total)

    phi = [0.0, 0.0, 0.0]
    parsed.shap(x, phi)

    assert phi == pytest.approx(exact, abs=1e-12)
    assert parsed.expected() == pytest.approx(expectation(set()))
    assert parsed.expected() + sum(phi) == pytest.approx(parsed.leaf(x))


def test_a_line_and_its_shap_values() -> None:
    coef = [0.0] * N
    coef[GAP] = -0.5
    mean = [0.0] * N
    mean[GAP] = -4.0
    m = model.parse(doc(overrun=line_target(3.0, coef, mean)))

    _, overrun = m.predict(vector(progress_gap_pct=-10))

    assert overrun.value == 8.0
    assert overrun.base == 5.0  # the line at the average snapshot
    assert overrun.contributions[GAP] == 3.0  # 6 points further behind than average, 0.5 each


def test_the_range_grows_with_the_programme_still_to_run() -> None:
    span = {
        "features": list(model.RANGE_FEATURES),
        "p10": {"intercept": -2.0, "coef": [0.0, -0.1]},
        "p90": {"intercept": 5.0, "coef": [0.0, 0.2]},
    }
    m = model.parse(doc(delay=trees_target([leaf(10.0)], span=span)))

    delay, _ = m.predict(vector(planned_duration_days=400, elapsed_pct=75))  # 100 planned days left

    assert (delay.low, delay.value, delay.high) == pytest.approx((-2.0, 10.0, 35.0))
    past_end, _ = m.predict(vector(planned_duration_days=400, elapsed_pct=130))
    assert (past_end.low, past_end.high) == pytest.approx((8.0, 15.0))


def test_crossed_offsets_still_give_a_range_around_the_forecast() -> None:
    span = {
        "features": list(model.RANGE_FEATURES),
        "p10": {"intercept": 3.0, "coef": [0.0, 0.0]},  # above the forecast
        "p90": {"intercept": -1.0, "coef": [0.0, 0.0]},  # below it
    }
    m = model.parse(doc(delay=trees_target([leaf(10.0)], span=span)))

    delay, _ = m.predict(vector())

    assert (delay.low, delay.value, delay.high) == (9.0, 10.0, 13.0)


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
    split = [[GAP, 0.0, 1, 2, 1.0, 20], leaf(2.0), leaf(0.0)]
    d["targets"]["delay_days"]["point"]["trees"] = [copy.deepcopy(split)]
    tree = d["targets"]["delay_days"]["point"]["trees"][0]
    target = d["targets"]["delay_days"]
    if change == "format":
        d["format"] = "sitesense-gbdt-v1"
    elif change == "no features":
        d["features"] = []
    elif change == "no planned duration":
        d["features"] = [f for f in FEATURE_NAMES if f != "planned_duration_days"]
    elif change == "missing target":
        del d["targets"]["overrun_pct"]
    elif change == "extra target":
        d["targets"]["anything"] = target
    elif change == "unknown kind":
        target["kind"] = "pickle"
    elif change == "empty trees":
        target["point"]["trees"] = []
    elif change == "unknown feature":
        tree[0][0] = N
    elif change == "child before parent":  # would let a walk loop forever
        tree[1] = [GAP, 0.0, 0, 2, 1.0, 10]
    elif change == "child out of range":
        tree[0][3] = 9
    elif change == "short node":
        tree[1] = [-1, 0, -1, -1, 2.0]
    elif change == "text in node":
        tree[1] = [-1, 0, -1, -1, "2.0", 10]
    elif change == "boolean in node":
        tree[1] = [-1, 0, -1, -1, True, 10]
    elif change == "infinite value":
        tree[1] = [-1, 0, -1, -1, math.inf, 10]
    elif change == "zero count":
        tree[1] = [-1, 0, -1, -1, 2.0, 0]
    elif change == "too many trees":
        target["point"]["trees"] = [[leaf(0.0)]] * (model.MAX_TREES + 1)
    elif change == "no range":
        del target["range"]
    elif change == "range over other inputs":
        target["range"]["features"] = ["progress_gap_pct", "elapsed_pct"]
    elif change == "short range line":
        target["range"]["p90"]["coef"] = [0.1]
    elif change == "line without means":
        d["targets"]["overrun_pct"] = line_target(1.0, [0.0] * N)
        del d["targets"]["overrun_pct"]["point"]["mean"]
    elif change == "line too short":
        d["targets"]["overrun_pct"] = line_target(1.0, [0.0] * (N - 1))
    elif change == "line not finite":
        d["targets"]["overrun_pct"] = line_target(math.nan, [0.0] * N)
    return d


@pytest.mark.parametrize(
    "change",
    [
        "format", "no features", "no planned duration", "missing target", "extra target", "unknown kind",
        "empty trees", "unknown feature", "child before parent", "child out of range", "short node",
        "text in node", "boolean in node", "infinite value", "zero count", "too many trees", "no range",
        "range over other inputs", "short range line", "line without means", "line too short",
        "line not finite",
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
        ("wet_days_ahead", 41.6, "about 42 heavy-rain days expected in the rest of the programme"),
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
