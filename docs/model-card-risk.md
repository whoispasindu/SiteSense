# Model card: delay and cost-overrun risk, v1.0.0

| | |
| --- | --- |
| Model | Two gradient-boosted tree ensembles (LightGBM 4.7): final **delay in days** and final **cost overrun in %** |
| Version | 1.0.0, trained 2026-10-10. Model file: `backend/app/ai/risk/models/risk-v1.0.0.json` |
| Training code | `ml/data_generator/simulate.py`, `ml/train.py`. Exploration: `ml/notebooks/01_explore.ipynb` |
| Training data | **Synthetic**: 300 simulated projects, 18,329 weekly snapshots, real Open-Meteo rainfall. See [Data](#data) |
| Owner | SiteSense project. Retrained weekly once real completed projects exist (guide, section 4.6) |

## What it is for

The model ranks a contractor's open projects by the risk of finishing late or over budget, so a project
manager knows where to look first. It produces:

- **A forecast** of delay at completion and cost overrun at completion.
- **A score** from 0 to 100: the worse of the two, where 25% of the planned duration late or 20% over
  budget scores 100.
- **A band** (BR-10): 70 or more is High and alerts the project manager, 40 to 69 is Medium, under 40 is Low.
- **Drivers**: how much each input moved the forecast compared with a typical project at the same stage.

It **suggests**; people decide. A score never changes anything in a project by itself.

**Not for:** judging individual workers (no feature describes a person), contractual claims, or
projects unlike the training mix (very small jobs, civil infrastructure, design-and-build).

## Inputs

Built from live app data each day by `backend/app/ai/risk/features.py`, with the same meaning as in the
simulator. When the app has no data for an input it takes a neutral value and the forecast lists the gap.

| Feature | Source | Neutral when missing |
| --- | --- | --- |
| `elapsed_pct`, `planned_duration_days` | Project dates | |
| `progress_gap_pct`, `progress_rate_trend` | Programme tasks and progress snapshots | 0 (no programme) |
| `late_deliveries_count`, `avg_lateness_days` | Purchase orders and deliveries | 0 |
| `rain_days_next_14` | 14-day forecast cache (heavy rain is 10 mm or more, BR-06) | 0 (scaled if fewer days are cached) |
| `budget_variance_pct` | Committed requests against the budgeted value of the same quantities | 0 (nothing committed) |
| `crew_vs_plan_pct` | Daily report crews against the project's planned crew | 0 (no planned crew set) |
| `missing_reports_14` | Daily reports (BR-07) | |
| `contract_value_m`, `type_*` | Project | |

Not yet used (they arrive in later phases): open issues from report NLP (Phase 7) and variation
counts (Phase 8).

## Method

- **Baseline:** linear regression on the same features.
- **Main model:** LightGBM with monotone constraints where the direction is known. For example,
  falling further behind plan can only raise the delay forecast; more late deliveries can only raise
  both forecasts. Tree size and rounds were chosen by 5-fold cross-validation **grouped by project**.
- **Split:** 240 projects for training, 60 held out, split by project so no project's weeks appear on
  both sides.
- **Export:** trees are exported as JSON and scored by a pure-Python evaluator in the backend; no
  pickle files are loaded (see ADR 0009). Golden predictions in the model file prove the evaluator
  matches LightGBM exactly, and CI checks that retraining reproduces the shipped file.

## Results on the 60 held-out projects

| Target | Model | MAE | RMSE | R² |
| --- | --- | --- | --- | --- |
| Delay (days) | LightGBM | **19.7** | **29.3** | **0.58** |
| Delay (days) | Linear baseline | 25.6 | 34.8 | 0.41 |
| Overrun (%) | LightGBM | **5.7** | **7.9** | **0.20** |
| Overrun (%) | Linear baseline | 5.7 | 8.0 | 0.16 |

- **High band:** F1 0.60 (baseline 0.45); macro F1 across the three bands 0.59.
- **Getting better as a project runs:** delay MAE is 29 days in the first quarter and 13 days in the last.
- **Backtest:** of 16 held-out projects that ended High, 15 were flagged High at some point, at a
  median of 54% of the planned duration, 28 weeks before the planned end. 3 of the 28 projects that
  ended Low were flagged High at some point (false alarms).
- **What the delay model leans on most** (share of gain): progress gap 34%, time elapsed 20%,
  planned duration 19%, contract size 11%, delivery lateness 5%.

## Limitations

- **Synthetic data.** The model has learnt the simulator's rules
  ([ASSUMPTIONS.md](../ml/data_generator/ASSUMPTIONS.md)), not real projects. These numbers show the
  pipeline works; they do not show it is right about real sites. Validating the assumptions with a
  contractor's past projects comes before trusting it.
- **Overrun is weak** (R² 0.20). Most overrun in the simulation comes from time-related overheads and
  variations, which the app does not record yet.
- **Drivers are approximate.** They use path attribution through the trees, a simpler method than
  SHAP (planned for v2). Each driver is measured against the average training project at the same
  point, so "4 points behind" can lower a forecast if typical projects are further behind by then.
  The screen says so.
- **No ranges yet.** Likely ranges (quantile models) arrive with risk model v2 (Phase 10).

## Responsible use

- Every forecast shows its drivers, the inputs it was missing, the model version and the word
  "estimate".
- Scores are about projects, never people.
- Only project managers and quantity surveyors see risk (`risk:read`), on their own sites.
- High risk alerts the PM once when a project *enters* High, not every day it stays there.

## Data

- **Synthetic projects:** `ml/data_generator/simulate.py` (seed 2026, 300 projects). The
  assumptions and their sources are in `ASSUMPTIONS.md`. The generated file (`ml/data/`) is not
  committed; its SHA-256 is recorded in the model file and in `metrics.json`.
- **Rainfall:** daily precipitation for seven Sri Lankan towns, 2012 to 2025, from the Open-Meteo
  archive API (free, no key; CC BY 4.0). Committed as `ml/data_generator/rainfall.csv`.
- **No personal data** is used anywhere in training.
