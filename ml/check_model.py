"""CI check: retraining from the committed code and data reproduces the shipped model.

    python check_model.py

Compares the freshly trained model's predictions on the golden rows with the committed model file.
A small tolerance allows for floating-point differences between platforms.
"""

import json
import subprocess
import sys
from pathlib import Path

MODEL = Path(__file__).parent.parent / "backend" / "app" / "ai" / "risk" / "models" / "risk-v1.1.0.json"
METRICS = Path(__file__).parent / "models" / "risk-v1.1.0" / "metrics.json"
TOLERANCE = 0.01  # days / percentage points


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
    for old, new in zip(committed["golden"], fresh["golden"], strict=True):
        for target in ("delay_days", "overrun_pct"):
            if abs(old[target] - new[target]) > TOLERANCE:
                problems.append(f"{target}: shipped {old[target]:.3f}, retrained {new[target]:.3f}")
    if problems:
        print("The shipped risk model is not reproducible from this commit:", *problems[:10], sep="\n  ")
        print("Retrain (python train.py) and commit the new model file, or revert the change.")
        return 1
    print("Retraining reproduces the shipped model.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
