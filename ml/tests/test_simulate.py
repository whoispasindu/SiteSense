"""The simulator and exporter: reproducible, finite, and consistent with the backend's definitions."""

import importlib.util
import json
import math
import sys
from datetime import date, timedelta
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pytest

from data_generator import simulate
from train import export_model

BACKEND_MODEL = Path(__file__).parents[2] / "backend" / "app" / "ai" / "risk" / "models" / "risk-v1.2.0.json"


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


# --- Rain (risk model 1.2, issue #27) -------------------------------------------------------------------

BACKEND_RISK = Path(__file__).parents[2] / "backend" / "app" / "ai" / "risk"


def backend_climate():  # type: ignore[no-untyped-def]
    """The backend's climate module, loaded by path (it uses the standard library only)."""
    spec = importlib.util.spec_from_file_location("backend_climate", BACKEND_RISK / "climate.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["backend_climate"] = module  # dataclasses look their module up while being created
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    ("mm", "yesterday", "lost"),
    [
        (0, 0, 0.0),
        (1.9, 0, 0.0),
        (2, 0, 0.1),
        (9.9, 0, 0.1),
        (10, 0, 0.45),
        (25, 0, 0.8),
        (0, 10, 0.25),
        (25, 30, 1.0),
    ],
)
def test_the_rain_bands_and_the_day_after(mm: float, yesterday: float, lost: float) -> None:
    assert simulate.lost_day(mm, yesterday) == pytest.approx(lost)


def test_the_rain_allowance_is_a_named_assumption() -> None:
    assert simulate.RAIN_ALLOWANCE == 0.5
    source = Path(simulate.__file__).read_text(encoding="utf-8")
    assert "ASSUMPTION, NOT MEASURED" in source
    assert "RAIN_ALLOWANCE" in (Path(simulate.__file__).parent / "ASSUMPTIONS.md").read_text(encoding="utf-8")


def test_the_pace_keeps_the_median_project_ten_percent_late(rainfall: dict) -> None:
    rows = simulate.generate(300, seed=2026, rainfall=rainfall)

    assert simulate.median_delay_pct(rows) == pytest.approx(simulate.TARGET_MEDIAN_DELAY_PCT, abs=0.5)


def test_the_backend_climate_table_is_the_simulators(rainfall: dict) -> None:
    from data_generator import climate

    shipped = json.loads((BACKEND_RISK / "rain_climate.json").read_text(encoding="utf-8"))

    assert shipped == json.loads(json.dumps(climate.table()))


def test_the_backend_computes_wet_days_ahead_like_the_simulator(rainfall: dict) -> None:
    backend = backend_climate()
    rng = np.random.default_rng(3)
    for town in sorted(rainfall):
        mine = simulate.heavy_rain_climate(rainfall[town])
        theirs = backend.Town(town, 0.0, 0.0, tuple(mine[m] for m in range(1, 13)))
        for _ in range(20):
            today = date(2026, 1, 1) + timedelta(days=int(rng.integers(0, 700)))
            end = today + timedelta(days=int(rng.integers(-60, 900)))
            assert backend.wet_days_ahead(theirs, today, end) == pytest.approx(
                simulate.wet_days_ahead(mine, today, end), abs=1e-9
            )
