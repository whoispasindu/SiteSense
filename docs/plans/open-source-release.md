# Open-source release plan

Status: decided (2026-11-15). Step 3 (any country) done on 2026-11-15
([ADR 0017](../adr/0017-any-country.md)); the other steps not started. Follows Phase 14 (UAT and evaluation), so the first
public release is v1.0. This page collects what is decided and what is still open, so the release
work starts from it.

## Goal

- **Now:** SiteSense is released as an open-source project. A construction company in any country
  can install and run it on its own server, with no help from us.
- **Later:** we offer SiteSense as a hosted cloud service. The cloud service runs the same release
  that self-hosting companies run.

Done when a company with a server and Docker can go from nothing to a working, secure SiteSense with
its own admin account, time zone, currency and holidays by following the docs alone, back it up,
restore it, and upgrade it to the next release.

## Decided by the project owner (2026-11-15)

1. **Licence: AGPL-3.0.** Replaces MIT before the repository is made public. Companies self-host
   freely; anyone who offers a changed SiteSense as a service must publish their changes. Get the
   wording checked by a lawyer once.
2. **Contributions: a CLA (Contributor Licence Agreement).** Contributors grant us the right to also
   offer their code under other terms, so the cloud service and any commercial licence stay
   possible. Automated with a CLA bot on pull requests, in place before the first outside pull
   request.
3. **Name: SiteSense.** The domain is available. Still to do: a trademark search for construction
   software in the countries we sell the cloud service in, and registering the domain and, if
   affordable, the name.
4. **Every feature stays free** in the open-source release, including two-step sign-in, the AI
   models and the AI briefing (with the company's own Claude API key). The cloud service sells
   hosting, backups, updates, monitoring, support and an uptime promise, not features.
5. **Any country from v1.0.** The Sri Lankan time zone, currency and holiday wording become company
   settings, with Sri Lanka as the default (step 3). Sri Lanka stays the home of the demo data. Both
   risk model problems are solved for v1.0 (step 3).

## Where we start

Already in place:

- `docker-compose.prod.yml`: HTTPS through Caddy on one origin, 4 API workers, the scheduler in its
  own process, read-only containers, the database not exposed.
- The API refuses to start in production with weak settings (debug, wildcard origins, example
  passwords, the development MFA or JWT key, plain-HTTP links, mail without TLS).
- `python -m app.cli create-admin` creates the first admin with a one-time password.
- [deployment.md](../deployment.md) covers the local production setup and Render, Railway and Vercel.
- Semantic versioning, a changelog with upgrade notes, and migrations that run on start.
- `SECURITY.md`, `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, CI with CodeQL, Gitleaks and dependency
  audits.
- Holidays are already data, not code: the Company Admin keeps them (Admin → Holidays), so a company
  in another country can enter its own today. Only the wording says "Poya days".
- Weather (Open-Meteo) works anywhere, from each site's coordinates.

Checked on 2026-11-15:

- The repository is private and MIT-licensed.
- Every commit is by the project owner (and Dependabot), so the licence can still be changed freely.
- No `.env` file has ever been committed, and site photos (`backend/var/media`) are not tracked.

Gaps for self-hosting:

- **No published images.** The production compose file builds the images from source.
- **The large model needs the GitHub CLI.** `scripts/fetch_models.py` downloads the DistilBERT
  report classifier with `gh release download`, signed in to an account that can read the repository.
- **The setup is manual.** Secrets in `.env.prod` are filled in by hand.
- **Sri Lanka is built in** (details in step 3).
- **No backup and restore guide.**
- **No sizing guide.** The load test results are in [performance.md](../performance.md), but there
  is no "this many users needs this server".
- **One company per installation.** There is no tenant concept in the database. This is right for
  self-hosting, and it shapes the cloud plan below.

## Steps

### Step 1: Release images

- Build and publish the backend and frontend images to GitHub Container Registry on every release
  tag (`ghcr.io/<owner>/sitesense-backend:1.0.0` and `-frontend`), for `linux/amd64` and
  `linux/arm64`.
- Attach an SBOM and sign the images (cosign, keyless through GitHub Actions).
- Change `docker-compose.prod.yml` to pull images by version (`SITESENSE_VERSION=1.0.0`), keeping a
  build override for people working on the code.
- Done when `docker compose pull && docker compose up -d` runs a release with no source checkout
  beyond the compose file, the Caddyfile and the env file.

### Step 2: Models without the GitHub CLI

- Put the DistilBERT model files in the backend image at build time, checked against the SHA-256 in
  the committed manifest. Keep the TF-IDF fallback.
- Or, if the image gets too large: download the files over plain HTTPS from the public release, with
  the same SHA-256 check, and no sign-in.
- Done when a fresh install uses the DistilBERT model with no GitHub account.

### Step 3: Any country

What is fixed today (counted on 2026-11-15, tests left out):

| What | Where | Size |
| --- | --- | --- |
| Time zone `Asia/Colombo` | `core/clock.py` (`SITE_TIME_ZONE`, `site_today`), used by about 20 services, the scheduler and the dashboard; `integrations/weather.py` (asks Open-Meteo for Colombo time); `features/admin/adminUtils.ts` and two other frontend files | backend 10 files, frontend 3 files |
| Currency LKR | Backend: messages (`rules/materials.py`), `ai/risk/scoring.py`, `schemas/analytics.py` (`RangeLKR`), `services/boq_import.py`. Frontend: `lib/money.ts` (`formatCompactLKR`, `en-LK` number format) and labels such as "Contract change, LKR" | backend 11 files, frontend 26 files, about 124 lines |
| "Poya days" wording | `models/schedule.py`, `rules/calendar.py`, `services/calendar_service.py`, `services/network_service.py`, `pages/admin/HolidaysPage.tsx` | 5 files, text only |
| Risk model: contract value in LKR millions | `ai/risk/features.py` (`contract_value_m`) | about 7% of the delay forecast's SHAP share, 4.5% of the overrun's |
| Risk model: rain climate | `ai/risk/climate.py` uses the nearest of seven Sri Lankan towns (`rain_climate.json`) | a site in another country would get a town thousands of km away |

Done on 2026-11-15 ([ADR 0017](../adr/0017-any-country.md)), as proposed below except:

- The settings are **server settings** (`SITESENSE_TIME_ZONE`, `SITESENSE_COUNTRY`,
  `SITESENSE_CURRENCY`, `SITESENSE_NUMBER_LOCALE`, `SITESENSE_RISK_LKR_PER_UNIT`), not an admin page:
  the API workers and the scheduler process must agree on the time zone, and the currency must not
  change once amounts exist. The setup script (step 4) asks for them.
- `SITESENSE_RISK_LKR_PER_UNIT` is required when the currency is not LKR, so a forgotten rate cannot
  silently skew every score.
- Sri Lankan sites keep the nearest of the seven towns (scores there do not move); only sites
  outside Sri Lanka fetch their own rain history.
- Migration 0019 removes the seeded 2026 Sri Lankan holidays when the country is not LK.

Still to do from this step: retrain the risk model on a size measure that does not depend on
currency (then drop `SITESENSE_RISK_LKR_PER_UNIT`), and the setup script's questions (step 4).

The proposal:

- **Company settings**, kept by the Company Admin (a new Admin → Company page, audited), set once at
  install by the setup script (step 4):
  - **Time zone** (IANA name, default `Asia/Colombo`). One for the whole company in v1.0: `site_today`
    and the scheduler read it instead of the constant, and the weather request uses it. A time zone
    per site (for companies working across time zones) waits until someone asks for it.
  - **Currency** (ISO 4217 code, default `LKR`) and **number format** (locale, default `en-LK`).
    Amounts stay plain decimals in the database; only labels and formatting change. The frontend
    gets one helper (`formatMoney`, `formatCompactMoney`) reading the currency from the session, and
    every "LKR" label uses it. Currencies with no minor unit (for example JPY) show no decimals.
  - Changing the currency after projects exist is refused, or only allowed with a warning that
    amounts are not converted.
- **Holidays:** reword "Poya days and public holidays" to "public holidays and other days off" (Sri
  Lanka's wording stays in the demo data). Add **Import public holidays** for a country and year
  (the `holidays` Python package, offline), which the admin can then edit. Check that the Sri Lanka
  import includes Poya days before relying on it there.
- **Risk model, contract value:** for v1.0, a company setting **"value of 1 unit of your currency in
  LKR"** (default 1) converts the contract value before scoring, and the model card says so. Later,
  retrain (risk model 2.1) with a size measure that does not depend on currency, and drop the
  setting.
- **Risk model, rain climate:** when a site's coordinates are saved, fetch its monthly heavy-rain
  shares from the Open-Meteo archive once and store them with the site. Keep `rain_climate.json`
  for the demo and as a fallback inside Sri Lanka. A site with neither uses a neutral climate (the
  training average) and its forecast says so.
- **Model cards:** say plainly that the models were trained on simulated projects with Sri Lankan
  rainfall, so scores outside Sri Lanka are even less proven.
- **Not in v1.0:** translating the interface. It stays English.
- Tests: a project in another time zone rolls over to "today" at its own midnight; the scheduler's
  18:00 reminder uses the company time zone; every money label uses the configured currency (a
  frontend test fails on a hard-coded "LKR" outside the demo and tests); the risk score of a
  converted contract value matches the LKR one; a site outside Sri Lanka uses its own climate.
- Done when a company set to, for example, `Europe/London` and `GBP` sees no LKR, Colombo time or
  Poya wording anywhere, and its risk forecasts use its own sites' rain.

### Step 4: Install in one step

- A setup script (`scripts/setup.sh`, plus a PowerShell version or a Python one) that:
  - writes `.env.prod` from `.env.prod.example` with strong random values for every secret, and a
    different `SITESENSE_MFA_KEY` and `SITESENSE_JWT_SECRET`;
  - asks for the domain name, the company's admin email, time zone and currency (step 3) and,
    optionally, SMTP details;
  - never turns demo mode on;
  - starts the stack and runs `create-admin`, printing the one-time password once.
- Later, optionally: a first-run page in the app instead of the CLI step, available only while there
  are no users.
- Done when the quick start in the README is about five commands.

### Step 5: Run it safely

- **Backup and restore guide** in `docs/self-hosting.md`:
  - a nightly `pg_dump` and a copy of the photos volume, kept off the server;
  - how to restore into a new installation, tested end to end;
  - "back up before every upgrade", since migrations run on start.
- **Sizing:** from the load test, the server size for up to 50 people working at once, and what to
  change above that.
- **Upgrades:** read the changelog's upgrade notes, back up, pull the new version, start. Say which
  releases get security fixes (for example the latest minor release only).
- **Health:** the health endpoint, and what to watch in the logs.

### Step 6: Go public

- Replace `LICENSE` with AGPL-3.0, update the README badge and licence section, set
  `license = "AGPL-3.0-only"` in `backend/pyproject.toml`, and add the same field to
  `ml/pyproject.toml` and `frontend/package.json` (neither has one today). Add a short licence
  notice to `CONTRIBUTING.md`.
- Add the CLA text and the CLA bot.
- Run Gitleaks over the full history once more, and read through the existing issues, pull requests
  and releases, since they become public too.
- Move the deployment guide's Render, Railway and Vercel section under "other ways to host".
- Release v1.0 with signed images, the changelog and the upgrade notes.
- Make the repository public, then turn on Discussions (or another place for questions) and say in
  `SECURITY.md` how to report problems privately.

## Later: the cloud service

- **One installation per customer.** Each company gets its own stack and database from the same
  release images. This keeps companies' cost data apart without changing the code, and the cloud
  runs exactly what self-hosting companies run.
- Shared services the cloud adds around it: sign-up and billing, automated backups, updates,
  monitoring, email (SMTP) and the Claude API key, all set through the existing settings.
- **Multi-tenancy only if the price per customer needs it.** Adding a tenant to every table and
  query is a large change with a security risk; decide it on numbers from the first cloud customers.
- A way to move between the two: a company can export its data from the cloud and restore it on its
  own server, and the other way round (the backup format from step 5).
