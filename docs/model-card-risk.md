# Model card: delay and cost-overrun risk, v1.2.0

| | |
| --- | --- |
| Model | Two gradient-boosted tree ensembles (LightGBM 4.7): final **delay in days** and final **cost overrun in %** |
| Version | 1.2.0, trained 2026-10-11. Model file: `backend/app/ai/risk/models/risk-v1.2.0.json`. See [Changes](#changes) |
| Training code | `ml/data_generator/simulate.py`, `ml/train.py`. Exploration: `ml/notebooks/01_explore.ipynb` |
| Training data | **Synthetic**: 300 simulated projects, 18,153 weekly snapshots, real Open-Meteo rainfall. Rain's effect rests on an **assumed** allowance; see [Rain](#rain-an-assumption-not-measured-data) |
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
| `wet_days_ahead` (1.2) | The site's rain climate: for the nearest of seven towns, the share of heavy-rain days in each month (Open-Meteo, 2012 to 2025, `backend/app/ai/risk/rain_climate.json`), summed over the working days from tomorrow to the planned end, at least the next 28 days. Computed locally; nothing is fetched | Sri Lanka's average climate (site without coordinates) |
| `budget_variance_pct` | Committed requests against the budgeted value of the same quantities | 0 (nothing committed) |
| `crew_vs_plan_pct` | Daily report crews against the project's planned crew | 0 (no planned crew set) |
| `missing_reports_14` | Daily reports (BR-07) | |
| `issues_material_14`, `issues_safety_14`, `issues_design_14` | Issues confirmed by the author in daily reports filed in the last 14 days ([report classifier](model-card-report-issues.md)). Suggestions that were not confirmed never count | 0 |
| `contract_value_m`, `type_*` | Project | |

Not yet used: variation counts (Phase 8).

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
| Delay (days) | LightGBM | **19.1** | **25.5** | **0.65** |
| Delay (days) | Linear baseline | 22.6 | 29.1 | 0.54 |
| Overrun (%) | LightGBM | 4.8 | 6.2 | 0.22 |
| Overrun (%) | Linear baseline | **4.7** | **6.1** | **0.27** |

- **High band:** F1 0.57 (baseline 0.59); macro F1 across the three bands 0.58.
- **Getting better as a project runs:** delay MAE is 27 days in the first quarter and 13 days in the last.
- **Backtest:** of 23 held-out projects that ended High, 22 were flagged High at some point, at a
  median of 52% of the planned duration, 30 weeks before the planned end. 1 of the 22 projects that
  ended Low was flagged High at some point (a false alarm).
- **What the delay model leans on most** (share of gain): progress gap 36%, time elapsed 19%, planned
  duration 13%, contract size 13%, **wet season ahead 12%**, delivery lateness 3%.
- **The linear baseline does slightly better on overrun and on the High band** in this run. With 60
  test projects the difference is within noise, and the trees keep the monotone constraints and the
  drivers. Risk model v2 (later in Phase 10) revisits the overrun model.

These are not directly comparable with v1.1's results: the rain change gives a different simulated
set (23 of the 60 test projects end High, against 16). The comparison that isolates the change is
below.

## Rain: an assumption, not measured data

In v1.1 rain held 0.0% of the delay model's gain. The model was right, given the simulator: it
assumed programmes allow for all of a town's usual rain, so only wetter-than-normal weeks slowed work,
and over a project that evened out. Surveys of Sri Lankan building projects rank rainy weather as a
leading cause of delay, which suggests the opposite. Version 1.2 changes the simulator
([ASSUMPTIONS.md](../ml/data_generator/ASSUMPTIONS.md#rain-risk-model-12), issue
[#27](https://github.com/whoispasindu/SiteSense/issues/27)):

- **`RAIN_ALLOWANCE = 0.5`: programmes allow for half of the usual rain loss for the month.** This is
  an **assumption chosen by the project owner, not measured data.** It is a named simulator parameter
  and will be replaced with contractor figures when they exist.
- Rain intensity matters (2–10 mm loses 10% of a day, 10–25 mm 45%, 25 mm or more 80%), a quarter of
  the day after heavy rain is lost too, and earthworks suffer more than a closed-in building.
- The base pace is recalibrated so the median project is still 10% late, as in v1. Rain changes
  **what explains** delay, not how late projects are.
- A new input, `wet_days_ahead`, gives the model the season still to come. The 14-day forecast stays
  small (0.5%): two weeks of weather barely move a final delay.

**Same data, with and without `wet_days_ahead`:** delay MAE 20.1 to 19.1 days, R² 0.61 to 0.65, High
F1 0.54 to 0.57. High projects are flagged earlier, at a median of 52% of the planned duration
instead of 58% (30 weeks before the planned end, instead of 27), with 1 false alarm instead of 0.

**Sensitivity to the assumption** (`ml/rain_sensitivity.py`, `ml/models/risk-v1.2.0/rain-sensitivity.json`).
The whole pipeline run again with programmes allowing three quarters of the usual rain, with the pace
recalibrated (1.046 instead of 1.096):

| Allowance | Rain's share of delay gain | Delay MAE | High F1 | Final bands L / M / H |
| --- | --- | --- | --- | --- |
| **0.5 (shipped)** | **12.7%** (wet season 12.2, forecast 0.5) | 19.1 | 0.57 | 40% / 31% / 29% |
| 0.75 | 8.3% (8.1, 0.2) | 18.4 | 0.58 | 41% / 33% / 25% |

So rain's weight depends on the assumption (a third less at 0.75) but does not vanish. In the demo
data, the wet season ahead is now the largest driver for the two wet-zone projects (Galle and
Colombo), and lowers the forecast for the Kandy project, whose remaining programme is drier.

## Changes

**1.2.0 (Phase 10, issue #27).** Rain (above): the simulator's rain rule, a recalibrated pace, and
the new `wet_days_ahead` input (monotone: more wet days ahead can only raise either forecast).

**1.1.0 (Phase 7).** Adds the three report-issue counts. Their rules in the simulator are in
`ASSUMPTIONS.md`: material delays follow overdue deliveries, safety issues follow poor site
management, design issues follow variations. They are drawn from a separate random stream, so the
projects, outcomes and every other input are identical to v1.0, and the two versions compare like for
like. Monotone constraints: more issues can only raise a forecast.

The gain is small. In the simulation the issues are noisy symptoms of things the model already sees
(late deliveries, missed reports, the progress gap), so they carry little extra signal: design
issues hold 2% of the overrun model's gain, and the delay model barely uses any of them (0.1%).
Against v1.0 on the same held-out projects: delay MAE 19.7 to 19.8 days, overrun R² 0.20 to 0.23,
High F1 0.60 to 0.61, false alarms 3 to 1 of 28. With 60 test projects, small differences like these
are not strong evidence either way. They are included because they are what a site
records first, and real issues may carry more than simulated ones; real data will tell.

## Limitations

- **Synthetic data.** The model has learnt the simulator's rules
  ([ASSUMPTIONS.md](../ml/data_generator/ASSUMPTIONS.md)), not real projects. These numbers show the
  pipeline works; they do not show it is right about real sites. Validating the assumptions with a
  contractor's past projects comes before trusting it.
- **Overrun is weak** (R² 0.23). Most overrun in the simulation comes from time-related overheads and
  variations, which the app does not record yet.
- **Drivers are approximate.** They use path attribution through the trees, a simpler method than
  SHAP (planned for v2). Each driver is measured against the average training project at the same
  point, so "4 points behind" can lower a forecast if typical projects are further behind by then.
  The screen says so.
- **No ranges yet.** Likely ranges (quantile models) arrive with risk model v2 (Phase 10).
- **Rain's weight is assumed.** It follows from `RAIN_ALLOWANCE`, which no contractor has confirmed
  (see [Rain](#rain-an-assumption-not-measured-data) for how much it matters). The climate comes from
  the nearest of seven towns, which is coarse for sites far from all of them (the hill country east
  of Kandy, the north-west).
- Stopped working days (BR-11) reach the model through the progress gap.

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
  archive API (free, no key; CC BY 4.0). Committed as `ml/data_generator/rainfall.csv`. The monthly
  climate the app uses is derived from it (`python -m data_generator.climate`); a test checks the
  backend's copy matches.
- **No personal data** is used anywhere in training.
