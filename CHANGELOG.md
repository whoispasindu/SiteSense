# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project
uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Upgrading

- **Any country.** Nothing changes for a Sri Lankan company: the new settings default to Sri Lanka.
  A company elsewhere sets `SITESENSE_COUNTRY`, `SITESENSE_TIME_ZONE`, `SITESENSE_CURRENCY`,
  `SITESENSE_NUMBER_LOCALE` and `SITESENSE_RISK_LKR_PER_UNIT` before the first project (see
  `.env.example`). Migration 0019 adds each site's rain climate, and removes the seeded 2026 Sri
  Lankan holidays when the country is not LK. A new dependency, `holidays`, needs the backend image
  rebuilt (`docker compose up --build`).
- **Two-step sign-in (Phase 13).** Company Admins, project managers, quantity surveyors and
  procurement officers are asked to set it up at their next sign-in, before anything else. Each
  needs an authenticator app. Set `SITESENSE_MFA_KEY` (32+ characters, different from the JWT
  secret, kept safe: it decrypts every enrolment) before upgrading; production refuses to start
  without it.
- **Mark the demo accounts** on an existing demo or development database: run `python -m app.cli
  seed-dev` once. Demo mode only skips two-step codes, and the nightly reset only runs, for
  accounts the seed has marked.
- Migrations 0017 and 0018 add two-step sign-in and eight indexes.
- **Link existing client accounts to their projects.** From Phase 12, clients see only the projects
  the Company Admin links them to (Users → the client → *Projects this client can see*), not every
  project on their sites. Until linked, an existing client account sees no projects. There is no
  automatic copy from sites, because that would carry over the cross-client exposure this fixes.
- **Clean photos uploaded before this release:** run `python -m app.cli strip-photo-metadata` once
  (add `--dry-run` to count first). It re-encodes any stored photo that still carries a JPEG comment
  or other metadata, and is safe to run again.
- Migrations 0014 to 0016 add the client portal tables, the client links and each project's defects
  period (12 months for existing projects).

### Added

- **Installable app** (PWA, part A; [ADR 0018](docs/adr/0018-installable-app.md)): SiteSense installs
  on phones and computers from the browser, opens from the device (also with no signal), and offers
  "A new version is ready, Reload" after a release instead of reloading under you. An offline
  notice says when there is no connection. Nothing from the API is ever stored on the device.
- **Any country** ([ADR 0017](docs/adr/0017-any-country.md)):
  - The company's time zone, country, currency and number format are settings. "Today" on site,
    the scheduled jobs and the weather follow the time zone; every amount in the app, emails and
    the weekly PDF carries the currency code.
  - **Import public holidays** by country and year on the Holidays page (then edit them).
  - The risk model reads the contract value in rupees: other currencies are converted with
    `SITESENSE_RISK_LKR_PER_UNIT`, and the driver is shown in the company's currency.
  - Sites outside Sri Lanka get their own rain climate for the risk and supplier models, fetched
    once from the Open-Meteo archive with the morning weather refresh.
- Phase 13, hardening and deployment ([ADR 0016](docs/adr/0016-hardening-and-deployment.md)):
  - **Two-step sign-in** with an authenticator app (time-based codes) and ten single-use recovery
    codes. Required for Company Admins, project managers, quantity surveyors and procurement
    officers; optional for site engineers and clients, under **Two-step sign-in** in the account
    menu. A Company Admin can reset someone's (audited, and never their own). Codes work once, and
    wrong codes count towards the account lockout.
  - **Request budgets for every write:** 120 a minute per signed-in user (per IP before sign-in),
    and smaller ones for what-if and the weekly PDF (20) and report analysis (30, now per user).
  - **Demo mode** (`SITESENSE_DEMO_MODE`): a "Demo data" notice, emails only logged, the demo
    accounts skip two-step codes, and a reset to the seeded data every night at 03:00
    (`python -m app.cli reset-demo` by hand). The demo company now has one project at each risk
    level.
  - **A production setup that runs locally:** `docker-compose.prod.yml` with Caddy (HTTPS, one
    origin), migrations as the schema owner, 4 API workers, and scheduled jobs in their own process
    (`python -m app.cli run-scheduler`). Step-by-step hosting guide for Render or Railway, Vercel and
    managed PostgreSQL in [docs/deployment.md](docs/deployment.md).
  - **A load test** (Locust, `loadtest/`): 50 concurrent users, 0 errors. 95th percentiles: reads
    280 ms, writes 359 ms, heavy endpoints 974 ms. Results and machine specs in
    [docs/performance.md](docs/performance.md).
  - **Accessibility checks on every change:** axe runs on every screen the frontend tests reach, and
    a test checks the colour contrast of every design-token pair in both themes
    ([docs/accessibility.md](docs/accessibility.md)).
- Phase 12, the client portal ([ADR 0015](docs/adr/0015-client-portal.md)):
  - **The portal**, under a simpler top navigation:
    - progress and the S-curve;
    - the handover date the PM published, with the reason and earlier dates (the contract date until
      one is published);
    - milestones with their status in words;
    - the photos the PM shared;
    - payments: approved and paid claims with the full breakdown, the contract value with approved
      variations, and the retention held so far (released at the end of the defects period);
    - variations waiting for a decision.

    No budgets, costs, rates, risk scores or internal comments: client responses use their own
    schemas, and a test walks every one of them for internal fields at any depth (TC-07).
  - **Client access per project.** The Company Admin links client accounts to projects (audited).
    Clients reach nothing else: portal pages, variation decisions, notifications and emails, photos.
    Another client's project, even on the same site, answers exactly like one that does not exist
    (tested with two clients on one site).
  - **The defects period** per project (default 12 months, set on the project form). The client's
    payments show when the retention is due back: the end of that period after the published
    handover date (or the contract date before one is published).
  - **`strip-photo-metadata`**, a one-off command that re-encodes stored photos still carrying a
    comment or other metadata.
  - **A "Client view" tab** on each project:
    - the PM publishes the client's handover date with a reason, helped by the programme forecast and
      the risk model's range, or confirms it unchanged (both audited, and the client is notified of a
      new date);
    - flags milestones (suggested ones mapped to tasks by keyword);
    - shares or unshares photos, one at a time or in bulk.

    The PM's dashboard flags a published date as outdated when the programme forecast is more than 7
    working days later than it, or when it has not been reviewed for 30 days.
- Phase 11, the dashboard, alerts and the AI daily briefing ([ADR 0014](docs/adr/0014-dashboard-alerts-briefing.md)):
  - **Today's briefing** at the top of the dashboard: 3 to 5 points on what needs attention, each
    with the records it rests on (counted by the server). Written by Claude (Haiku by default,
    `SITESENSE_BRIEFING_MODEL`) when `SITESENSE_ANTHROPIC_API_KEY` is set, by fixed rules otherwise,
    and always labelled **AI-written** or **Rule-based**. The model receives only structured facts:
    scores and their ranges, counts, project codes and names, rule IDs. It never receives report
    text, comments or people's names; a test captures the real request for every role and fails if
    any reach it. Any failure falls back to the rules with a note.
  - **Portfolio analytics** (`GET /analytics/portfolio`): KPIs, cost against plan with the risk
    model's likely final cost, the risk ranking, confirmed issues per week, each site's saved 5-day
    forecast, and an approval queue of what waits for you. Cost and risk only for the roles that see
    them.
  - **The full dashboard**: briefing card, KPI tiles, a cost ruler per project (committed, budget,
    the forecast at current rates and the model's hatched likely range), issues per week, the
    weather strip for every site, the latest alerts with urgent ones marked, and the approval queue.
  - **Email alerts**: urgent kinds at once (high risk, stop-work, rain on a pour, high-severity
    issues, items waiting for your approval), everything else in an 18:30 digest that is skipped
    when there is nothing new. Each person chooses under **Email settings**; stop-work emails cannot
    be turned off. Emails carry a title, a fixed sentence and a link, never the alert's text. They
    go through a transactional outbox with retries. Without an SMTP host they are written to the
    log.
  - **Weekly PDF report** (`GET /reports/weekly.pdf`, PM and QS only, audited): a download on the
    dashboard and a Monday 07:00 email. On by default for project managers, opt-in for quantity
    surveyors.
- Phase 10, risk model v2, what-if planner and supplier model ([ADR 0013](docs/adr/0013-risk-v2-what-if-supplier-model.md)):
  - **Risk model 1.2.0: rain now counts** ([#27](https://github.com/whoispasindu/SiteSense/issues/27),
    [model card](docs/model-card-risk.md#rain-an-assumption-not-measured-data)). The simulator
    assumes programmes allow for half of a town's usual rain (`RAIN_ALLOWANCE`, an assumption, not
    measured data), loses work by rain intensity and on the day after heavy rain, and is recalibrated
    so the median project is still 10% late. A new input, `wet_days_ahead`, is the heavy-rain days
    expected from the site's climate (nearest of seven towns, shipped with the backend) until the
    planned end. Rain's share of the delay model goes from 0.0% to 12.7% (8.3% if programmes allow
    three quarters; `ml/rain_sensitivity.py`). The risk panel shows it as "Wet season ahead".
  - **Risk model 2.0.0: likely ranges and SHAP drivers** ([model card](docs/model-card-risk.md)).
    Every forecast comes with its likely range (10th to 90th percentile, about 8 in 10 outcomes
    inside it at every stage): the risk panel, the dashboard ranking, the score's bar and the
    High-risk alert all show it. Drivers are exact SHAP values (TreeSHAP in pure Python, checked
    against LightGBM). For each target a sign-constrained straight line competes with the trees, and
    the trees ship only if clearly better: they do for delay; the line ships for overrun.
  - **What-if planner** on each project's new **Risk** tab (project managers): add a crew, work
    Sundays, expedite late materials, weather protection. Each action's effect is a range (half its
    planned change to all of it), labelled a simulation estimate; the PM's cost for an action is added
    to the cost forecast, and a blank cost is called out, never treated as free. Filing reports and
    following up issues appear as advice only. A test checks no action or combination ever makes a
    forecast, or either end of its range, worse. The tab also shows the score's last 14 days with its
    range, and **Risk & what-if** in the menu lists every project by risk.
  - **Supplier on-time model and BR-12** ([model card](docs/model-card-supplier.md)): each supplier's
    chance of delivering on time, with its likely range and "based on N deliveries" (low data under
    5). Trained on simulated histories; logistic regression was not clearly better than the smoothed
    on-time rate, so the rate ships. The purchase-order form suggests a better supplier when a
    critical-path item would go to one under 50%; each request shows its critical-path status (from
    the programme: critical, or 5 working days of float or fewer) and the suppliers for its date, and
    the PM can mark it critical or not (audited). Demo data adds a finished job with a year of
    deliveries.
  - **Forecast handover, two ways:** the Schedule tab shows the programme's date "At current rates"
    and the risk model's likely range, with a note when they disagree. Engineers see the first only.

- Phase 9, advanced schedule ([ADR 0012](docs/adr/0012-critical-path-calendar-weather-stop-work.md)):
  - **Task links and the critical path:** the PM links tasks finish-to-start, with a lag in working
    days. Loops are refused. The critical path is calculated with a two-pass CPM written from scratch.
  - **Forecast handover and slip:** finished tasks keep their actual dates, work under way finishes
    at its own rate, and work not started begins no earlier than today. Tasks now record their
    actual start and finish.
  - **Working calendar:** each project has a working week (Monday to Saturday by default). The
    Company Admin keeps the company's holidays (2026's Poya days and public holidays seeded) and is
    warned when next year's list is missing.
  - **BR-06 (TC-12):** concrete pour tasks with 10 mm or more of rain forecast on a day of work are
    flagged and the site's PMs alerted, daily at 05:45, when a pour is marked, and from
    `app.cli check-pours`.
  - **BR-11:** a stop-work flag stops the tasks its author picks, or the whole project. Only a PM
    changes or clears it. Stopped tasks take no progress, and their forecast moves a working day
    later for each stopped day.
  - **Gantt** on the Schedule tab: planned and forecast bars, the critical path, links, a today
    line, slip, STOP badges and rain marks, with a table for screen readers. The stop-work banner
    shows there too.
  - Demo data: linked programmes, concrete pours and actual dates.

- Phase 8, cost control, claims and variations ([ADR 0011](docs/adr/0011-claims-variations-forecast.md)):
  - **Forecast final cost** per BOQ section: committed cost plus the remaining budget at the cost trend
    so far. The budget panel shows forecast, variance and trend; a section forecast more than 5% over
    budget alerts the PM and QS once (daily at 06:10, after cost events, `app.cli check-variance`).
  - **Progress claims (BR-08):** the QS certifies a percentage per section and the claim is calculated
    with 5% retention, less previous claims; the PM approves or returns it; the QS records payment.
  - **Variation orders (BR-09):** raised by a PM or QS, priced by the QS, routed to the PM or the
    client (any time impact, above the project's limit, or raised by a PM). On approval the contract
    value, budget line, task and planned end change, audited (TC-10). Extra quantity on a BOQ item
    raises its BR-02 allowance.
  - **The client** sees and decides on the variations sent to them, without internal costs.
  - **The BR-09 limit** per project: 1% of the contract value by default; only the Company Admin
    changes it, with a reason, audited.
  - **Cost & claims** page: every project's forecast and claims, and what waits for you.
  - Demo data: claims and variations at every stage on Havelock.

- Phase 7, report issue classifier ([model card](docs/model-card-report-issues.md),
  [ADR 0010](docs/adr/0010-report-issue-classifier.md)):
  - After filing a daily report, its author gets an **AI check**: each sentence of the problems
    text is tagged with a category, a severity and a confidence. Tags under 0.6 are highlighted.
    The author keeps, edits, removes or adds tags and confirms; nothing happens before that.
  - Follow-ups the author can tick (all start unticked): draft a material request (prefilled, and
    closed when the request is raised), alert the project managers, or flag stop-work, which stays
    on the project as a banner until a project manager clears it (BR-11, in part).
  - Names of people are replaced with `[PERSON]` before tagging and storage, including common Sri
    Lankan names written without a title, in any case (#23).
  - The classifier: DistilBERT for the category (macro F1 0.80 on 199 hand-written test sentences,
    against 0.73 for the TF-IDF baseline) and TF-IDF with the labelling guide's rules for severity
    (0.50; DistilBERT did not beat it). DistilBERT runs as ONNX; the TF-IDF model is the fallback.
  - Model weights are attached to a GitHub Release, pinned by SHA-256 in a committed manifest, and
    fetched with `scripts/fetch_models.py`.
  - Risk model 1.1.0 adds confirmed material, safety and design issues of the last 14 days.
    Confirming re-scores the project.
  - Endpoints: `GET /reports/{id}/issues`, `POST /reports/{id}/analyze`,
    `POST /reports/{id}/issues/confirm`, `POST /report-actions/{id}/close`,
    `GET /projects/{id}/report-actions`.
  - Training code, synthetic data generator and labelling guide in `ml/nlp/`.

### Fixed

- The purchase-order list loaded each order's lines in a separate query (found by the load test);
  they now load in one batch.
- Accessibility: form field borders now meet 3:1 contrast in both themes; error pages have a main
  landmark; the sidebar and the demo notice are named landmarks; photo alt text no longer repeats
  the caption shown beside it.
- Photo uploads kept a JPEG comment from the original file. The re-encode now drops it with every
  other piece of metadata, and copies shown to clients are checked again on the way out.

### Changed

- The rate limits on BOQ import, photo upload and report analysis count per signed-in user, not
  per IP, so people sharing an office connection no longer share one budget.
- Empty environment variables count as not set.
- BR-06's heavy-rain threshold is now 10 mm or more (it was "over 10 mm"), in the weather strip,
  the risk model's input and the simulator alike.
- A task's "critical" tick is gone: the critical path is calculated. Tasks can be marked as concrete
  pours instead.

### Security

- A network that would run past the calendar's 30-year horizon is shown without a critical path and
  with a warning, instead of failing; working-day arithmetic no longer walks day by day.
- Pour alerts' de-duplication key is a hash of the rain days, so a long wet spell cannot overflow it.
- A project's contract value and planned end can no longer be edited directly once it is under way;
  they change only through approved variations.
- onnxruntime's usage telemetry to Microsoft is switched off before it is imported.
- Analysing a report is rate limited per client; confirmations lock the report so a double submit
  cannot duplicate follow-ups.
- The transformer training dependencies are pinned and audited in CI.
- A test lists every module that can call out of the server; a new one fails until reviewed.

## [0.1.0] - 2026-10-10

### Changed
- **Whole-app UI redesign** ([ADR 0006](docs/adr/0006-clean-site-office-ui.md)), keeping the
  asphalt and hi-vis identity.
  - Clear type: IBM Plex Sans at a 15 px base in sentence case, replacing widened Archivo and
    small monospaced capitals. Monospace is used only for codes.
  - Light, dark and system themes, switchable from the user menu and applied before first paint.
  - Clean cards, soft shadows and no grid backgrounds or sheet codes.
  - A new dashboard: portfolio KPIs, schedule health per project and a contract value chart; the
    company admin gets system status and admin shortcuts.
  - Charts restyled: the S-curve shows actual as a filled accent line, and the programme timeline
    shows the shortfall against today's plan as a red segment.
  - Sidebar icons, an avatar user menu and calmer error pages. The sign-in button now says "Sign in".

### Added

- Phase 6, risk model v1 (the v0.1 MVP AI feature):
  - A synthetic project simulator (`ml/data_generator`) with every assumption written down, using
    real Open-Meteo rainfall for seven Sri Lankan towns; 300 projects of weekly snapshots.
  - Training with a project-grouped split, a linear baseline and LightGBM with monotone
    constraints. On held-out projects, delay MAE is 19.7 days (baseline 25.6) and F1 for High is
    0.60. All the figures are in the model card, along with the limits of synthetic data.
  - The backend scores exported JSON trees in pure Python: no pickle loading and no ML libraries in
    the API.
  - A feature builder from live data: progress gap and trend, late deliveries, heavy rain in the next
    14 days, committed cost against budget, crew against plan and missing reports.
  - Daily scoring at 06:00, again after each daily report, and `python -m app.cli score-risk`.
    Scores are kept in `risk_scores` with their drivers, inputs and model version.
  - BR-10: High (70+) alerts the site's project managers once when a project enters High.
  - `GET /projects/{id}/risk` and `GET /risk/projects` for PMs and QSs.
  - Dashboard: a High-risk KPI and projects ranked by risk with High, Medium and Low badges. The
    project page shows the score, forecast, drivers and missing data, labelled as an estimate.
  - Projects have a planned crew size; the weather cache holds 14 days; the demo seed adds the
    history the model reads and scores every project.
  - An exploration notebook, a model card, ADR 0009, an ML CI job (tests and a reproducibility
    check), and ML dependencies in pip-audit and Dependabot.
- **Phase 5: materials, approvals and rules engine.**
  - Material requests against BOQ items, with a rules engine of pure functions:
    - BR-01: a unit price more than 5% above the budgeted rate needs the PM.
    - BR-13: the section's committed cost plus the request exceeding its budget line needs the PM.
    - BR-02: quantity is blocked beyond the BOQ plus 3%.
    - BR-04: no approving your own request.
    - BR-05: no purchase order before approval.
    - The request page names the rule that sent a request to the PM.
  - Rates and amounts only for the PM, QS and procurement. Site engineers get cost-free API
    responses (role-specific schemas) and see item, unit, BOQ quantity, requested and remaining.
    They raise requests without prices: the price is pending until the QS enters the quoted price,
    with the budgeted rate shown beside the field. Approval is refused until it is entered.
  - BR-14: at purchase-order issue, an order price more than 5% above the approved price sends the
    request back for PM approval. BR-13 is checked again at issue with the order prices, so lines
    that fit alone but not together cannot both be ordered. The other lines are still ordered.
  - Committed cost is cumulative: each approved, ordered or delivered request once at its latest
    value; pending requests are excluded. The budget shows Committed, Spent, On order and Left.
  - Approval state machine: QS check, PM approval, approved, ordered and delivered, plus rejected,
    change requested and cancelled. Invalid transitions are refused, and every step is audited
    and notified.
  - Suppliers, purchase orders (one project each, price never above the approved price) and
    deliveries (never more than ordered).
  - Budget per BOQ section shows approved, committed and spent cost, derived from orders and
    deliveries so it updates by itself. The BOQ cannot be replaced once requests refer to it.
  - Web: Materials page with pipeline counts and filters; a request form with a BOQ item picker
    and a live rules check; a request page with rule results, history and approve, reject or
    request-change actions. Purchase-order, delivery and supplier screens for procurement, and
    a cost-control panel on the BOQ tab.
  - `seed-dev` adds suppliers and requests at every stage.
  - `docs/business-rules.md` documents every rule.
- **Phase 4: daily site reports.**
  - Site engineers file one report per project per day: weather, crew, work done, problems,
    task progress and up to 12 photos. A second report for the same day is refused with a link
    to the first (TC-03).
  - Weather is pre-filled from a five-day Open-Meteo forecast, cached per site. When the
    service is down, the last saved forecast is shown with a warning (TC-08).
  - Photos are checked, re-encoded and stripped of metadata (including GPS position), and are
    only served to signed-in users who can see the report.
  - The author can correct a report, and add or remove photos, on the day they submitted it.
    Task progress in a report updates the programme.
  - An 18:00 reminder notifies the engineers and project managers of sites still missing
    today's report (BR-07). Project managers are notified when a report is filed.
  - In-app notifications with a bell in the top bar. They are reused by later phases.
  - Web: Site reports page (today's status), project Reports tab with a weather strip and
    history, a phone-friendly report form and a report detail page with a photo viewer.
  - `send-reminders` and `refresh-weather` commands; `seed-dev` adds a week of demo reports.
- **Phase 3: schedule basics.**
  - Programme tasks with planned dates, weight (share of the contract), percent complete and an
    optional BOQ section link; at most 500 tasks and 15 years per project.
  - Planned progress curve week by week from task weights; actual progress from task progress,
    with a daily snapshot history so the actual line shows the real past.
  - Site engineers can report progress (percent complete only); project managers plan.
  - Web: portfolio Schedule page (furthest behind first), project Schedule tab with KPIs,
    planned-against-actual S-curve (Recharts, with a data table), programme timeline and task
    editor.
  - Demo programmes for Havelock Residences (behind plan) and Peradeniya Road Offices.
- **Phase 2: projects, BOQ and budget.**
  - Projects with client, contract value, type, status and contract period, scoped to the
    user's sites; project managers create and edit them.
  - BOQ import from Excel (.xlsx) or CSV with a row-by-row validation report, dry run first,
    all-or-nothing import, flexible header names, and protection against hostile files.
  - BOQ sections and items with exact decimal totals; a cost budget line per section, editable
    by the quantity surveyor (seeded from an optional "Budget rate" column).
  - Web: Projects register, project overview (title block, KPIs, cost by section, team), BOQ
    browser with inline budget editing, and a three-step import screen.
  - Realistic demo BOQ (72-apartment block in Colombo, LKR 1.11 bn) loaded by `seed-dev`.
- **Phase 1: authentication, roles and users.**
  - Sign-in with argon2id passwords, 15-minute access tokens kept in memory, and rotating
    refresh tokens in an httpOnly cookie with reuse detection.
  - Account lockout after 5 failed attempts (15 minutes), per-IP rate limiting on sign-in and
    refresh, uniform answers for wrong password and unknown email.
  - Six roles with a central permission table; `require_permission`, `require_role` and
    site-scoping helpers (groundwork for BR-03).
  - Admin: create users with one-time temporary passwords, change roles, assign sites, reset
    passwords, deactivate and reactivate; manage sites; read the audit log.
  - Append-only audit log for sign-ins, lockouts and admin actions (enforced by database grants).
  - Web: "site gate" sign-in, forced password change, role-based menu, user menu, Users, Sites
    and Audit log screens.
  - `python -m app.cli create-admin` and `seed-dev`.
- **Phase 0: setup and foundations.**
  - FastAPI backend with layered folders (`api`, `models`, `schemas`, `services`, `ai`,
    `integrations`, `core`), settings from environment, SQLAlchemy 2 and Alembic.
  - Liveness and readiness health endpoints.
  - One JSON error envelope for every failure; no stack traces or input echoed to clients.
  - Structured JSON logging with request IDs and automatic redaction of sensitive fields.
  - Security middleware: strict security headers, trusted hosts, CORS allow-list, request
    body size limit.
  - PostgreSQL with separate schema-owner and least-privilege application roles.
  - React + TypeScript + Vite + Tailwind web app with the "site office" layout shell,
    typed and runtime-validated API client, React Query, and a live system-status dashboard.
  - Docker Compose stack started with one command.
  - CI: Ruff, mypy, pytest, Alembic drift check, ESLint, TypeScript, Vitest, build,
    pip-audit, npm audit, Gitleaks, dependency review and CodeQL.
