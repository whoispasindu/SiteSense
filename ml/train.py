"""Train risk model v2: final delay (days) and cost overrun (%), each with a likely range.

    python -m data_generator.simulate      # writes data/snapshots.csv
    python train.py                        # trains, evaluates, exports

Method
    - Train/test split grouped by project (no project has weeks on both sides, so nothing leaks).
    - For each target, two families compete (``risk_models.py``):
        * trees: LightGBM, tuned with 5-fold cross-validation grouped by project;
        * a straight line: least squares.
      Both have the same monotone (sign) constraints where the direction is known: falling further
      behind can only raise the predicted delay, so no model can learn a backwards rule from noise.
    - The trees ship only if their out-of-fold errors are clearly smaller than the line's (a 95%
      interval over projects); when the two match, or the line wins, the simpler line ships.
    - The likely range is the 10th to 90th percentile around the shipped forecast: quantile
      regression of its out-of-fold errors on the programme's length and the part still to run.
    - Metrics on the held-out projects: MAE, RMSE and R squared for both families, range coverage
      (how often the outcome fell inside the range), F1 for the High class, and a backtest of how
      early projects that ended High were flagged.

Export
    The backend does not load pickles (joblib/pickle files run code when loaded). Models are exported
    as plain JSON (``backend/app/ai/risk/models/risk-v<version>.json``): trees as node lists with
    their training counts (for exact TreeSHAP), lines as coefficients. Golden rows record LightGBM's
    own predictions and SHAP values, so a backend test proves the pure-Python scorer agrees.
    Metrics and settings go to ``models/risk-v<version>/metrics.json``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.metrics import confusion_matrix, f1_score, mean_absolute_error, mean_squared_error, r2_score
from sklearn.model_selection import GroupShuffleSplit

import risk_models as rm
from data_generator.simulate import FEATURES, PROJECT_TYPES, TARGETS, risk_score

ML = Path(__file__).parent
DATA = ML / "data" / "snapshots.csv"
BACKEND_MODELS = ML.parent / "backend" / "app" / "ai" / "risk" / "models"
VERSION = "2.0.0"
MODEL_FORMAT = "sitesense-risk-v2"
SEED = 2026
BANDS = ("low", "medium", "high")

# +1: a higher value can only raise the prediction; -1: can only lower it; 0: learnt freely.
# Every input a what-if recovery action changes (crew, deliveries, rain) has a direction for both
# targets, so no action can make a forecast worse.
MONOTONE: dict[str, dict[str, int]] = {
    "delay_days": {
        "progress_gap_pct": -1,
        "progress_rate_trend": -1,
        "late_deliveries_count": 1,
        "avg_lateness_days": 1,
        "rain_days_next_14": 1,
        "wet_days_ahead": 1,
        "crew_vs_plan_pct": -1,
        "missing_reports_14": 1,
        "issues_material_14": 1,
        "issues_safety_14": 1,
        "issues_design_14": 1,
    },
    "overrun_pct": {
        "progress_gap_pct": -1,
        "budget_variance_pct": 1,
        "rain_days_next_14": 1,
        "wet_days_ahead": 1,
        "crew_vs_plan_pct": -1,
        "late_deliveries_count": 1,
        "avg_lateness_days": 1,
        "issues_design_14": 1,
    },
}
BASE_PARAMS: dict[str, Any] = {
    "learning_rate": 0.05,
    "feature_fraction": 0.9,
    "bagging_fraction": 0.8,
    "bagging_freq": 1,
    "use_missing": False,  # the feature builder always supplies numbers; keeps the exported trees simple
    "zero_as_missing": False,
    "deterministic": True,
    "force_row_wise": True,
    "seed": SEED,
    "verbose": -1,
}
GRID = [{"num_leaves": n, "min_child_samples": m} for n in (7, 15, 31) for m in (40, 100)]
GOLDEN_ROWS = 25
# The straight line measures each project type against residential (the most common), so the type
# columns cannot duplicate the intercept.
REFERENCE = (f"type_{PROJECT_TYPES[0]}",)


def band(score: int) -> str:
    return "high" if score >= 70 else "medium" if score >= 40 else "low"


def scores(delay: np.ndarray, overrun: np.ndarray, planned_days: np.ndarray) -> np.ndarray:
    return np.array([risk_score(d, o, p) for d, o, p in zip(delay, overrun, planned_days, strict=True)])


def regression_metrics(y: np.ndarray, pred: np.ndarray) -> dict[str, float]:
    return {
        "mae": round(float(mean_absolute_error(y, pred)), 2),
        "rmse": round(float(np.sqrt(mean_squared_error(y, pred))), 2),
        "r2": round(float(r2_score(y, pred)), 3),
    }


# --- Fitting one target ------------------------------------------------------------------------------


@dataclass
class TargetModels:
    """Both families for one target, which one ships, and the range around its forecast."""

    kind: str  # "trees" or "linear"
    trees: lgb.Booster
    line: rm.Line
    range: dict[str, rm.Line]  # offsets from the forecast to its 10th and 90th percentiles
    tree_params: dict[str, Any]
    rounds: int
    cv: dict[str, Any]

    def predict(self, which: str, x: pd.DataFrame, kind: str | None = None) -> np.ndarray:
        """``point``, or ``p10`` / ``p90``: the forecast plus its offset (before ordering)."""
        if (kind or self.kind) == "trees":
            point = np.asarray(self.trees.predict(x))
        else:
            point = self.line.predict(x.to_numpy(dtype=float))
        if which == "point":
            return point
        return point + self.range[which].predict(rm.range_design(x).to_numpy(dtype=float))

    def contributions(self, x: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
        """SHAP values of the shipped point model per row, and the base value per row."""
        if self.kind == "trees":
            raw = np.asarray(self.trees.predict(x, pred_contrib=True))
            return raw[:, :-1], raw[:, -1]
        rows = x.to_numpy(dtype=float)
        values = np.array([self.line.contributions(row)[0] for row in rows])
        return values, np.full(len(rows), self.line.contributions(rows[0])[1])

    def export(self) -> dict[str, Any]:
        point = rm.export_trees(self.trees, list(FEATURES)) if self.kind == "trees" else self.line.as_json()
        offsets = {
            w: {"intercept": line.intercept, "coef": [float(c) for c in line.coef]}
            for w, line in self.range.items()
        }
        return {"kind": self.kind, "point": point, "range": {"features": list(rm.RANGE_FEATURES), **offsets}}


def tune(x: pd.DataFrame, y: pd.Series, groups: pd.Series, target: str) -> tuple[dict[str, Any], int, float]:
    """Pick tree size and rounds by 5-fold cross-validation grouped by project."""
    monotone = [MONOTONE[target].get(f, 0) for f in FEATURES]
    best: tuple[dict[str, Any], int, float] | None = None
    for extra in GRID:
        params = rm.tree_params(BASE_PARAMS, extra, monotone)
        rounds, rmse = rm.cv_rounds(params, x, y, groups)
        print(f"  {target} {extra}: cv rmse {rmse:.3f} at {rounds} rounds")
        if best is None or rmse < best[2]:
            best = (extra, rounds, rmse)
    assert best is not None
    return best


def fit_target(x: pd.DataFrame, y: pd.Series, groups: pd.Series, target: str) -> TargetModels:
    signs = MONOTONE[target]
    monotone = [signs.get(f, 0) for f in FEATURES]
    extra, rounds, _ = tune(x, y, groups, target)
    params = rm.tree_params(BASE_PARAMS, extra, monotone)
    trees = lgb.train(params, lgb.Dataset(x, y), num_boost_round=rounds)
    line = rm.fit_line(x, y, signs, REFERENCE)

    def trees_fold(xa: pd.DataFrame, ya: pd.Series, xb: pd.DataFrame) -> np.ndarray:
        return np.asarray(lgb.train(params, lgb.Dataset(xa, ya), num_boost_round=rounds).predict(xb))

    def line_fold(xa: pd.DataFrame, ya: pd.Series, xb: pd.DataFrame) -> np.ndarray:
        return rm.fit_line(xa, ya, signs, REFERENCE).predict(xb.to_numpy(dtype=float))

    oof = {
        "trees": rm.out_of_fold(trees_fold, x, y, groups),
        "linear": rm.out_of_fold(line_fold, x, y, groups),
    }
    cv = {"trees_mae": round(rm.mae(y, oof["trees"]), 3), "linear_mae": round(rm.mae(y, oof["linear"]), 3)}
    kind, difference = rm.choose(y, oof, groups)
    cv["trees_minus_linear_mae"] = difference  # negative: the trees' errors are smaller
    print(
        f"  {target}: cv MAE trees {cv['trees_mae']}, line {cv['linear_mae']}, {difference} -> ships {kind}"
    )
    offsets = rm.fit_range(x, y.to_numpy(dtype=float) - oof[kind])
    used = {**extra, "learning_rate": BASE_PARAMS["learning_rate"]}
    return TargetModels(kind, trees, line, offsets, used, rounds, cv)


# --- Evaluation ------------------------------------------------------------------------------------


def backtest(test: pd.DataFrame, predicted: np.ndarray) -> dict[str, Any]:
    """How early were projects that ended High flagged High, and how often were Low projects flagged?"""
    frame = test.assign(predicted=predicted)
    flagged_at: list[float] = []
    lead_weeks: list[float] = []
    missed = 0
    false_alarms = 0
    lows = 0
    for _, weeks in frame.groupby("project_id"):
        weeks = weeks.sort_values("snapshot_date")
        final = band(int(weeks["final_score"].iloc[0]))
        hits = weeks[weeks["predicted"] >= 70]
        if final == "high":
            if hits.empty:
                missed += 1
            else:
                first = hits.iloc[0]
                flagged_at.append(float(first["elapsed_pct"]))
                lead_weeks.append(
                    float(first["planned_duration_days"] * (1 - first["elapsed_pct"] / 100) / 7)
                )
        elif final == "low":
            lows += 1
            false_alarms += int(not hits.empty)
    return {
        "high_projects": len(flagged_at) + missed,
        "flagged": len(flagged_at),
        "median_flagged_at_elapsed_pct": round(float(np.median(flagged_at)), 1) if flagged_at else None,
        "median_weeks_before_planned_end": round(float(np.median(lead_weeks)), 1) if lead_weeks else None,
        "low_projects": lows,
        "low_projects_ever_flagged_high": false_alarms,
    }


def stages(elapsed: pd.Series) -> pd.Series:
    return pd.cut(
        elapsed, [0, 25, 50, 75, 100, 1000], labels=["0-25%", "25-50%", "50-75%", "75-100%", "late"]
    )


def range_report(
    y: np.ndarray, point: np.ndarray, low: np.ndarray, high: np.ndarray, stage: pd.Series
) -> dict[str, Any]:
    low, high = rm.ordered(point, low, high)
    inside = (y >= low) & (y <= high)
    return {
        "coverage": round(float(inside.mean()), 3),  # aim: about 0.8
        "mean_width": round(float((high - low).mean()), 2),
        "coverage_by_elapsed": {
            str(s): round(float(inside[(stage == s).to_numpy()].mean()), 3)
            for s in stage.cat.categories
            if (stage == s).any()
        },
    }


def shap_shares(values: np.ndarray) -> dict[str, float]:
    """Each feature's share of the mean absolute SHAP value (project types combined per row first)."""
    keys = ["project_type" if name.startswith("type_") else name for name in FEATURES]
    per_row: dict[str, np.ndarray] = {}
    for i, key in enumerate(keys):
        per_row[key] = per_row.get(key, 0.0) + values[:, i]
    combined = {k: float(np.abs(v).mean()) for k, v in per_row.items()}
    total = sum(combined.values()) or 1.0
    return {k: round(v / total * 100, 1) for k, v in sorted(combined.items(), key=lambda p: -p[1]) if v > 0}


def train_and_evaluate(data: pd.DataFrame) -> tuple[dict[str, TargetModels], dict[str, Any], pd.DataFrame]:
    """Grouped split, both families, ranges and every held-out metric: the models, report and test rows."""
    split = GroupShuffleSplit(n_splits=1, test_size=0.2, random_state=SEED)
    train_idx, test_idx = next(split.split(data, groups=data["project_id"]))
    train, test = data.iloc[train_idx], data.iloc[test_idx]
    x_train, x_test = train[list(FEATURES)], test[list(FEATURES)]
    print(
        f"{len(train)} training rows ({train.project_id.nunique()} projects), "
        f"{len(test)} test rows ({test.project_id.nunique()} projects)"
    )
    stage = stages(test["elapsed_pct"])

    models: dict[str, TargetModels] = {}
    report: dict[str, Any] = {"targets": {}}
    shipped: dict[str, np.ndarray] = {}
    linear: dict[str, np.ndarray] = {}
    for target in TARGETS:
        m = fit_target(x_train, train[target], train["project_id"], target)
        models[target] = m
        y = test[target].to_numpy()
        shipped[target] = m.predict("point", x_test)
        linear[target] = m.predict("point", x_test, kind="linear")
        gain = m.trees.feature_importance("gain")
        shap_values, _ = m.contributions(x_test)
        report["targets"][target] = {
            "shipped": m.kind,
            "cv_mae": m.cv,
            "params": m.tree_params,
            "rounds": m.rounds,
            "test": regression_metrics(y, shipped[target]),
            "trees_test": regression_metrics(y, m.predict("point", x_test, kind="trees")),
            "baseline_test": regression_metrics(y, linear[target]),
            "range": range_report(
                y, shipped[target], m.predict("p10", x_test), m.predict("p90", x_test), stage
            ),
            # The trees' split gain, whichever family ships (comparable across versions).
            "importance_gain_pct": {
                f: round(float(g / gain.sum() * 100), 1)
                for f, g in sorted(zip(FEATURES, gain, strict=True), key=lambda p: -p[1])
                if g > 0
            },
            # What the shipped model actually leans on: mean absolute SHAP value on the test rows.
            "shap_share_pct": shap_shares(shap_values),
        }

    planned = test["planned_duration_days"].to_numpy()
    true_bands = [band(s) for s in test["final_score"]]
    model_scores = scores(shipped["delay_days"], shipped["overrun_pct"], planned)
    model_bands = [band(s) for s in model_scores]
    base_bands = [band(s) for s in scores(linear["delay_days"], linear["overrun_pct"], planned)]
    report["risk_class"] = {
        "f1_high": round(float(f1_score(true_bands, model_bands, labels=["high"], average="macro")), 3),
        "f1_high_baseline": round(
            float(f1_score(true_bands, base_bands, labels=["high"], average="macro")), 3
        ),
        "f1_macro": round(float(f1_score(true_bands, model_bands, labels=list(BANDS), average="macro")), 3),
        "confusion_matrix": {
            "labels": list(BANDS),
            "rows_true_cols_predicted": confusion_matrix(
                true_bands, model_bands, labels=list(BANDS)
            ).tolist(),
        },
    }
    report["backtest"] = backtest(test, model_scores)
    delay_true, delay_pred = test["delay_days"].to_numpy(), shipped["delay_days"]
    report["delay_mae_by_elapsed"] = {
        str(s): round(float(mean_absolute_error(delay_true[mask], delay_pred[mask])), 1)
        for s in stage.cat.categories
        if (mask := (stage == s).to_numpy()).any()
    }
    return models, report, test


# --- Export ----------------------------------------------------------------------------------------


def golden(models: dict[str, TargetModels], test: pd.DataFrame) -> list[dict[str, Any]]:
    """Rows the backend must reproduce: raw point and quantile outputs, SHAP values and base value."""
    x = test.sample(GOLDEN_ROWS, random_state=SEED)[list(FEATURES)]
    rows: list[dict[str, Any]] = [{"x": [float(v) for v in row]} for row in x.to_numpy()]
    for target, m in models.items():
        outputs = {w: m.predict(w, x) for w in ("point", "p10", "p90")}
        shap_values, base = m.contributions(x)
        for i, row in enumerate(rows):
            row[target] = {
                **{w: float(outputs[w][i]) for w in outputs},
                "base": float(base[i]),
                "contributions": [float(v) for v in shap_values[i]],
            }
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Train and export the risk model")
    parser.add_argument("--data", type=Path, default=DATA)
    args = parser.parse_args(argv)

    data = pd.read_csv(args.data)
    data_hash = hashlib.sha256(args.data.read_bytes()).hexdigest()
    models, report, test = train_and_evaluate(data)
    train = data[~data.index.isin(test.index)]

    trained_at = datetime.now(UTC).replace(microsecond=0).isoformat()
    model = {
        "format": MODEL_FORMAT,
        "name": "risk",
        "version": VERSION,
        "trained_at": trained_at,
        "features": list(FEATURES),
        "targets": {target: models[target].export() for target in TARGETS},
        "training": {
            "data": "synthetic: ml/data_generator (see ml/data_generator/ASSUMPTIONS.md)",
            "data_sha256": data_hash,
            "projects": int(data.project_id.nunique()),
            "rows": len(data),
        },
        "golden": golden(models, test),
    }
    BACKEND_MODELS.mkdir(parents=True, exist_ok=True)
    model_path = BACKEND_MODELS / f"risk-v{VERSION}.json"
    model_path.write_text(json.dumps(model, separators=(",", ":")), encoding="utf-8")

    report_dir = ML / "models" / f"risk-v{VERSION}"
    report_dir.mkdir(parents=True, exist_ok=True)
    report.update(
        {
            "version": VERSION,
            "trained_at": trained_at,
            "data_sha256": data_hash,
            "split": {
                "train_projects": int(train.project_id.nunique()),
                "test_projects": int(test.project_id.nunique()),
                "train_rows": len(train),
                "test_rows": len(test),
            },
            "model_file": str(model_path.relative_to(ML.parent)).replace("\\", "/"),
            "model_sha256": hashlib.sha256(model_path.read_bytes()).hexdigest(),
        }
    )
    (report_dir / "metrics.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    summary = {k: report[k] for k in ("targets", "risk_class", "backtest", "delay_mae_by_elapsed")}
    print(json.dumps(summary, indent=1)[:9000])
    print(f"Model: {model_path} ({model_path.stat().st_size / 1024:.0f} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
