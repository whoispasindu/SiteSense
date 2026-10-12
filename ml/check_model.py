"""CI check: retraining from the committed code and data reproduces the shipped model.

    python check_model.py

Compares the freshly trained model's predictions on the golden rows with the committed model file.
A small tolerance allows for floating-point differences between platforms.
"""

import json
import subprocess
import sys
from pathlib import Path

MODEL = Path(__file__).parent.parent / "backend" / "app" / "ai" / "risk" / "models" / "risk-v2.0.0.json"
METRICS = Path(__file__).parent / "models" / "risk-v2.0.0" / "metrics.json"
TOLERANCE = 0.01  # days / percentage points


SUPPLIER_MODEL = MODEL.parents[2] / "supplier" / "models" / "supplier-v1.0.0.json"
SUPPLIER_METRICS = Path(__file__).parent / "models" / "supplier-v1.0.0" / "metrics.json"


def check_supplier() -> list[str]:
    """The supplier on-time model (BR-12): same data, the same kind shipped, the same predictions."""
    committed_text = SUPPLIER_MODEL.read_text(encoding="utf-8")
    metrics_text = SUPPLIER_METRICS.read_text(encoding="utf-8")
    committed = json.loads(committed_text)
    for step in (["-m", "data_generator.deliveries"], ["train_supplier.py"]):
        subprocess.run([sys.executable, *step], check=True, cwd=Path(__file__).parent)  # noqa: S603
    fresh = json.loads(SUPPLIER_MODEL.read_text(encoding="utf-8"))
    SUPPLIER_MODEL.write_text(committed_text, encoding="utf-8")
    SUPPLIER_METRICS.write_text(metrics_text, encoding="utf-8")
    problems = []
    if fresh["training"]["data_sha256"] != committed["training"]["data_sha256"]:
        problems.append("supplier: the simulated deliveries differ from the shipped model's")
    if fresh["kind"] != committed["kind"]:
        problems.append(f"supplier: shipped {committed['kind']}, retraining chose {fresh['kind']}")
    for old, new in zip(committed["golden"], fresh["golden"], strict=True):
        if abs(old["p"] - new["p"]) > 1e-6:
            problems.append(f"supplier: shipped {old['p']:.4f}, retrained {new['p']:.4f}")
    return problems


def main() -> int:
    committed_text, metrics_text = MODEL.read_text(encoding="utf-8"), METRICS.read_text(encoding="utf-8")
    committed = json.loads(committed_text)
    for step in (["-m", "data_generator.simulate"], ["train.py"]):
        subprocess.run([sys.executable, *step], check=True, cwd=Path(__file__).parent)  # noqa: S603
    fresh = json.loads(MODEL.read_text(encoding="utf-8"))
    MODEL.write_text(committed_text, encoding="utf-8")  # leave the working tree as it was
    METRICS.write_text(metrics_text, encoding="utf-8")

    problems = []
    if fresh["training"]["data_sha256"] != committed["training"]["data_sha256"]:
        problems.append("the simulated training data differs from the data the shipped model was trained on")
    for target in ("delay_days", "overrun_pct"):
        if fresh["targets"][target]["kind"] != committed["targets"][target]["kind"]:
            problems.append(
                f"{target}: shipped a {committed['targets'][target]['kind']} model, retraining chose another"
            )
    for old, new in zip(committed["golden"], fresh["golden"], strict=True):
        for target in ("delay_days", "overrun_pct"):
            for which in ("point", "p10", "p90"):
                a, b = old[target][which], new[target][which]
                if abs(a - b) > TOLERANCE:
                    problems.append(f"{target} {which}: shipped {a:.3f}, retrained {b:.3f}")
    problems += check_supplier()
    if problems:
        print("The shipped models are not reproducible from this commit:", *problems[:10], sep="\n  ")
        print("Retrain (python train.py) and commit the new model file, or revert the change.")
        return 1
    print("Retraining reproduces the shipped models.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
