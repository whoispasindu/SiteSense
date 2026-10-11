"""Risk model v2 building blocks: point and quantile models, as trees or as a straight line.

For each target (delay days, overrun %) ``train.py`` fits:

- **trees:** LightGBM, tuned by cross-validation grouped by project, with monotone constraints;
- **a straight line:** least squares with the *same* sign constraints (a feature that can only raise
  the forecast gets a coefficient of zero or more), so a recovery action in the what-if planner can
  never make the forecast worse because of a fitted sign that runs backwards;

``choose`` decides which family ships: the trees only if they are *clearly* better than the
straight line; when the two match, or the line wins, the simpler line ships.

The likely range (10th to 90th percentile) is fitted around the shipped forecast: linear quantile
regression of its out-of-fold errors on the programme's length and the part still to run. The
offsets do not depend on anything a recovery action changes, so an action moves the whole range
with the forecast and can never widen it upwards. (LightGBM's quantile objective cannot take
monotone constraints, so quantile trees could not promise that.)

Everything is exported as plain JSON for the backend's pure-Python scorer (no pickles, ADR 0009).
Tree nodes carry their training counts so the backend can compute exact TreeSHAP values.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import lightgbm as lgb
import numpy as np
import pandas as pd
from scipy import sparse
from scipy.optimize import linprog, lsq_linear
from sklearn.metrics import mean_absolute_error
from sklearn.model_selection import GroupKFold

QUANTILES = {"p10": 0.1, "p90": 0.9}  # the likely range: 8 in 10 outcomes should fall inside it
# What the range's width depends on: longer programmes, and more of them still to run, are less certain.
RANGE_FEATURES = ("planned_duration_days", "remaining_planned_days")
CV_FOLDS = 5
# "Clearly better": a 95% interval for the difference in mean absolute error, from resampling whole
# projects (weeks of one project are not independent), lies entirely on one side of zero.
BOOTSTRAP_RESAMPLES = 2000
BOOTSTRAP_SEED = 2026


# --- Straight line -----------------------------------------------------------------------------------


@dataclass(frozen=True)
class Line:
    intercept: float
    coef: np.ndarray  # on the raw feature scale
    mean: np.ndarray  # training means: the SHAP baseline (an average snapshot)

    def predict(self, x: np.ndarray) -> np.ndarray:
        return self.intercept + x @ self.coef

    def contributions(self, x: np.ndarray) -> tuple[np.ndarray, float]:
        """Exact SHAP values for a linear model with independent features: coef x (x - mean)."""
        return self.coef * (x - self.mean), float(self.intercept + self.mean @ self.coef)

    def as_json(self) -> dict[str, Any]:
        return {
            "intercept": float(self.intercept),
            "coef": [float(c) for c in self.coef],
            "mean": [float(m) for m in self.mean],
        }


def _bounds(columns: list[str], signs: dict[str, int]) -> tuple[np.ndarray, np.ndarray]:
    lower = np.array([0.0 if signs.get(c, 0) > 0 else -np.inf for c in columns])
    upper = np.array([0.0 if signs.get(c, 0) < 0 else np.inf for c in columns])
    return lower, upper


def _standardised(x: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    mean = x.mean(axis=0)
    scale = x.std(axis=0)
    scale[scale == 0] = 1.0  # a constant column: its coefficient ends at zero anyway
    return (x - mean) / scale, mean, scale


def _to_raw(beta: np.ndarray, mean: np.ndarray, scale: np.ndarray, constant: np.ndarray) -> Line:
    coef = beta[:-1] / scale
    coef[constant] = 0.0
    return Line(float(beta[-1] - mean @ coef), coef, mean)


def fit_line(x: pd.DataFrame, y: pd.Series, signs: dict[str, int], reference: tuple[str, ...] = ()) -> Line:
    """Least squares with sign constraints (and a free intercept).

    ``reference`` columns are left out and keep a coefficient of zero: one category of a one-hot
    group, whose columns always sum to one like the intercept. Without it the fit can pick huge
    coefficients that cancel out: the predictions survive, the explanations do not.
    """
    kept = [c for c in x.columns if c not in reference]
    line = _fit_line(x[kept], y, signs)
    return _widen(line, list(x.columns), kept, x)


def _widen(line: Line, columns: list[str], kept: list[str], x: pd.DataFrame) -> Line:
    """Put the reference columns back, with a coefficient of zero."""
    coef = np.zeros(len(columns))
    for i, c in enumerate(kept):
        coef[columns.index(c)] = line.coef[i]
    return Line(line.intercept, coef, x.to_numpy(dtype=float).mean(axis=0))


def _fit_line(x: pd.DataFrame, y: pd.Series, signs: dict[str, int]) -> Line:
    raw = x.to_numpy(dtype=float)
    z, mean, scale = _standardised(raw)
    lower, upper = _bounds(list(x.columns), signs)
    a = np.hstack([z, np.ones((len(z), 1))])
    result = lsq_linear(
        a, y.to_numpy(dtype=float), bounds=(np.append(lower, -np.inf), np.append(upper, np.inf))
    )
    return _to_raw(result.x, mean, scale, raw.std(axis=0) == 0)


def fit_line_quantile(x: pd.DataFrame, y: pd.Series, q: float, signs: dict[str, int] | None = None) -> Line:
    """Linear quantile regression with sign constraints, as a linear programme (HiGHS).

    Minimise q * sum(u) + (1 - q) * sum(v) subject to A b + u - v = y and u, v >= 0, where u and v
    are the parts of each residual above and below the line.
    """
    raw = x.to_numpy(dtype=float)
    z, mean, scale = _standardised(raw)
    n, p = z.shape
    a = sparse.hstack(
        [sparse.csr_matrix(np.hstack([z, np.ones((n, 1))])), sparse.identity(n), -sparse.identity(n)],
        format="csr",
    )
    cost = np.concatenate([np.zeros(p + 1), np.full(n, q), np.full(n, 1 - q)])
    lower, upper = _bounds(list(x.columns), signs or {})
    bounds = [
        (lo if np.isfinite(lo) else None, hi if np.isfinite(hi) else None)
        for lo, hi in zip(lower, upper, strict=True)
    ]
    bounds += [(None, None)] + [(0, None)] * (2 * n)
    result = linprog(cost, A_eq=a, b_eq=y.to_numpy(dtype=float), bounds=bounds, method="highs")
    if not result.success:
        raise RuntimeError(f"Quantile regression did not solve: {result.message}")
    return _to_raw(result.x[: p + 1], mean, scale, raw.std(axis=0) == 0)


# --- Trees -------------------------------------------------------------------------------------------


def tree_params(base: dict[str, Any], extra: dict[str, Any], monotone: list[int]) -> dict[str, Any]:
    return {**base, **extra, "monotone_constraints": monotone, "objective": "regression", "metric": "rmse"}


def cv_rounds(params: dict[str, Any], x: pd.DataFrame, y: pd.Series, groups: pd.Series) -> tuple[int, float]:
    """Boosting rounds by grouped cross-validation with early stopping; returns (rounds, cv score)."""
    folds = list(GroupKFold(n_splits=CV_FOLDS).split(x, y, groups))
    result = lgb.cv(
        params,
        lgb.Dataset(x, y, free_raw_data=False),
        num_boost_round=2000,
        folds=folds,
        callbacks=[lgb.early_stopping(50, verbose=False)],
    )
    key = next(k for k in result if k.endswith("-mean"))
    return len(result[key]), float(result[key][-1])


def export_tree(node: dict[str, Any], nodes: list[list[float]]) -> int:
    """Flatten a LightGBM tree into rows [feature, threshold, left, right, value, count].

    Leaves have feature -1. ``count`` is the number of training rows that reached the node, which
    TreeSHAP needs to weigh the branch a feature's value does not take.
    """
    index = len(nodes)
    if "leaf_value" in node:
        nodes.append([-1, 0.0, -1, -1, float(node["leaf_value"]), float(node["leaf_count"])])
        return index
    if node["decision_type"] != "<=" or node["missing_type"] != "None":
        raise ValueError(f"Unsupported split: {node['decision_type']} / {node['missing_type']}")
    nodes.append(
        [
            int(node["split_feature"]),
            float(node["threshold"]),
            -1,
            -1,
            float(node["internal_value"]),
            float(node["internal_count"]),
        ]
    )
    nodes[index][2] = export_tree(node["left_child"], nodes)
    nodes[index][3] = export_tree(node["right_child"], nodes)
    return index


def export_trees(booster: lgb.Booster, features: list[str]) -> dict[str, Any]:
    dump = booster.dump_model()
    if dump["feature_names"] != features:
        raise ValueError("Feature order changed between training and export")
    trees = []
    for info in dump["tree_info"]:
        nodes: list[list[float]] = []
        export_tree(info["tree_structure"], nodes)
        trees.append(nodes)
    return {"trees": trees}


# --- Choosing --------------------------------------------------------------------------------------


def out_of_fold(fit_predict: Any, x: pd.DataFrame, y: pd.Series, groups: pd.Series) -> np.ndarray:
    """Each training row predicted by a model that never saw its project (folds grouped by project)."""
    predicted = np.empty(len(y))
    for train_idx, test_idx in GroupKFold(n_splits=CV_FOLDS).split(x, y, groups):
        predicted[test_idx] = fit_predict(x.iloc[train_idx], y.iloc[train_idx], x.iloc[test_idx])
    return predicted


def mae(y: pd.Series, predicted: np.ndarray) -> float:
    return float(mean_absolute_error(y, predicted))


def range_design(x: pd.DataFrame) -> pd.DataFrame:
    """The range's inputs: planned length, and the planned days still to run (none once past the end)."""
    remaining = x["planned_duration_days"] * np.clip(1 - x["elapsed_pct"] / 100, 0, None)
    return pd.DataFrame(
        {"planned_duration_days": x["planned_duration_days"], "remaining_planned_days": remaining}
    )


def fit_range(x: pd.DataFrame, errors: np.ndarray) -> dict[str, Line]:
    """Offsets from the forecast to its 10th and 90th percentiles: quantile regression of the errors."""
    design = range_design(x)
    target = pd.Series(errors, index=x.index)
    return {which: fit_line_quantile(design, target, q) for which, q in QUANTILES.items()}


def error_difference(errors_a: np.ndarray, errors_b: np.ndarray, groups: pd.Series) -> dict[str, float]:
    """Mean of (errors_a - errors_b), with a 95% interval from resampling whole projects.

    Negative means A's errors are smaller. Both arrays are per row (absolute errors, or any loss),
    aligned with ``groups``.
    """
    frame = pd.DataFrame({"g": groups.to_numpy(), "a": errors_a, "b": errors_b})
    per_project = frame.groupby("g").agg(a=("a", "sum"), b=("b", "sum"), n=("a", "size"))
    a, b, n = (per_project[c].to_numpy(dtype=float) for c in ("a", "b", "n"))
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    draws = rng.integers(0, len(n), size=(BOOTSTRAP_RESAMPLES, len(n)))
    diffs = (a[draws].sum(axis=1) - b[draws].sum(axis=1)) / n[draws].sum(axis=1)
    low, high = np.percentile(diffs, [2.5, 97.5])
    return {
        "mean": round(float((a.sum() - b.sum()) / n.sum()), 4),
        "low": round(float(low), 4),
        "high": round(float(high), 4),
    }


def clearly_better(difference: dict[str, float]) -> bool:
    """A is clearly better than B when the whole interval of (A - B) is below zero."""
    return difference["high"] < 0


def choose(y: pd.Series, oof: dict[str, np.ndarray], groups: pd.Series) -> tuple[str, dict[str, float]]:
    """'trees' only if they are clearly better than the line on out-of-fold errors; otherwise 'linear'."""
    truth = y.to_numpy(dtype=float)
    difference = error_difference(np.abs(truth - oof["trees"]), np.abs(truth - oof["linear"]), groups)
    return ("trees" if clearly_better(difference) else "linear"), difference


def ordered(point: np.ndarray, low: np.ndarray, high: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """The range always contains the point forecast, even where separately fitted quantiles cross."""
    return np.minimum.reduce([low, point, high]), np.maximum.reduce([low, point, high])
