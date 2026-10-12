"""Risk model v2 building blocks: sign-constrained lines, quantile regression, ranges and the choice."""

import importlib.util
import sys
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
import pytest

import risk_models as rm
from data_generator import simulate

BACKEND_MODEL_CODE = Path(__file__).parents[2] / "backend" / "app" / "ai" / "risk" / "model.py"


def backend_model():  # type: ignore[no-untyped-def]
    """The backend's scorer, loaded by path (it uses the standard library only)."""
    spec = importlib.util.spec_from_file_location("backend_risk_model", BACKEND_MODEL_CODE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["backend_risk_model"] = module
    spec.loader.exec_module(module)
    return module


def data(n: int = 600, seed: int = 1) -> tuple[pd.DataFrame, pd.Series, pd.Series]:
    rng = np.random.default_rng(seed)
    x = pd.DataFrame({"good": rng.normal(size=n), "bad": rng.normal(size=n), "noise": rng.normal(size=n)})
    y = pd.Series(2 * x["good"] + 0.3 * x["bad"] + rng.normal(scale=1.0, size=n))
    groups = pd.Series(np.repeat(np.arange(n // 10), 10))
    return x, y, groups


def test_a_line_obeys_its_signs() -> None:
    x, y, _ = data()

    free = rm.fit_line(x, y, {})
    forced = rm.fit_line(x, y, {"bad": -1})  # told "bad" can only lower the forecast

    assert free.coef[1] > 0.2
    assert forced.coef[1] == pytest.approx(0.0, abs=1e-9)
    assert forced.coef[0] == pytest.approx(2.0, abs=0.15)


def test_a_reference_column_keeps_a_zero_coefficient() -> None:
    x, y, _ = data()
    x["one"] = 1.0 - x["noise"] * 0  # duplicates the intercept

    line = rm.fit_line(x, y, {}, reference=("one",))

    assert line.coef[list(x.columns).index("one")] == 0.0
    assert line.predict(x.to_numpy()) == pytest.approx(
        rm.fit_line(x.drop(columns="one"), y, {}).predict(x.drop(columns="one").to_numpy())
    )


def test_line_shap_values_add_up() -> None:
    x, y, _ = data()
    line = rm.fit_line(x, y, {})
    row = x.to_numpy()[0]

    values, base = line.contributions(row)

    assert base + values.sum() == pytest.approx(line.predict(row[None, :])[0])
    assert base == pytest.approx(line.predict(x.to_numpy()).mean())


@pytest.mark.parametrize("q", [0.1, 0.9])
def test_quantile_regression_puts_the_right_share_below(q: float) -> None:
    x, y, _ = data(2000)

    line = rm.fit_line_quantile(x, y, q)

    assert (y.to_numpy() <= line.predict(x.to_numpy())).mean() == pytest.approx(q, abs=0.02)


def test_the_range_widens_with_the_programme_still_to_run() -> None:
    rng = np.random.default_rng(4)
    n = 3000
    x = pd.DataFrame(
        {"planned_duration_days": rng.uniform(200, 800, n), "elapsed_pct": rng.uniform(0, 120, n)}
    )
    remaining = x["planned_duration_days"] * np.clip(1 - x["elapsed_pct"] / 100, 0, None)
    errors = rng.normal(scale=5 + 0.1 * remaining.to_numpy())

    offsets = rm.fit_range(x, errors)
    design = rm.range_design(x).to_numpy()
    low, high = offsets["p10"].predict(design), offsets["p90"].predict(design)

    inside = (errors >= low) & (errors <= high)
    assert inside.mean() == pytest.approx(0.8, abs=0.03)
    early = remaining.to_numpy() > 400
    assert (high - low)[early].mean() > 2 * (high - low)[~early].mean()


def test_ordered_ranges_always_hold_the_forecast() -> None:
    low, high = rm.ordered(np.array([10.0, 10.0]), np.array([12.0, 5.0]), np.array([8.0, 15.0]))

    assert list(low) == [8.0, 5.0]
    assert list(high) == [12.0, 15.0]


def test_the_trees_ship_only_when_clearly_better() -> None:
    _, y, groups = data()
    truth = y.to_numpy()
    rng = np.random.default_rng(2)
    noise = rng.normal(size=len(truth))
    other = rng.normal(size=len(truth))  # the same size of error, independently: a tie

    close = {"trees": truth + noise, "linear": truth + other}
    far = {"trees": truth + noise * 0.5, "linear": truth + noise * 2}
    worse = {"trees": truth + noise * 2, "linear": truth + noise * 0.5}

    assert rm.choose(y, close, groups)[0] == "linear"  # a tie goes to the simpler model
    kind, difference = rm.choose(y, far, groups)
    assert kind == "trees"
    assert difference["low"] < difference["mean"] < difference["high"] < 0
    assert rm.choose(y, worse, groups)[0] == "linear"


def test_the_backend_computes_lightgbms_shap_values() -> None:
    rng = np.random.default_rng(5)
    features = list(simulate.FEATURES)
    x = rng.normal(size=(500, len(features)))
    y = 3 * x[:, 2] - 2 * x[:, 5] + x[:, 2] * x[:, 9] + rng.normal(size=500)
    params = {"objective": "regression", "num_leaves": 15, "verbose": -1, "use_missing": False, "seed": 1,
              "bagging_fraction": 0.8, "bagging_freq": 1}  # fmt: skip
    booster = lgb.train(params, lgb.Dataset(x, y, feature_name=features), num_boost_round=30)
    backend = backend_model()
    trees = tuple(
        backend._tree(nodes, len(features)) for nodes in rm.export_trees(booster, features)["trees"]
    )
    ensemble = backend.Ensemble(trees, len(features))

    expected = booster.predict(x[:20], pred_contrib=True)
    for row, contrib in zip(x[:20], expected, strict=True):
        value, base, phi = ensemble.predict(tuple(float(v) for v in row))
        assert phi == pytest.approx(list(contrib[:-1]), abs=1e-9)
        assert base == pytest.approx(contrib[-1], abs=1e-9)
        assert value == pytest.approx(contrib.sum(), abs=1e-9)
