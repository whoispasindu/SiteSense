# ADR 0013: Risk model v2, the what-if planner, and the supplier model (BR-12)

- Status: accepted
- Date: 2026-10-12
- Supersedes, for drivers: the path attribution in [ADR 0009](0009-risk-model-v1.md)

## Context

Phase 10 turns the forecast into decision support. The build guide asks for:

- a retrain with likely ranges (quantile regression), SHAP drivers and a backtest;
- a what-if endpoint and planner;
- a supplier on-time model (logistic regression on delivery history) for BR-12.

Issue #27 asked first for rain to carry real weight in the risk model.

The project owner decided:

- **Rain:** programmes allow for half a town's usual rain (`RAIN_ALLOWANCE = 0.5`). It is a named
  assumption, not measured data, with a sensitivity check at three quarters.
- **Ranges everywhere:** every forecast is shown with its likely range, never alone.
- **Simpler models win ties:** the straight-line baseline ships for cost overrun if it matches or
  beats the trees. The logistic supplier model ships only if it clearly beats the smoothed on-time
  rate.
- **What-if:** four causal actions:
  - add a crew;
  - work Sundays;
  - expedite late materials;
  - weather protection.

  Each effect is a range, labelled a simulation estimate. The PM's cost for an action is added to
  the cost forecast, and a blank cost reads "cost not entered", never free. Management actions are
  advice only.
- **BR-12:** a critical-path item is a request whose BOQ section is linked to a critical task, or
  to one with 5 working days of float or fewer. The PM can override it either way, shown on the
  request. Estimates show "based on N deliveries", and low-data suppliers make suggestions tentative.
- **Handover:** the Schedule tab shows "At current rates" and "Risk model, likely range", with a
  note when they disagree. The Phase 12 client portal will show one date, chosen by the PM.

## Decisions

**Rain (risk model 1.2).** The simulator's rain rule changed:

- programmes allow for half the usual loss;
- loss depends on intensity (10%, 45% or 80% of a day);
- a quarter of the day after heavy rain is lost;
- the effect depends on the stage of work;
- the pace is recalibrated (`--calibrate`) so the median project is still 10% late.

A new input, `wet_days_ahead`, is computed in the app from a shipped climate table (the nearest of
seven towns), so nothing is fetched.

**Two families compete per target.**

- LightGBM trees and a least-squares line both carry the same sign constraints. For the line this
  is constrained least squares, so a fitted sign can never run backwards.
- The trees ship only if a 95% interval, from resampling whole projects, for the difference in
  their cross-validated errors lies entirely in their favour.
- Delay: the trees, clearly better by 3.7 days. Overrun: the line (the interval included zero).
- The same bootstrap rule decides the supplier model.

**Ranges are offsets around the forecast.**

- They come from quantile regression (10th and 90th percentiles) of the shipped model's
  out-of-fold errors, on the planned duration and the planned days still to run.
- Quantile trees were rejected: LightGBM refuses monotone constraints with the quantile objective,
  so a recovery action could have widened a range upwards.
- Offsets that don't depend on anything an action changes move the whole range with the forecast.
- Coverage on held-out projects: 0.78 (delay) and 0.80 (overrun), steady across stages.
- Ranges are stored with every score, returned by the API, and shown on every screen that shows a
  forecast, and in the High-risk alert.

**SHAP drivers, computed exactly in pure Python.**

- TreeSHAP (Lundberg et al., the polynomial-time algorithm) uses node counts now exported with each
  tree. A line's SHAP values are `coef × (x − mean)`.
- Tests compare the values with LightGBM's own, and with brute-force Shapley values on a small tree.
- The model file format became `sitesense-risk-v2`. It is still plain JSON, validated on load, with
  no pickles.

**No schedule features in the model.** The simulator has no task network, so it cannot produce the
programme's slip the way the app computes it. A feature whose live meaning differs from its training
meaning would mislead. Stopped days still reach the model through the progress gap.

**The what-if planner calculates and stores nothing.**

- Only the PM (`risk:what_if`) uses it, on their own sites.
- Each action is applied at half and at full strength, so its effect is a range.
- Every input an action touches has a fixed direction in both models, and a test checks that no
  action or combination, at either strength, makes a forecast or either end of its range worse.
- Costs are converted to a share of the cost budget and added to the cost forecast. When there is no
  budget, that is said.

**The supplier model is trained on simulated histories.**

- The app has 2 real deliveries. The simulation records only what the app could know at each order:
  orders already due.
- The smoothed rate ships, because the logistic model wasn't clearly better.
- The likely range is a log-odds interval on the supplier's effective number of deliveries.
- "On time" is the same rule as the risk model's late deliveries.

**BR-12 placement.**

- On the purchase-order form, the chosen supplier's chance appears beside the supplier select. A
  BR-12 notice suggests the best alternative when any line is a critical-path item and the supplier
  is under 50%.
- On each request, a panel shows its critical-path status and reason, the PM's override, and the
  suppliers ranked for its date.
- The override is a nullable column (migration 0012), set by a strict boolean (`"yes"` is refused)
  and audited.
- The near-critical float is a setting, `SITESENSE_BR12_FLOAT_DAYS`, default 5.

## Consequences

- Risk forecasts read as estimates with uncertainty. On a young project the ranges are wide: that is
  the honest state of knowledge.
- Overrun is forecast by a straight line. The signal is thin until the app records overheads and
  variations.
- Rain's weight and the supplier effects rest on assumptions documented in `ASSUMPTIONS.md`. Real
  contractor data should replace them, starting with `RAIN_ALLOWANCE`.
- The supplier model cannot tell whether an alternative stocks the material; the suggestion says
  "if they supply it".
- The near-critical float is an environment setting, not yet a screen for the Company Admin.
