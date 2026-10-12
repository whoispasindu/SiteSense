# Model card: delay and cost-overrun risk, v2.0.0

| | |
| --- | --- |
| Model | Final **delay in days**: gradient-boosted trees (LightGBM 4.7). Final **cost overrun in %**: a **straight line** (sign-constrained least squares), because the trees were not clearly better. Each forecast comes with a **likely range** (10th to 90th percentile) |
| Version | 2.0.0, trained 2026-10-12. Model file: `backend/app/ai/risk/models/risk-v2.0.0.json`. See [Changes](#changes) |
| Training code | `ml/data_generator/simulate.py`, `ml/risk_models.py`, `ml/train.py`. Exploration: `ml/notebooks/01_explore.ipynb` |
| Training data | **Synthetic**: 300 simulated projects, 18,153 weekly snapshots, real Open-Meteo rainfall. Rain's effect rests on an **assumed** allowance; see [Rain](#rain-an-assumption-not-measured-data) |
| Owner | SiteSense project. Retrained weekly once real completed projects exist (guide, section 4.6) |

## What it is for

The model ranks a contractor's open projects by the risk of finishing late or over budget, so a project
manager knows where to look first. It produces:

- **A forecast** of delay at completion and cost overrun at completion, **always with its likely range**:
  8 in 10 outcomes should fall inside it. The app never shows one without the other.
- **A score** from 0 to 100: the worse of the two, where 25% of the planned duration late or 20% over
  budget scores 100. The score's range is the score at the two ends of the forecast ranges.
- **A band** (BR-10): 70 or more is High and alerts the project manager, 40 to 69 is Medium, under 40 is Low.
- **Drivers**: SHAP values, how much each input moved this forecast away from the average project
  snapshot the model learnt from.

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

**Not used, on purpose: schedule features from the programme** (the critical-path slip of Phase 9).
The guide suggests them, but the simulator has no task network, so it cannot produce the slip the way
the app computes it. A feature whose training meaning differs from its live meaning would teach the
model something false. The progress gap and its trend carry the same information in the simulation,
and stopped working days (BR-11) reach the model through them. Variation counts are not used yet
either (Phase 8 records them; the simulator does not show them to the model).

## Method

- **Two families per target.** Gradient-boosted trees (LightGBM), tuned by 5-fold cross-validation
  **grouped by project**, and a straight line (least squares). Both have the same **sign
  constraints** where the direction is known: falling further behind can only raise the delay
  forecast; more late deliveries, more wet days ahead, or a smaller crew can only raise either
  forecast. So no recovery action in the what-if planner can make a forecast worse.
- **Which ships.** The trees ship only if they are **clearly** better: the 95% interval, from
  resampling whole projects, for the difference in their cross-validated errors must lie entirely in
  the trees' favour. When the two match, or the line wins, the simpler line ships. The same rule is
  used for the supplier model.
- **Likely ranges.** Quantile regression of the shipped model's out-of-fold errors on the planned
  duration and the planned days still to run, for the 10th and 90th percentiles. The range is an
  offset around the forecast, so it moves with it. (LightGBM's quantile objective cannot take the
  monotone constraints, so quantile trees could not promise that.) Where the two offsets would cross,
  the range still contains the forecast.
- **Drivers.** Exact SHAP values: TreeSHAP for the trees, `coefficient × (value − average)` for the
  line. The backend computes them in pure Python; a test checks them against LightGBM's own, and
  another against Shapley values computed by brute force on a small tree.
- **Split:** 240 projects for training, 60 held out, split by project so no project's weeks appear on
  both sides.
- **Export:** plain JSON scored by a pure-Python evaluator in the backend; no pickle files are loaded
  (see ADR 0009). Golden rows in the model file record forecasts, ranges and SHAP values, and CI checks
  that retraining reproduces the shipped file.

## Results on the 60 held-out projects

| Target | Model | MAE | RMSE | R² | Ships |
| --- | --- | --- | --- | --- | --- |
| Delay (days) | Trees | **19.1** | **25.5** | **0.65** | yes |
| Delay (days) | Straight line | 22.9 | 29.5 | 0.53 | |
| Overrun (%) | Trees | 4.7 | 6.2 | 0.24 | |
| Overrun (%) | Straight line | **4.7** | **6.1** | **0.27** | **yes** |

**The choice, on cross-validation within the 240 training projects** (mean absolute error, trees minus
line, with its 95% interval):

| Target | Trees | Line | Difference | Decision |
| --- | --- | --- | --- | --- |
| Delay | 18.97 days | 22.67 days | −3.70 (−4.68 to −2.71) | Trees clearly better: **trees ship** |
| Overrun | 4.69% | 4.75% | −0.06 (−0.21 to +0.10) | Not clearly better: **the line ships** |

On the held-out projects the line is also slightly better for overrun, so the result does not hinge on
the split. Shipping it raised the High band's F1 from 0.57 (all trees) to 0.60.

**Likely ranges** (how often the outcome fell inside, aiming for 0.8):

| Target | Overall | First quarter | 25–50% | 50–75% | Last quarter | Past the planned end | Average width |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Delay | 0.78 | 0.76 | 0.79 | 0.80 | 0.80 | 0.76 | 60 days |
| Overrun | 0.80 | 0.80 | 0.80 | 0.79 | 0.82 | 0.76 | 14.6 points |

- **High band:** F1 0.60 (all-line baseline 0.58); macro F1 across the three bands 0.59.
- **Getting better as a project runs:** delay MAE is 27 days in the first quarter and 13 days in the last.
- **Backtest** (how early would a real delay have been flagged?): all 23 held-out projects that ended
  High were flagged High at some point, at a median of 41% of the planned duration, 36 weeks before the
  planned end. 2 of the 22 projects that ended Low were flagged High at some point (false alarms).
- **What the forecasts lean on** (share of the mean absolute SHAP value): delay: progress gap 37%,
  time elapsed 18%, **wet season ahead 14%**, contract size 7%, planned duration 7%, delivery lateness
  6%, crew 4%. Overrun: committed cost against budget 28%, progress gap 21%, design issues 9%, wet
  season ahead 9%, late deliveries 6%.

## Rain: an assumption, not measured data

In v1.1 rain held 0.0% of the delay model's gain. The model was right, given the simulator: it
assumed programmes allow for all of a town's usual rain, so only wetter-than-normal weeks slowed work,
and over a project that evened out. Surveys of Sri Lankan building projects rank rainy weather as a
leading cause of delay, which suggests the opposite. Version 1.2 changed the simulator
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
  small: two weeks of weather barely move a final delay.

**Same data, with and without `wet_days_ahead`** (1.2, trees for both targets): delay MAE 20.1 to 19.1
days, R² 0.61 to 0.65, High F1 0.54 to 0.57. High projects were flagged earlier, at a median of 52% of
the planned duration instead of 58%, with 1 false alarm instead of 0.

**Sensitivity to the assumption** (`ml/rain_sensitivity.py`, `ml/models/risk-v2.0.0/rain-sensitivity.json`).
The whole pipeline run again with programmes allowing three quarters of the usual rain, with the pace
recalibrated (1.046 instead of 1.096). Rain's share is the delay trees' split gain, comparable across
versions:

| Allowance | Rain's share of delay gain | Delay MAE | High F1 | Final bands L / M / H |
| --- | --- | --- | --- | --- |
| **0.5 (shipped)** | **12.7%** (wet season 12.2, forecast 0.5) | 19.1 | 0.60 | 40% / 31% / 29% |
| 0.75 | 8.3% (8.1, 0.2) | 18.4 | 0.59 | 41% / 33% / 25% |

So rain's weight depends on the assumption (a third less at 0.75) but does not vanish. In the demo
data, the wet season ahead is the largest driver for the two wet-zone projects (Galle and Colombo),
and lowers the forecast for the Kandy project, whose remaining programme is drier.

## Changes

**2.0.0 (Phase 10).** Likely ranges with every forecast; exact SHAP drivers instead of path
attribution; the straight line competes with the trees for each target and ships for overrun; sign
constraints on crew and the 14-day rain forecast for overrun too, so every what-if action has a known
direction. The data and the delay trees are the same as 1.2.0.

**1.2.0 (Phase 10, issue #27).** Rain (above): the simulator's rain rule, a recalibrated pace, and
the new `wet_days_ahead` input (monotone: more wet days ahead can only raise either forecast).

**1.1.0 (Phase 7).** Adds the three report-issue counts. Their rules in the simulator are in
`ASSUMPTIONS.md`: material delays follow overdue deliveries, safety issues follow poor site
management, design issues follow variations. Against v1.0 on the same held-out projects the gain was
small (delay MAE 19.7 to 19.8 days, overrun R² 0.20 to 0.23); they are included because they are what
a site records first, and real issues may carry more than simulated ones.

## Limitations

- **Synthetic data.** The model has learnt the simulator's rules
  ([ASSUMPTIONS.md](../ml/data_generator/ASSUMPTIONS.md)), not real projects. These numbers show the
  pipeline works; they do not show it is right about real sites. Validating the assumptions with a
  contractor's past projects comes before trusting it.
- **Overrun is weak** (R² 0.27). Most overrun in the simulation comes from time-related overheads and
  variations, which the app does not record yet. A straight line does as well as trees, which says
  the signal is thin, not that costs are simple.
- **Ranges are calibrated on simulated projects.** Real outcomes may be more spread out; check the
  coverage on real completed projects before relying on the width.
- **SHAP values compare with the average snapshot**, not with projects at the same stage, so time
  elapsed and planned duration often appear as drivers. They are marked as context.
- **Rain's weight is assumed.** It follows from `RAIN_ALLOWANCE`, which no contractor has confirmed
  (see [Rain](#rain-an-assumption-not-measured-data) for how much it matters). The climate comes from
  the nearest of seven towns, which is coarse for sites far from all of them (the hill country east
  of Kandy, the north-west).

## Responsible use

- Every forecast shows its likely range, its drivers, the inputs it was missing, the model version
  and the word "estimate".
- Scores are about projects, never people.
- Only project managers and quantity surveyors see risk (`risk:read`), on their own sites.
- High risk alerts the PM once when a project *enters* High, not every day it stays there. The alert
  gives the forecast with its range.

## Data

- **Synthetic projects:** `ml/data_generator/simulate.py` (seed 2026, 300 projects). The
  assumptions and their sources are in `ASSUMPTIONS.md`. The generated file (`ml/data/`) is not
  committed; its SHA-256 is recorded in the model file and in `metrics.json`.
- **Rainfall:** daily precipitation for seven Sri Lankan towns, 2012 to 2025, from the Open-Meteo
  archive API (free, no key; CC BY 4.0). Committed as `ml/data_generator/rainfall.csv`. The monthly
  climate the app uses is derived from it (`python -m data_generator.climate`); a test checks the
  backend's copy matches.
- **No personal data** is used anywhere in training.
