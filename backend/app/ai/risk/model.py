"""Load the risk model (JSON trees) and score feature vectors in pure Python.

The model is trained in ``ml/train.py`` with LightGBM and exported as plain JSON: for each target a
list of trees, each a flat list of nodes ``[feature, threshold, left, right, value]`` (leaves have
feature -1). Nothing is unpickled: loading a joblib/pickle file runs code, so a tampered model
file could take over the server. A JSON file can only ever be data, and it is validated here
before use.

Scoring walks each tree: at a split, go left when ``x[feature] <= threshold`` (LightGBM's rule
for numeric splits with no missing values). The prediction is the sum of the leaves.

Drivers: on the way down, the change in node value at each split is credited to that split's
feature (path attribution). Contributions plus the base value add up exactly to the prediction,
so the screen can show how much each factor moved the forecast. It is a simpler attribution than
SHAP (planned for risk model v2) and is labelled as approximate.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any

MODELS_DIR = Path(__file__).parent / "models"
MODEL_FORMAT = "sitesense-gbdt-v1"
CURRENT_VERSION = "1.1.0"
# Hard limits: a model file outside them is refused rather than trusted.
MAX_TREES = 5000
MAX_NODES = 1 << 16


class ModelError(ValueError):
    """The model file is missing or not a valid SiteSense model."""


@dataclass(frozen=True, slots=True)
class Tree:
    feature: tuple[int, ...]
    threshold: tuple[float, ...]
    left: tuple[int, ...]
    right: tuple[int, ...]
    value: tuple[float, ...]


@dataclass(frozen=True, slots=True)
class Prediction:
    value: float
    base: float  # the model's expected value before any feature is considered
    contributions: tuple[float, ...]  # one per feature; base + sum(contributions) == value


@dataclass(frozen=True, slots=True)
class Ensemble:
    trees: tuple[Tree, ...]

    def predict(self, x: tuple[float, ...]) -> Prediction:
        total = 0.0
        base = 0.0
        contributions = [0.0] * _feature_count(self)
        for tree in self.trees:
            node = 0
            base += tree.value[0]
            while tree.feature[node] >= 0:
                f = tree.feature[node]
                child = tree.left[node] if x[f] <= tree.threshold[node] else tree.right[node]
                contributions[f] += tree.value[child] - tree.value[node]
                node = child
            total += tree.value[node]
        return Prediction(total, base, tuple(contributions))


def _feature_count(ensemble: Ensemble) -> int:
    return max((max(t.feature) for t in ensemble.trees), default=-1) + 1


@dataclass(frozen=True, slots=True)
class RiskModel:
    version: str
    features: tuple[str, ...]
    delay: Ensemble
    overrun: Ensemble
    trained_at: str
    training: dict[str, Any]
    golden: tuple[dict[str, Any], ...]

    def predict(self, x: tuple[float, ...]) -> tuple[Prediction, Prediction]:
        if len(x) != len(self.features):
            raise ModelError(f"Expected {len(self.features)} features, got {len(x)}.")
        if not all(math.isfinite(v) for v in x):
            raise ModelError("Features must be finite numbers.")
        delay, overrun = self.delay.predict(x), self.overrun.predict(x)
        # The per-feature arrays must cover every feature, even ones no tree splits on.
        pad = len(self.features)
        return _padded(delay, pad), _padded(overrun, pad)


def _padded(prediction: Prediction, size: int) -> Prediction:
    extra = size - len(prediction.contributions)
    if extra <= 0:
        return prediction
    return Prediction(prediction.value, prediction.base, prediction.contributions + (0.0,) * extra)


def _tree(raw: Any, n_features: int) -> Tree:
    if not isinstance(raw, list) or not 0 < len(raw) <= MAX_NODES:
        raise ModelError("A tree must be a non-empty list of nodes.")
    feature: list[int] = []
    threshold: list[float] = []
    left: list[int] = []
    right: list[int] = []
    value: list[float] = []
    size = len(raw)
    for index, node in enumerate(raw):
        if not (isinstance(node, list) and len(node) == 5):
            raise ModelError("Each node must be [feature, threshold, left, right, value].")
        f, t, lo, hi, v = node
        if not all(isinstance(n, (int, float)) and not isinstance(n, bool) for n in node):
            raise ModelError("Node fields must be numbers.")
        if not (math.isfinite(t) and math.isfinite(v)):
            raise ModelError("Thresholds and values must be finite.")
        f, lo, hi = int(f), int(lo), int(hi)
        if f == -1:
            lo = hi = -1
        elif not (0 <= f < n_features and index < lo < size and index < hi < size):
            # Children always come after their parent, so a walk always ends at a leaf.
            raise ModelError("A split refers to an unknown feature or node.")
        feature.append(f)
        threshold.append(float(t))
        left.append(lo)
        right.append(hi)
        value.append(float(v))
    return Tree(tuple(feature), tuple(threshold), tuple(left), tuple(right), tuple(value))


def parse(document: Any) -> RiskModel:
    """Validate a decoded model document and build the scorer."""
    if not isinstance(document, dict) or document.get("format") != MODEL_FORMAT:
        raise ModelError("Not a SiteSense risk model.")
    features = document.get("features")
    if not (isinstance(features, list) and features and all(isinstance(f, str) for f in features)):
        raise ModelError("The model must list its features.")
    targets = document.get("targets")
    if not isinstance(targets, dict) or set(targets) != {"delay_days", "overrun_pct"}:
        raise ModelError("The model must predict delay_days and overrun_pct.")
    ensembles = {}
    for name, target in targets.items():
        trees = target.get("trees") if isinstance(target, dict) else None
        if not isinstance(trees, list) or not 0 < len(trees) <= MAX_TREES:
            raise ModelError(f"{name}: expected a list of trees.")
        ensembles[name] = Ensemble(tuple(_tree(t, len(features)) for t in trees))
    golden = document.get("golden", [])
    return RiskModel(
        version=str(document.get("version", "")),
        features=tuple(features),
        delay=ensembles["delay_days"],
        overrun=ensembles["overrun_pct"],
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
