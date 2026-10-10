"""The simulator and exporter: reproducible, finite, and consistent with the backend's definitions."""

import json
import math
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pytest

from data_generator import simulate
from train import export_model

BACKEND_MODEL = Path(__file__).parents[2] / "backend" / "app" / "ai" / "risk" / "models" / "risk-v1.0.0.json"


@pytest.fixture(scope="module")
def rainfall() -> dict:
    return simulate.load_rainfall()


def test_same_seed_same_projects(rainfall: dict) -> None:
    first = simulate.generate(8, seed=7, rainfall=rainfall)
    second = simulate.generate(8, seed=7, rainfall=rainfall)

    assert first == second
    assert simulate.generate(8, seed=8, rainfall=rainfall) != first


def test_every_snapshot_has_finite_features_and_an_outcome(rainfall: dict) -> None:
    rows = simulate.generate(15, seed=11, rainfall=rainfall)

    assert {r["project_id"] for r in rows} == set(range(1, 16))
    for row in rows:
        assert all(math.isfinite(float(row[f])) for f in simulate.FEATURES)
        assert sum(row[f"type_{t}"] for t in simulate.PROJECT_TYPES) == 1
        assert 0 <= row["final_score"] <= 100
        assert row["missing_reports_14"] <= 12


def test_the_hidden_quality_is_never_a_feature() -> None:
    assert "quality" not in simulate.FEATURES
    assert not set(simulate.TARGETS) & set(simulate.FEATURES)


def test_rainfall_history_is_real_and_complete(rainfall: dict) -> None:
    assert len(rainfall) == 7
    assert all(len(days) > 5000 for days in rainfall.values())
    # Ratnapura is the wettest town and Jaffna one of the driest: a quick check the data is what it says.
    yearly = {town: sum(days.values()) / (len(days) / 365.25) for town, days in rainfall.items()}
    assert yearly["ratnapura"] > 3000 > yearly["jaffna"]


@pytest.mark.parametrize(("fraction", "expected"), [(-1, 0.0), (0, 0.0), (0.5, 0.5), (1, 1.0), (2, 1.0)])
def test_s_curve(fraction: float, expected: float) -> None:
    assert simulate.s_curve(fraction) == pytest.approx(expected)


@pytest.mark.parametrize(
    ("delay", "overrun", "planned", "score"),
    [
        (0, 0, 400, 0),
        (40, 0, 400, 40),
        (70, 0, 400, 70),
        (0, 14, 400, 70),
        (500, 0, 400, 100),
        (-10, -2, 400, 0),
    ],
)
def test_risk_score_matches_the_backend_cases(
    delay: float, overrun: float, planned: float, score: int
) -> None:
    """Same cases as backend/tests/test_risk_model.py::test_risk_score: one definition in two places."""
    assert simulate.risk_score(delay, overrun, planned) == score


def test_exported_trees_reproduce_lightgbm() -> None:
    rng = np.random.default_rng(3)
    x = rng.normal(size=(400, len(simulate.FEATURES)))
    y = 3 * x[:, 2] - 2 * x[:, 5] + rng.normal(size=400)
    params = {"objective": "regression", "num_leaves": 7, "verbose": -1, "use_missing": False, "seed": 1}
    booster = lgb.train(params, lgb.Dataset(x, y, feature_name=list(simulate.FEATURES)), num_boost_round=20)

    trees = export_model(booster)

    def score(row: np.ndarray) -> float:
        total = 0.0
        for nodes in trees:
            i = 0
            while nodes[i][0] >= 0:
                f, threshold, left, right, _ = nodes[i]
                i = int(left) if row[int(f)] <= threshold else int(right)
            total += nodes[i][4]
        return total

    expected = booster.predict(x[:50])
    assert [score(r) for r in x[:50]] == pytest.approx(list(expected), abs=1e-9)


def test_the_shipped_model_lists_the_simulators_features() -> None:
    model = json.loads(BACKEND_MODEL.read_text(encoding="utf-8"))

    assert model["features"] == list(simulate.FEATURES)
    assert model["format"] == "sitesense-gbdt-v1"
