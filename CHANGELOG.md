# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project
uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

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
