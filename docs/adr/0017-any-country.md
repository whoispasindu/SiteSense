# ADR 0017: Any country: the company's time zone, currency and holidays, and the risk model abroad

- Status: accepted
- Date: 2026-11-15
- Changes: "today on site" in [ADR 0007](0007-daily-reports-photos-weather.md) (was Colombo), the
  rain climate in [ADR 0013](0013-risk-v2-what-if-supplier-model.md) (was the nearest Sri Lankan town
  everywhere)

## Context

SiteSense will be released as open source for companies to run themselves, in any country
([release plan](../plans/open-source-release.md), decision 5). Until now it assumed Sri Lanka:

- the `Asia/Colombo` time zone (`core/clock.py`, the scheduler, the weather request, the web app);
- LKR in about 124 lines of the web app and in backend messages;
- "Poya days" in the holiday wording, and Sri Lanka's 2026 holidays seeded by migration 0011;
- the risk model reads the contract value in **LKR millions** (about 7% of the delay forecast's SHAP
  share) and the rain climate of the **nearest of seven Sri Lankan towns**, which for a site in
  London is thousands of kilometres away.

## Decision

### Settings, not an admin page

The time zone, country, currency and number format are server settings, like the rest of
SiteSense's configuration: `SITESENSE_TIME_ZONE`, `SITESENSE_COUNTRY`, `SITESENSE_CURRENCY`,
`SITESENSE_NUMBER_LOCALE` (Sri Lanka's by default, so existing installs are unchanged).

- The time zone decides "today" for every rule and when every scheduled job runs. The API workers
  and the scheduler process must agree on it, and the scheduler builds its triggers at start. A
  setting read at start (changed with a restart) is the simplest way to keep them consistent; an
  admin page would need every process to notice a change.
- Amounts are stored as plain decimals with no currency and are never converted. Changing the
  currency later would only relabel every amount, so it is set at install, not in the app.
- The setup script (release plan, step 4) will ask for them.

The API sends them to the web app with the signed-in user (`/me` → `company`), and
`frontend/src/lib/locale.ts` holds them for the money and time helpers. A test fails if "LKR",
`Asia/Colombo` or `en-LK` appears in any screen's code.

Amounts are stored to 2 decimals (`Numeric(16, 2)`). Currencies with no minor unit (JPY, KRW and
others) are shown without decimals; currencies with three (KWD, BHD, OMR) keep two.

### Holidays

Holidays were already data the Company Admin keeps. The wording no longer assumes Poya days, and
the admin can **import a country's public holidays for a year** (the `holidays` package: MIT
licence, offline data, about 500 countries and regions), then edit them. Dates already entered are
left alone, and each import is audited. Sri Lanka's list in the package ends with the last
gazetted year (2026 today); for a later year the import says none are published yet.

Migration 0011 seeded Sri Lanka's 2026 holidays into every database. Migration 0019 removes those
seeded rows (no author) when `SITESENSE_COUNTRY` is not LK.

### The risk model: contract value

The model was trained in LKR and is not retrained now. For another currency,
`SITESENSE_RISK_LKR_PER_UNIT` (LKR per unit of the currency) converts the contract value for the
model only. It is **required** when the currency is not LKR: a forgotten rate would silently make
every project look 300 times smaller in pounds. The driver is still shown in the company's currency.

Rejected for now: retraining on a size measure that does not depend on currency (planned duration
and crew are already inputs; BOQ size per day could replace the value). It changes the model,
`check_model.py` and the model card, and needs the simulator to produce that measure. It is the
better long-term answer and is recorded in the release plan.

### The risk model: rain climate

`climate.for_site` decides:

1. **In Sri Lanka** (its bounding box, which no other country's land reaches): the nearest of the
   seven towns, as the model was trained. Unchanged, so Sri Lankan scores do not move.
2. **Elsewhere:** the site's own monthly heavy-rain shares, worked out exactly as the towns' were
   (Open-Meteo archive, daily precipitation 2012 to 2025, a day with 10 mm or more is heavy, a missing
   value counts as dry, rounded to 4 decimals). Fetched **once** per site by the morning weather
   refresh and `refresh-weather`, stored on the site (`sites.rain_climate`), and cleared when the
   site's coordinates change. Scoring never fetches.
3. **Otherwise** (no coordinates, or the history not fetched yet): the seven towns' average, with a
   note on the forecast.

The archive adapter follows the forecast adapter's rules: a fixed https host, only the stored
coordinates in the query, no redirects, a size cap and a validated response. It is listed in
`tests/test_outbound_calls.py`: it sends coordinates, never report text.

The supplier model's wet-season effect uses the same climate.

## Consequences

- Existing Sri Lankan installs see no change: same defaults, same towns, same holidays.
- A company abroad gets its own clock, currency, holidays and rain. Its risk scores rest on a model
  trained for Sri Lanka; the model cards say so.
- The interface stays in English, and the BOQ import still reads numbers written with a comma for
  thousands (not `1.250,50`).
- The report classifier's name redaction knows common Sri Lankan names only.
