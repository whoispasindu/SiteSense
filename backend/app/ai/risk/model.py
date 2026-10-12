"""Load the risk model (plain JSON) and score feature vectors in pure Python.

Risk model v2 (``ml/train.py``, ``ml/risk_models.py``) has, for each target (delay days, overrun %):

- a **point model**, either LightGBM trees or a straight line, whichever won on held-out data (the
  line ships unless the trees are clearly better);
- a **likely range**, the 10th to 90th percentile: offsets from the point forecast, linear in the
  planned duration and the planned days still to run.

Nothing is unpickled: loading a joblib/pickle file runs code, so a tampered model file could take
over the server. A JSON file can only ever be data, and it is validated here before use.

Trees: each is a flat list of nodes ``[feature, threshold, left, right, value, count]`` (leaves have
feature -1). At a split, go left when ``x[feature] <= threshold`` (LightGBM's rule for numeric
splits with no missing values); the prediction is the sum of the leaves.

Drivers are **SHAP values**: how much each input moved this forecast away from the average
training snapshot. For trees they are computed exactly with TreeSHAP (Lundberg et al., 2018, the
polynomial-time algorithm), using each node's training count; for a line they are
``coef x (x - mean)``. Either way the base value plus the contributions equals the forecast, and a
test checks them against LightGBM's own SHAP values.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any, TypeGuard

MODELS_DIR = Path(__file__).parent / "models"
MODEL_FORMAT = "sitesense-risk-v2"
CURRENT_VERSION = "2.0.0"
TARGETS = ("delay_days", "overrun_pct")
RANGE_FEATURES = ("planned_duration_days", "remaining_planned_days")
# Hard limits: a model file outside them is refused rather than trusted.
MAX_TREES = 5000
MAX_NODES = 1 << 16


class ModelError(ValueError):
    """The model file is missing or not a valid SiteSense model."""


@dataclass(frozen=True, slots=True)
class Prediction:
    value: float  # the forecast
    low: float  # likely range: 10th percentile (never above the forecast)
    high: float  # 90th percentile (never below it)
    base: float  # the model's average over the training snapshots
    contributions: tuple[float, ...]  # SHAP value per feature; base + sum(contributions) == value


# --- Trees ---------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Tree:
    feature: tuple[int, ...]
    threshold: tuple[float, ...]
    left: tuple[int, ...]
    right: tuple[int, ...]
    value: tuple[float, ...]
    count: tuple[float, ...]

    def leaf(self, x: tuple[float, ...]) -> float:
        node = 0
        while self.feature[node] >= 0:
            node = self.left[node] if x[self.feature[node]] <= self.threshold[node] else self.right[node]
        return self.value[node]

    def expected(self) -> float:
        """The tree's average output over its training rows (leaf values weighted by count)."""
        root = self.count[0]
        return (
            sum(v * c for f, v, c in zip(self.feature, self.value, self.count, strict=True) if f < 0) / root
        )

    def shap(self, x: tuple[float, ...], phi: list[float]) -> None:
        """Add this tree's exact SHAP values for ``x`` to ``phi`` (TreeSHAP, Algorithm 2)."""
        _recurse(self, x, phi, 0, [], 1.0, 1.0, -1)


# A path element: [feature, zero_fraction, one_fraction, weight]. The paths are short (tree depth).
_Path = list[list[float]]


def _extend(path: _Path, zero: float, one: float, feature: int) -> _Path:
    depth = len(path)
    path = [element[:] for element in path] + [[feature, zero, one, 1.0 if depth == 0 else 0.0]]
    for i in range(depth - 1, -1, -1):
        path[i + 1][3] += one * path[i][3] * (i + 1) / (depth + 1)
        path[i][3] = zero * path[i][3] * (depth - i) / (depth + 1)
    return path


def _unwind(path: _Path, index: int) -> _Path:
    depth = len(path) - 1
    one, zero = path[index][2], path[index][1]
    path = [element[:] for element in path]
    next_one = path[depth][3]
    for i in range(depth - 1, -1, -1):
        if one != 0:
            kept = path[i][3]
            path[i][3] = next_one * (depth + 1) / ((i + 1) * one)
            next_one = kept - path[i][3] * zero * (depth - i) / (depth + 1)
        else:
            path[i][3] = path[i][3] * (depth + 1) / (zero * (depth - i))
    for i in range(index, depth):
        path[i][0], path[i][1], path[i][2] = path[i + 1][0], path[i + 1][1], path[i + 1][2]
    return path[:depth]


def _unwound_sum(path: _Path, index: int) -> float:
    depth = len(path) - 1
    one, zero = path[index][2], path[index][1]
    next_one = path[depth][3]
    total = 0.0
    for i in range(depth - 1, -1, -1):
        if one != 0:
            share = next_one * (depth + 1) / ((i + 1) * one)
            total += share
            next_one = path[i][3] - share * zero * (depth - i) / (depth + 1)
        else:
            total += (path[i][3] / zero) / ((depth - i) / (depth + 1))
    return total


def _recurse(
    tree: Tree,
    x: tuple[float, ...],
    phi: list[float],
    node: int,
    parent: _Path,
    zero: float,
    one: float,
    feature: int,
) -> None:
    path = _extend(parent, zero, one, feature)
    split = tree.feature[node]
    if split < 0:
        for i in range(1, len(path)):
            weight = _unwound_sum(path, i)
            phi[int(path[i][0])] += weight * (path[i][2] - path[i][1]) * tree.value[node]
        return
    goes_left = x[split] <= tree.threshold[node]
    hot, cold = (tree.left[node], tree.right[node]) if goes_left else (tree.right[node], tree.left[node])
    incoming_zero = incoming_one = 1.0
    seen = next((i for i, element in enumerate(path) if element[0] == split), None)
    if seen is not None:  # split on this feature higher up: undo it, then redo it here
        incoming_zero, incoming_one = path[seen][1], path[seen][2]
        path = _unwind(path, seen)
    count = tree.count[node]
    _recurse(tree, x, phi, hot, path, incoming_zero * tree.count[hot] / count, incoming_one, split)
    _recurse(tree, x, phi, cold, path, incoming_zero * tree.count[cold] / count, 0.0, split)


@dataclass(frozen=True, slots=True)
class Ensemble:
    trees: tuple[Tree, ...]
    size: int  # number of features

    def predict(self, x: tuple[float, ...]) -> tuple[float, float, tuple[float, ...]]:
        phi = [0.0] * self.size
        for tree in self.trees:
            tree.shap(x, phi)
        value = sum(tree.leaf(x) for tree in self.trees)
        return value, sum(tree.expected() for tree in self.trees), tuple(phi)


# --- Lines ---------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Line:
    intercept: float
    coef: tuple[float, ...]
    mean: tuple[float, ...]

    def value(self, x: tuple[float, ...]) -> float:
        return self.intercept + sum(c * v for c, v in zip(self.coef, x, strict=True))

    def predict(self, x: tuple[float, ...]) -> tuple[float, float, tuple[float, ...]]:
        base = self.intercept + sum(c * m for c, m in zip(self.coef, self.mean, strict=True))
        contributions = tuple(c * (v - m) for c, v, m in zip(self.coef, x, self.mean, strict=True))
        return self.value(x), base, contributions


# --- One target, and the model -------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TargetModel:
    kind: str  # "trees" or "linear"
    point: Ensemble | Line
    low: Line  # offsets from the forecast to its 10th percentile, over RANGE_FEATURES
    high: Line  # and to its 90th

    def predict(self, x: tuple[float, ...], design: tuple[float, ...]) -> Prediction:
        value, base, contributions = self.point.predict(x)
        p10, p90 = value + self.low.value(design), value + self.high.value(design)
        # Separately fitted offsets can cross on unusual projects: the range always holds the forecast.
        return Prediction(value, min(p10, value, p90), max(p10, value, p90), base, contributions)


@dataclass(frozen=True, slots=True)
class RiskModel:
    version: str
    features: tuple[str, ...]
    delay: TargetModel
    overrun: TargetModel
    trained_at: str
    training: dict[str, Any]
    golden: tuple[dict[str, Any], ...]

    def design(self, x: tuple[float, ...]) -> tuple[float, float]:
        """The range's inputs: planned duration, and planned days still to run (none past the end)."""
        planned = x[self.features.index("planned_duration_days")]
        elapsed = x[self.features.index("elapsed_pct")]
        return planned, planned * max(1 - elapsed / 100, 0.0)

    def predict(self, x: tuple[float, ...]) -> tuple[Prediction, Prediction]:
        if len(x) != len(self.features):
            raise ModelError(f"Expected {len(self.features)} features, got {len(x)}.")
        if not all(math.isfinite(v) for v in x):
            raise ModelError("Features must be finite numbers.")
        design = self.design(x)
        return self.delay.predict(x, design), self.overrun.predict(x, design)


# --- Validation ----------------------------------------------------------------------------------


def _number(value: Any) -> TypeGuard[float]:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _tree(raw: Any, n_features: int) -> Tree:
    if not isinstance(raw, list) or not 0 < len(raw) <= MAX_NODES:
        raise ModelError("A tree must be a non-empty list of nodes.")
    columns: list[list[float]] = [[], [], [], [], [], []]
    size = len(raw)
    for index, node in enumerate(raw):
        if not (isinstance(node, list) and len(node) == 6):
            raise ModelError("Each node must be [feature, threshold, left, right, value, count].")
        if not all(_number(n) for n in node):
            raise ModelError("Node fields must be finite numbers.")
        f, t, lo, hi, v, c = node
        f, lo, hi = int(f), int(lo), int(hi)
        if c <= 0:
            raise ModelError("Node counts must be positive.")
        if f == -1:
            lo = hi = -1
        elif not (0 <= f < n_features and index < lo < size and index < hi < size):
            # Children always come after their parent, so a walk always ends at a leaf.
            raise ModelError("A split refers to an unknown feature or node.")
        for column, item in zip(columns, (f, t, lo, hi, v, c), strict=True):
            column.append(item)
    feature, threshold, left, right, value, count = columns
    return Tree(
        tuple(int(f) for f in feature),
        tuple(float(t) for t in threshold),
        tuple(int(lo) for lo in left),
        tuple(int(hi) for hi in right),
        tuple(float(v) for v in value),
        tuple(float(c) for c in count),
    )


def _line(raw: Any, size: int, *, needs_mean: bool) -> Line:
    if not isinstance(raw, dict):
        raise ModelError("A line must be an object.")
    if needs_mean and "mean" not in raw:
        raise ModelError("A point line needs the training means (the SHAP baseline).")
    intercept = raw.get("intercept")
    if not _number(intercept):
        raise ModelError("A line needs a finite intercept.")
    parts: dict[str, list[float]] = {}
    for name, values in (("coef", raw.get("coef")), ("mean", raw.get("mean", [0.0] * size))):
        if not (isinstance(values, list) and len(values) == size and all(_number(v) for v in values)):
            raise ModelError(f"A line's {name} must be {size} finite numbers.")
        parts[name] = [float(v) for v in values]
    return Line(float(intercept), tuple(parts["coef"]), tuple(parts["mean"]))


def _target(name: str, raw: Any, n_features: int) -> TargetModel:
    if not isinstance(raw, dict):
        raise ModelError(f"{name}: not an object.")
    kind = raw.get("kind")
    point_raw = raw.get("point")
    point: Ensemble | Line
    if kind == "trees":
        trees = point_raw.get("trees") if isinstance(point_raw, dict) else None
        if not isinstance(trees, list) or not 0 < len(trees) <= MAX_TREES:
            raise ModelError(f"{name}: expected a list of trees.")
        point = Ensemble(tuple(_tree(t, n_features) for t in trees), n_features)
    elif kind == "linear":
        point = _line(point_raw, n_features, needs_mean=True)
    else:
        raise ModelError(f"{name}: unknown model kind.")
    span = raw.get("range")
    if not isinstance(span, dict) or tuple(span.get("features", ())) != RANGE_FEATURES:
        raise ModelError(f"{name}: the likely range must be over {', '.join(RANGE_FEATURES)}.")
    size = len(RANGE_FEATURES)
    return TargetModel(
        kind,
        point,
        _line(span.get("p10"), size, needs_mean=False),
        _line(span.get("p90"), size, needs_mean=False),
    )


def parse(document: Any) -> RiskModel:
    """Validate a decoded model document and build the scorer."""
    if not isinstance(document, dict) or document.get("format") != MODEL_FORMAT:
        raise ModelError("Not a SiteSense risk model.")
    features = document.get("features")
    if not (isinstance(features, list) and features and all(isinstance(f, str) for f in features)):
        raise ModelError("The model must list its features.")
    if not {"planned_duration_days", "elapsed_pct"} <= set(features):
        raise ModelError("The likely range needs the planned duration and time elapsed.")
    targets = document.get("targets")
    if not isinstance(targets, dict) or set(targets) != set(TARGETS):
        raise ModelError("The model must predict delay_days and overrun_pct.")
    parsed = {name: _target(name, targets[name], len(features)) for name in TARGETS}
    golden = document.get("golden", [])
    return RiskModel(
        version=str(document.get("version", "")),
        features=tuple(features),
        delay=parsed["delay_days"],
        overrun=parsed["overrun_pct"],
        trained_at=str(document.get("trained_at", "")),
        training=dict(document.get("training", {})),
        golden=tuple(golden) if isinstance(golden, list) else (),
    )


def load(path: Path) -> RiskModel:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ModelError(f"Cannot read the risk model at {path.name}: {exc}") from exc
    return parse(document)


@cache
def current() -> RiskModel:
    """The model shipped with this build (loaded once per process)."""
    return load(MODELS_DIR / f"risk-v{CURRENT_VERSION}.json")
