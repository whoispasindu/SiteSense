# SiteSense ML

Training code for SiteSense's AI features. Phase 6 adds **risk model v1**: final delay and cost overrun
from weekly project snapshots. See the [model card](../docs/model-card-risk.md) and
[ADR 0009](../docs/adr/0009-risk-model-v1.md).

> The training data is **synthetic**. Projects are simulated from written-down assumptions
> ([data_generator/ASSUMPTIONS.md](data_generator/ASSUMPTIONS.md)); only the rainfall is real. The
> results show the pipeline works, not that the model is right about real sites.

## Layout

| Path | What |
| --- | --- |
| `data_generator/rainfall.py`, `rainfall.csv` | Real daily rainfall for seven towns (Open-Meteo archive, 2012 to 2025) |
| `data_generator/simulate.py` | The project simulator; writes `data/snapshots.csv` (not committed) |
| `train.py` | Grouped split, linear baseline, LightGBM, metrics, JSON export to the backend |
| `check_model.py` | CI check: retraining from this commit reproduces the shipped model |
| `models/risk-v1.0.0/metrics.json` | Metrics and settings of the shipped model |
| `notebooks/01_explore.ipynb` | Distributions, sanity checks and evaluation (built by `notebooks/build_explore.py`) |
| `tests/` | Simulator, scoring and export tests |

## Run it

```bash
cd ml
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt   # macOS/Linux: .venv/bin/python
.venv/Scripts/python -m data_generator.simulate             # 300 projects, seed 2026
.venv/Scripts/python train.py                               # trains, evaluates, exports
.venv/Scripts/python -m pytest
```

`train.py` writes the model to `backend/app/ai/risk/models/risk-v1.0.0.json` and its metrics to
`models/risk-v1.0.0/metrics.json`. The same seed and code give the same model, byte for byte apart
from the timestamp; `check_model.py` enforces that in CI.

## Changing the model

1. Change the simulator or training code, and the assumptions file if a rule changed.
2. If a feature is added, renamed or redefined, change it in `simulate.py` **and**
   `backend/app/ai/risk/features.py` (tests in both projects compare the lists), and bump the version.
3. Retrain, read `metrics.json` against the previous version, update the model card, commit both files.

The backend never loads pickles; it scores the exported JSON trees in pure Python (ADR 0009).
