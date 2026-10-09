<div align="center">

# SiteSense

**AI-powered delay and cost control for construction projects.**

SiteSense tells a construction company which site will slip before it does, and what to do about it.

[![CI](https://github.com/whoispasindu/SiteSense/actions/workflows/ci.yml/badge.svg)](https://github.com/whoispasindu/SiteSense/actions/workflows/ci.yml)
[![CodeQL](https://github.com/whoispasindu/SiteSense/actions/workflows/codeql.yml/badge.svg)](https://github.com/whoispasindu/SiteSense/actions/workflows/codeql.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-ffc21a.svg)](LICENSE)

</div>

> **Status: Phase 3 of 14 (schedule and S-curve).** Product features arrive phase by phase
> (see [Roadmap](#roadmap)). Nothing here is production-ready yet.

## What it will do

Site engineers submit structured daily reports. AI reads them, tags the issues, and forecasts
delay and cost overrun for every project. Managers test recovery plans before committing to
them, and clients see honest progress without internal costs.

- Six roles with their own permissions: Admin, Project Manager, Quantity Surveyor, Site Engineer, Procurement Officer, Client
- Projects, BOQ import and budget lines, with planned against actual progress
- Daily site reports with photos and weather filled in automatically
- Materials workflow from request to delivery, driven by 12 business rules
- AI risk forecasts with drivers, ranges and a what-if recovery planner
- AI report reading that tags issues, always confirmed by a person
- Cost control, progress claims with retention, and variation orders
- Client portal with progress and variation approval

## Quick start

You need **Docker Desktop** (or Docker Engine with Compose v2) and Git.

```bash
git clone https://github.com/whoispasindu/SiteSense.git
cd SiteSense
docker compose up --build
```

Then open:

| What | URL |
| --- | --- |
| Web app | http://localhost:5173 |
| API health | http://localhost:8000/api/v1/health |
| API docs (development only) | http://localhost:8000/api/docs |

The first start creates the database and its two roles, runs migrations, and starts the API
and the web app with hot reload. Stop with `Ctrl+C`; `docker compose down -v` also deletes the
local database.

### Sign in

Create demo sites and one account per role (local development only):

```bash
docker compose exec backend python -m app.cli seed-dev
```

| Role | Email |
| --- | --- |
| Company Admin | `admin@sitesense.example` |
| Project Manager | `pm@sitesense.example` |
| Quantity Surveyor | `qs@sitesense.example` |
| Site Engineer | `engineer@sitesense.example` |
| Procurement Officer | `procurement@sitesense.example` |
| Client | `client@sitesense.example` |

`seed-dev` also creates three demo projects; Havelock Residences comes with a full BOQ
(`backend/app/seed_data/boq-havelock-residences.csv`, also a good file to try the import with),
a programme and a week of daily reports. Sign in as the site engineer to file today's report.

Two operator commands run the scheduled jobs on demand:

```bash
docker compose exec backend python -m app.cli send-reminders
```

```bash
docker compose exec backend python -m app.cli refresh-weather
```
The password is the value of `SITESENSE_DEMO_PASSWORD` (see `.env.example`). For a real
company, create the first admin instead; it prints a one-time password:

```bash
docker compose exec backend python -m app.cli create-admin --email you@company.lk --name "Your Name"
```

After pulling changes that add dependencies, rebuild and renew the containers' `node_modules`
volume (otherwise the web container keeps its old packages):

```bash
docker compose up --build -V
```

The defaults are for local development only. To change the database passwords, copy
`.env.example` to `.env` and edit it **before the first start** (the roles are created once,
when the database volume is first initialised).

## Running without Docker

Backend (Python 3.13, with a local PostgreSQL that has the roles from
`infra/postgres/init/01-roles.sh`):

```bash
cd backend
python -m venv .venv
.venv/Scripts/activate      # Windows; use `source .venv/bin/activate` on macOS/Linux
pip install -r requirements-dev.txt
cp .env.example .env
alembic upgrade head
uvicorn app.main:app --reload
```

Frontend (Node 22 or later):

```bash
cd frontend
npm ci
npm run dev
```

## Running the tests

```bash
# backend: lint, types, tests
cd backend
ruff check . && ruff format --check . && mypy app tests && pytest --cov

# frontend: lint, types, tests, build
cd frontend
npm run lint && npm run typecheck && npm run coverage && npm run build
```

Backend tests use a real PostgreSQL. Start it first with `docker compose up -d db`; the tests
migrate the `sitesense_test` database and run each test in a transaction that is rolled back.
Override the location with `SITESENSE_TEST_DATABASE_URL` and `SITESENSE_TEST_MIGRATION_DATABASE_URL`. Every pull request also runs dependency audits, a secret scan and
CodeQL; see [docs/security.md](docs/security.md).

## Configuration

Backend settings are environment variables prefixed with `SITESENSE_`
(see [backend/.env.example](backend/.env.example)).

| Variable | Purpose | Default |
| --- | --- | --- |
| `SITESENSE_ENVIRONMENT` | `development`, `test` or `production` | `development` |
| `SITESENSE_DATABASE_URL` | Runtime connection (least-privilege role) | local dev URL |
| `SITESENSE_MIGRATION_DATABASE_URL` | Migration connection (schema owner) | falls back to the above |
| `SITESENSE_CORS_ORIGINS` | Comma-separated allowed browser origins | `http://localhost:5173` |
| `SITESENSE_ALLOWED_HOSTS` | Comma-separated accepted `Host` headers | `localhost,127.0.0.1,backend,testserver` |
| `SITESENSE_MAX_REQUEST_BODY_BYTES` | Largest accepted request body | `1048576` |
| `SITESENSE_LOG_LEVEL` | `DEBUG`, `INFO`, `WARNING`, `ERROR` | `INFO` |
| `SITESENSE_JWT_SECRET` | Access-token signing key, 32+ characters | development value (refused in production) |
| `SITESENSE_ACCESS_TOKEN_TTL_MINUTES` | Access-token lifetime | `15` |
| `SITESENSE_REFRESH_TOKEN_TTL_DAYS` | Refresh-token lifetime (rotated on use) | `7` |
| `SITESENSE_SESSION_MAX_DAYS` | Absolute session limit | `30` |
| `SITESENSE_LOGIN_MAX_FAILURES` / `SITESENSE_LOCKOUT_MINUTES` | Account lockout | `5` / `15` |
| `SITESENSE_LOGIN_RATE_PER_MINUTE` | Sign-in attempts per IP per minute | `10` |
| `SITESENSE_COOKIE_SECURE` | Secure flag on the refresh cookie | `true` |
| `SITESENSE_MEDIA_ROOT` | Folder for site photos (mount a persistent volume in production) | `var/media` |
| `SITESENSE_MAX_PHOTO_BYTES` / `SITESENSE_MAX_PHOTOS_PER_REPORT` | Photo limits | `10485760` / `12` |
| `SITESENSE_WEATHER_ENABLED` | Live forecast from Open-Meteo (off: cached forecasts only) | `true` |
| `SITESENSE_SCHEDULER_ENABLED` | Run the 18:00 reminder and 05:30 weather jobs in the API process | `true` |
| `SITESENSE_REPORT_DEADLINE_HOUR` | BR-11 daily report deadline, site time | `18` |

In production the API refuses to start with debug on, wildcard or plain-HTTP origins, or the
example database password.

## Tech stack

| Layer | Technology |
| --- | --- |
| Web | React 19, TypeScript, Vite, Tailwind CSS 4, React Router, TanStack Query, Zod |
| API | Python 3.13, FastAPI, Pydantic, SQLAlchemy 2, Alembic, structlog |
| Data | PostgreSQL 18 |
| AI (from Phase 6) | pandas, scikit-learn, XGBoost, SHAP |
| Quality | pytest, Ruff, mypy, Vitest, Testing Library, ESLint, CodeQL, Gitleaks |

Architecture notes, the [roles and access matrix](docs/roles-and-access.md) and decision records live in [docs/](docs/).

## Project structure

```
backend/        FastAPI app (api, models, schemas, services, ai, integrations, core) + Alembic
frontend/       React + TypeScript web app
ml/             synthetic data generator, notebooks, versioned models (from Phase 6)
infra/          database bootstrap scripts
docs/           architecture, decision records, security reviews, model cards
.github/        CI, CodeQL, Dependabot, issue and PR templates
```

## Roadmap

| Phase | Name | Status |
| --- | --- | --- |
| 0 | Setup and foundations | Done |
| 1 | Authentication, roles and users | Done |
| 2 | Projects, BOQ and budget | Done |
| 3 | Schedule basics | Done |
| 4 | Daily site reports | In progress |
| 5 | Materials, approvals and rules engine | Planned |
| 6 | Demo data and risk model v1 → **v0.1 MVP** | Planned |
| 7 | Report NLP classifier | Planned |
| 8 | Cost control, claims and variations | Planned |
| 9 | Advanced schedule | Planned |
| 10 | Risk model v2, what-if planner and supplier model | Planned |
| 11 | Dashboard, alerts and AI briefing | Planned |
| 12 | Client portal | Planned |
| 13 | Hardening and deployment | Planned |
| 14 | Testing, UAT and evaluation → **v1.0** | Planned |

After v1.0: an offline-first mobile app for site engineers and voice input in Sinhala, Tamil
and English.

## Contributing

Contributions are welcome. Read [CONTRIBUTING.md](CONTRIBUTING.md) first, and report security
problems privately as described in [SECURITY.md](SECURITY.md).

## Licence

[MIT](LICENSE). Fonts: IBM Plex Sans and IBM Plex Mono (SIL Open Font License), self-hosted through
Fontsource.
