# SiteSense ML

Training code for SiteSense's AI features:

- **Risk model** (Phase 6; v1.1.0 in Phase 7; v1.2.0 in Phase 10, rain): final delay and cost overrun from weekly project
  snapshots. [Model card](../docs/model-card-risk.md), [ADR 0009](../docs/adr/0009-risk-model-v1.md).
- **Report issue classifier** (Phase 7): category and severity for each sentence of a daily report's
  problems. [Model card](../docs/model-card-report-issues.md),
  [ADR 0010](../docs/adr/0010-report-issue-classifier.md).

> The training data is **synthetic**. Projects are simulated from written-down assumptions
> ([data_generator/ASSUMPTIONS.md](data_generator/ASSUMPTIONS.md)); only the rainfall is real. The
> results show the pipeline works, not that the model is right about real sites.

## Layout

| Path | What |
| --- | --- |
| `data_generator/rainfall.py`, `rainfall.csv` | Real daily rainfall for seven towns (Open-Meteo archive, 2012 to 2025) |
| `data_generator/simulate.py` | The project simulator; writes `data/snapshots.csv` (not committed). `--calibrate` finds the pace that keeps the median project 10% late |
| `data_generator/climate.py` | Writes the monthly rain climate the backend uses (`backend/app/ai/risk/rain_climate.json`) |
| `train.py` | Grouped split, linear baseline, LightGBM, metrics, JSON export to the backend |
| `check_model.py` | CI check: retraining from this commit reproduces the shipped model |
| `models/risk-v1.2.0/metrics.json` | Metrics and settings of the shipped risk model (earlier versions kept for comparison) |
| `rain_sensitivity.py`, `models/risk-v1.2.0/rain-sensitivity.json` | The same pipeline with programmes allowing 75% of usual rain instead of 50%: how much rain's weight depends on that assumption |
| `nlp/` | Report issue classifier: labelling guide, data generator, hand-written test set, training and export |
| `models/report-nlp/` | Classifier metrics, the adoption decision and the metrics of what ships |
| `notebooks/01_explore.ipynb` | Distributions, sanity checks and evaluation (built by `notebooks/build_explore.py`) |
| `tests/` | Simulator, scoring, export and report-issue data tests |

## Run it

```bash
cd ml
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt   # macOS/Linux: .venv/bin/python
.venv/Scripts/python -m data_generator.simulate             # 300 projects, seed 2026
.venv/Scripts/python train.py                               # trains, evaluates, exports
.venv/Scripts/python -m pytest
```

`train.py` writes the model to `backend/app/ai/risk/models/risk-v1.2.0.json` and its metrics to
`models/risk-v1.2.0/metrics.json`. The same seed and code give the same model, byte for byte apart
from the timestamp; `check_model.py` enforces that in CI.

## Changing the model

1. Change the simulator or training code, and the assumptions file if a rule changed.
2. If a feature is added, renamed or redefined, change it in `simulate.py` **and**
   `backend/app/ai/risk/features.py` (tests in both projects compare the lists), and bump the version.
3. If a rule changed how late projects are, re-run `python -m data_generator.simulate --calibrate`
   and set `BASE_PACE` to the value it prints. If the rain climate rule changed, re-run
   `python -m data_generator.climate`.
4. Retrain, read `metrics.json` against the previous version, update the model card, commit both files.

The backend never loads pickles; it scores the exported JSON trees in pure Python (ADR 0009).

## Report issue classifier

```bash
cd ml
.venv/Scripts/python -m nlp.generate                # synthetic train.csv and val.csv (templates held out)
.venv/Scripts/python -m nlp.train_baseline --export # TF-IDF baseline; JSON model for the backend
.venv/Scripts/python -m pip install -r requirements-transformer.txt   # PyTorch (CPU), transformers, ONNX
.venv/Scripts/python -m nlp.train_distilbert        # about an hour on a laptop CPU
.venv/Scripts/python -m nlp.export_onnx             # evidence, ONNX export, backend manifest
```

- `nlp/LABELLING.md` defines the labels. `nlp/data/test_handwritten.csv` is written by hand and is
  **never** used for training or tuning; a test fails if any of its sentences appears in the
  generated data.
- DistilBERT is adopted only if it beats the baseline by about 5 macro-F1 points on that test set
  (it does for category, not for severity; see `models/report-nlp/decision.json`).
- The weights (`models/report-nlp/distilbert/`, `onnx/`) are not committed. The shipped ONNX file
  and tokenizer go to a GitHub Release named in the manifest, and `scripts/fetch_models.py` fetches
  them. A new version needs a new release tag.
- `nlp/rules.py` is copied to `backend/app/ai/nlp/rules.py`; a test checks the two are the same code.
