# Simulator assumptions (risk model v1.x)

The risk model is trained on **simulated projects**. Nothing here comes from a real contractor's
records yet. Each assumption below is a number someone with site experience can check and correct.
The code is `simulate.py`; every value here appears there with a comment.

Weather is the exception: it is **real** daily rainfall for seven Sri Lankan towns from 2012 to 2025,
from the Open-Meteo archive API (`rainfall.csv`, refreshed by `rainfall.py`).

## Projects

| What | Assumption | To validate |
| --- | --- | --- |
| Type | Residential 35%, commercial 25%, mixed use 15%, industrial 15%, institutional 10% | Mix of a typical mid-size contractor's work |
| Contract value | Log-normal, median LKR 450 M, from LKR 60 M to 4 bn | |
| Planned duration | 24 + 15 × ln(value / 60 M + 1) weeks; industrial × 0.85, institutional × 1.1; ± 10% | Duration against value on past jobs |
| Location and start | One of the seven towns; a random Monday from 2013 to 2021 | |
| Cost budget | 82% of the contract value (margin and contingency held back) | Typical budget share |
| Planned crew | 10 + value / 12 M people, between 8 and 250 | Crew sizes against value |
| Planned progress | An S-curve: slow start, fast middle, slow finish (`3f² − 2f³`) | Shape of real programmes |

## What slows a project

Each project has a hidden **site-management quality** between 0 and 1 (Beta(5, 2): most sites are
run reasonably well, a tail is not). The model never sees it, only its symptoms.

| Factor | Rule |
| --- | --- |
| Base productivity | `BASE_PACE` + 0.12 × (quality − 0.7), ± 3% a week. `BASE_PACE` is 1.096, **calibrated** (`python -m data_generator.simulate --calibrate`) so the median project still ends 10% of its planned duration late, as in v1. Read it as the programme's general time allowance: with no rain, crew or material trouble a site would finish about 9% early, and the wet season eats into that. |
| Rain | See [Rain](#rain-risk-model-12) below. |
| Crew | The crew drifts around 1 − 0.15 × (1 − quality) of the plan. Shortages start with a 4–8% chance a week (more on poorly run sites), last 2–6 weeks and cut the crew to 60–80%. Output scales with crew^0.7, capped at 110%. |
| Deliveries | While 5–92% of the work is done, Poisson(0.6 + value / 800 M) deliveries a week. Each is on time with the project's supplier reliability (Beta(6, 2), better on well-run sites); otherwise it is 1 + Gamma(2, 3) × (1.5 − quality) days late. Each delivery still overdue holds up 4% of the week's work, up to 40%. |
| Variations | 1.2% chance a week of extra scope: 2–8% more work and cost, not in the plan. (Variation counts are not a model input until Phase 8, so this is noise the model cannot see.) |
| Noise | ± 4% of a week's progress |

## Rain (risk model 1.2)

Changed for issue #27. In v1 rain hardly mattered: programmes were assumed to allow for all of a
town's usual weather, so rain only slowed a job in wetter-than-normal weeks, and over a project that
evened out (about −2 days on average). Surveys of Sri Lankan building projects rank rainy weather as
a leading cause of delay, which suggests programmes do not fully allow for the monsoon.

| What | Assumption | To validate |
| --- | --- | --- |
| **Allowance** (`RAIN_ALLOWANCE`) | **0.5: programmes allow for half of the town's usual rain loss for the month.** Rain beyond that slows the job; a drier-than-allowed week helps. **This is an assumption, not measured data.** At 0.75 rain's weight in the model falls by about a third (model card, sensitivity) | The single most important number to replace with contractor data: how many working days per month their programmes set aside for rain, against the days actually lost |
| Lost work by intensity (`RAIN_BANDS`) | 2–10 mm: 10% of the day; 10–25 mm (heavy, BR-06): 45%; 25 mm or more: 80% | Site diaries: hours lost against the day's rainfall |
| The day after heavy rain (`RAIN_LINGER`) | Another 25% of the next day is lost (wet ground, dewatering, access) | Site diaries |
| By stage (`RAIN_STAGES`) | Earthworks and substructure (first 30% of the work) × 1.2; the frame (to 60%) × 1.0; closed in × 0.4 | Which trades stop in rain |
| What the model sees | `rain_days_next_14`: the 14-day forecast, as before. **New:** `wet_days_ahead`: heavy-rain working days expected from the town's climate (share of days with 10 mm or more, per month, 2012–2025) from tomorrow to the planned end, at least the next 28 days | The app uses the site's nearest of the seven towns |

The town's "usual loss" for each month is the average of the same rule over 2012 to 2025.

## Cost

| Item | Rule |
| --- | --- |
| Price drift | Material prices move by N(2%, 3%) over the project, applied as work is done |
| Rework | 4% × (1 − quality)^1.5 of the cost is redone on poorly run sites |
| Overheads | Time-related costs are 10% of the budget over the planned duration; every week past the planned end costs another week of them |
| Expediting | Each late delivery costs 0.02% of the budget per week late |

## What the app would have recorded

| Feature | How the simulator produces it |
| --- | --- |
| Progress gap and trend | Planned against actual S-curve position, with ± 1 point reporting noise; trend over the last three weeks |
| Late deliveries | Deliveries due so far that arrived late or are still overdue, and their mean lateness |
| Rain in the next 14 days | The real rainfall for the next 14 days, each day's heavy/not-heavy flipped with a 15% chance (a two-week forecast is often wrong) |
| Wet days ahead (v1.2) | The town's climate (share of heavy-rain days per month) summed over the working days from tomorrow to the planned end, at least 28 days ahead |
| Cost variance | Committed cost against the budgeted value of the same work: price drift, rework and expediting so far, ± 1.5 points. Overheads are not visible (the app does not track them yet) |
| Crew against plan | Average reported crew over the last 12 working days against the planned crew, each report ± 8% |
| Missing reports | Each working day's report is missing with chance 0.02 + 0.30 × (1 − quality)² |
| Confirmed report issues (v1.1) | Per week, Poisson counts scaled by the share of reports filed: material delays 0.1 + 0.5 per overdue delivery; safety 0.05 + 0.6 × (1 − quality)²; design 0.08 plus 1.5 after each variation, fading by 40% a week. The model sees the last two weeks. Drawn from their own random stream, so adding them left every other number unchanged |

## Outcomes

The project runs until all the work is done (or three times the planned duration, which never
happened in the training set). Final delay = actual minus planned completion, in days. Final overrun
= final cost against the budget, in %. The default run (300 projects, seed 2026) gives a median delay
of 10% of the planned duration (calibrated, see `BASE_PACE`) and a median overrun of 6.5%. Final risk
bands: 40% Low, 31% Medium, 29% High (v1: 40%, 33%, 27%). The longest delay was 50% of the planned
duration (v1: 45%).

## Known limits

- The relationships are the simulator's rules, so the model learns those rules, not reality.
  A real contractor's history would show which of them are wrong.
- Overruns depend mostly on things the app does not record yet (overheads, variations), so the
  overrun model is much weaker than the delay model. That is stated in the model card.
- One snapshot per project per week; consecutive weeks are strongly related, which is why the
  train/test split is by project.
