# Model card: supplier on-time chance (BR-12), v1.0.0

| | |
| --- | --- |
| Model | **The smoothed on-time rate.** A logistic regression competed with it and was not clearly better, so the simpler rate ships |
| Version | 1.0.0, trained 2026-10-12. Model file: `backend/app/ai/supplier/models/supplier-v1.0.0.json` |
| Training code | `ml/data_generator/deliveries.py`, `ml/train_supplier.py` |
| Training data | **Synthetic**: 150 simulated suppliers, 4,706 orders over 2016 to 2025, with the real rain climate of seven towns. The app has almost no delivery history yet |
| Used by | BR-12, the purchase-order form and each request's supplier comparison |

## What it is for

It estimates the chance that a supplier's next order arrives on time, so that, under BR-12, an order
for a **critical-path item** from a supplier **under 50%** prompts a suggested alternative. It
suggests; procurement chooses.

Every estimate is shown with:

- its **likely range** (10th to 90th percentile);
- **"based on N deliveries"**;
- a **low data** mark when N is under 5. A BR-12 suggestion about a low-data supplier says it is
  tentative.

**Not for:** rating suppliers' businesses, or anything beyond on-time delivery. It knows nothing
about quality, price, or which materials a supplier sells, so a suggested alternative is worded "if
they supply it".

## How the chance is worked out

On time means the line's whole quantity had arrived by the order's expected date. This is the same
rule the risk model uses for late deliveries. Lines still not complete after their expected date
count as late. Lines not yet due don't count.

1. **The company's rate:** its on-time share across all suppliers, smoothed towards 80% as if by 20
   deliveries at that rate (80% is the starting assumption before the company has a record).
2. **The supplier's rate:** its own on-time share, smoothed towards the company's rate as if by 5
   deliveries. A supplier with 2 of 2 on time is therefore not "100%", and a new supplier starts at
   the company's rate.
3. **The likely range:** on the log-odds scale, as if the rate rested on the supplier's deliveries
   plus the 5 pseudo-deliveries. It is wide with little history and narrows as deliveries are
   recorded.

## The choice: logistic regression against the smoothed rate

The logistic model sees the smoothed rate (as log-odds), how many deliveries it rests on, the lead
time, whether the lead time is under a week, and the wet season at the site (the share of heavy-rain
days in the expected month, from the same climate table as the risk model). The rule, set by the
project owner: **ship it only if it is clearly better on suppliers it never saw**. That means the
95% interval, from resampling whole suppliers, for the difference in log loss must lie entirely in
its favour.

| On 30 held-out suppliers (1,018 orders) | Log loss | Brier | AUC |
| --- | --- | --- | --- |
| Logistic regression | 0.517 | 0.173 | 0.75 |
| **Smoothed on-time rate (ships)** | 0.524 | 0.175 | 0.73 |

Cross-validated on the 120 training suppliers, logistic minus smoothed log loss is −0.004, with a
95% interval of −0.008 to +0.001. The interval includes no difference, so **the smoothed rate
ships**. The backend can score either kind, so a retrain on real history can ship the logistic
model if it earns it.

**Calibration** (held-out, smoothed rate): predicted 44% → 50% actually on time; 58% → 53%; 73% →
78%; 81% → 83%; 92% → 91%.

**With little history** (orders placed when the supplier had fewer than 5 deliveries on record): log loss 0.530 and AUC 0.66, against 0.522 and
0.74 with more. Hence the low-data mark.

## Limitations

- **Synthetic data.** The simulated suppliers follow written-down assumptions
  ([ASSUMPTIONS.md](../ml/data_generator/ASSUMPTIONS.md#suppliers-br-12)). They include a wet-season
  effect and a short-lead-time effect, which are assumptions, not measurements. Validate them with
  real delivery records before relying on them.
- **No material categories.** The model cannot tell whether an alternative supplier stocks the item.
- **Company-wide records.** A supplier's record pools every site's orders. Users see only the rate,
  never another site's orders.
- **The 80% starting rate** for a company with no history is an assumption.
- **Wet-season effect outside Sri Lanka.** The month's rain comes from the same climate as the risk
  model's (the nearest Sri Lankan town, or a site abroad's own history), but the effect's size was
  set for Sri Lankan monsoons.

## Data

- `ml/data_generator/deliveries.py` (seed 2026). The generated file (`ml/data/deliveries.csv`) is not
  committed; its SHA-256 is in the model file and `ml/models/supplier-v1.0.0/metrics.json`. CI checks
  that retraining reproduces the shipped model.
- The rain climate is real (Open-Meteo, 2012 to 2025). No personal data is used.
