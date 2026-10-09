# SiteSense

AI-powered delay and cost control for construction companies (PUSL2107 Applied Group Project).

Site engineers submit structured daily reports, AI reads the reports and forecasts delay and cost
overrun for every project, and managers test recovery plans before committing to them.

## Repository layout

```
sitesense/
  frontend/              React + TypeScript + Vite + Tailwind web app
    src/
      pages/             One component per screen (Dashboard, Project, Materials, Risk, ...)
      components/        Shared UI; layout/ holds the sidebar and top bar shell
      features/reports/  Daily report form and AI check
      api/               Typed API client and React Query hooks
      store/             Client-side state
      routes.tsx         All app routes
  backend/               Python + FastAPI API
    app/
      api/               FastAPI routers (router.py registers them all)
      models/            SQLAlchemy models
      schemas/           Pydantic request and response schemas
      services/          Workflow logic and rules engine
      ai/                Risk model, NLP classifier, supplier model, briefing
      integrations/      Weather, LLM, notifications (adapters)
      core/              Config, database, logging, error handling
    alembic/             Database migrations
    tests/               pytest unit and integration tests
  ml/
    notebooks/           Data exploration and evaluation
    data_generator/      Synthetic project simulator
    models/              Saved, versioned model files
  docs/                  Diagrams, decisions, reports, meeting notes
  docker-compose.yml     Database, backend and frontend for local development
```

## Running locally

### Option A: everything in Docker (one command)

Needs only [Docker Desktop](https://www.docker.com/products/docker-desktop/).

```bash
docker compose up --build
```

- Frontend: http://localhost:5173
- Backend: http://localhost:8000 (API docs at http://localhost:8000/docs)

Code is mounted into the containers, so saving a file reloads the app. Database migrations run
automatically when the backend starts. Stop with `Ctrl+C`, or `docker compose down`.

### Option B: database in Docker, backend and frontend on your machine

Needs Python 3.12+, Node.js 22+ and Docker Desktop. Faster to debug, and works with your
editor's debugger.

```bash
docker compose up -d db
```

Backend:

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS / Linux
pip install -r requirements-dev.txt
copy .env.example .env          # Windows (cp on macOS / Linux)
alembic upgrade head
uvicorn app.main:app --reload
```

Frontend:

```bash
cd frontend
npm install
npm run dev
```

In development, frontend requests to `/api/...` are proxied to the backend
(see `frontend/vite.config.ts`), so the browser never needs the backend's address.

## Database migrations

Models live in `backend/app/models/`. After adding or changing a model (and importing it in
`app/models/__init__.py`), create and apply a migration from the `backend` folder:

```bash
alembic revision --autogenerate -m "add users table"
alembic upgrade head
```

Always read the generated file in `alembic/versions/` before committing it. CI runs
`alembic check`, which fails if a model changed without a migration.

## Checks

| Where    | Command                                                       |
| -------- | ------------------------------------------------------------- |
| backend  | `ruff check .` · `ruff format --check .` · `pytest`           |
| frontend | `npm run lint` · `npm run typecheck` · `npm test` · `npm run build` |

The same checks run in GitHub Actions on every pull request (`.github/workflows/ci.yml`).

## Conventions

- **API errors** always have the shape `{"error": {"code", "message", "details?"}}`. Raise
  `AppError` subclasses from `app/core/errors.py` in services; the frontend receives them as
  `ApiError` from `src/api/client.ts`.
- **Logs** are JSON, one line per event, and every request carries an `X-Request-ID`.
- **Secrets** go in `backend/.env` (ignored by git), never in code.
- **Branches**: one per ticket, e.g. `feature/SS-42-report-photos`, merged by pull request.

## GenAI declaration

The Phase 0 foundation (project structure, tooling, configuration, Docker and CI setup, the
logging and error-handling modules, the API client and the layout shell) was produced with the
help of an AI assistant (Claude). This must be declared in the signed GenAI declaration attached to
each submission. Feature code from Phase 1 onwards is written by the group.
