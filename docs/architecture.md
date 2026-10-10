# Architecture

SiteSense is a layered web application: a React single-page app talks to one FastAPI backend
over HTTPS with JSON. The backend holds the business rules and runs the AI models in the same
Python process, which keeps deployment simple. PostgreSQL stores relational data; site photos
live behind a storage adapter (a local folder today, S3-compatible storage later). External
services (weather, storage, and later LLM and email) sit behind adapter classes in
`backend/app/integrations` so they can be mocked in tests and swapped later. Scheduled jobs
(missing-report reminders at 18:00, weather refresh at 05:30) run in the API process with
APScheduler and are safe to run more than once ([ADR 0007](adr/0007-daily-reports-photos-weather.md)).

```
 Browser (React + TS)  --/api/v1-->  FastAPI
                                      |- api/           HTTP only: routing, auth dependencies, schemas in/out
                                      |- services/      workflows: gather facts, apply rules, save, audit, notify
                                      |- rules/         business rules as pure functions (docs/business-rules.md)
                                      |- ai/            risk model, NLP classifier, supplier model, briefing
                                      |- integrations/  weather, file storage, later LLM and email (adapters)
                                      |- models/        SQLAlchemy tables
                                      '- core/          config, database, logging, errors, middleware
                                                 |
                                                 v
                                           PostgreSQL 18
```

## Request path (Phase 0)

Middleware runs outermost first:

1. `SecurityHeadersMiddleware` adds security headers to *every* response, including errors.
2. `RequestContextMiddleware` assigns or accepts a safe `X-Request-ID`, logs one line per
   request, and turns any unhandled exception into a generic 500 in the standard envelope.
3. `BodySizeLimitMiddleware` rejects oversized bodies (declared or streamed) with 413.
4. `TrustedHostMiddleware` rejects unknown `Host` headers.
5. `CORSMiddleware` applies the explicit origin allow-list.
6. FastAPI routing and exception handlers (`AppError`, validation, HTTP errors).

## Error envelope

```json
{ "error": { "code": "forbidden", "message": "...", "request_id": "...", "details": [] } }
```

The frontend API client parses this envelope into an `ApiError`, so UI code handles one error
type whatever went wrong.

## Database roles

| Role | Used by | Can |
| --- | --- | --- |
| `postgres` | container admin | everything (never used by the app) |
| `sitesense_owner` | Alembic migrations | own and change the schema |
| `sitesense_app` | the running API | read and write rows only |

CI verifies that `sitesense_app` cannot create tables.

## Frontend

- `src/api`: typed fetch client with Zod validation, React Query hooks
- `src/components/layout`: the app shell (sidebar, top bar, mobile navigation dialog)
- `src/components/ui`: design-system primitives (Sheet, Button, StatusBadge, SectionHeading, Dialog, Icon)
- `src/pages`: one folder per screen
- `src/features`: feature modules (admin, projects, schedule, reports)

In development, Vite proxies `/api` to the backend, so the browser sees a single origin, as it
will in production.

Decisions and their reasons are recorded in [adr/](adr/).
