<div align="center">

# SiteSense

**AI-powered delay and cost control for construction projects.**

SiteSense tells a construction company which site will slip before it does, and what to do about it.

[![CI](https://github.com/whoispasindu/SiteSense/actions/workflows/ci.yml/badge.svg)](https://github.com/whoispasindu/SiteSense/actions/workflows/ci.yml)
[![CodeQL](https://github.com/whoispasindu/SiteSense/actions/workflows/codeql.yml/badge.svg)](https://github.com/whoispasindu/SiteSense/actions/workflows/codeql.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-ffc21a.svg)](LICENSE)

</div>

> **Status: Phase 0 of 14 (foundations).** The skeleton runs end to end; product features
> arrive phase by phase (see [Roadmap](#roadmap)). Nothing here is production-ready yet.

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

Backend integration tests that need a real database run when `SITESENSE_TEST_DATABASE_URL` is
set (CI always sets it). Every pull request also runs dependency audits, a secret scan and
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

Architecture notes and decision records live in [docs/](docs/).

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
| 0 | Setup and foundations | In progress |
| 1 | Authentication, roles and users | Planned |
| 2 | Projects, BOQ and budget | Planned |
| 3 | Schedule basics | Planned |
| 4 | Daily site reports | Planned |
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

[MIT](LICENSE). Fonts: Archivo and IBM Plex Mono (SIL Open Font License), self-hosted through
Fontsource.
