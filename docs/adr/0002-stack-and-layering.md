# ADR 0002: Stack and backend layering

- Status: accepted
- Date: 2026-10-09

## Context

The product needs complex dashboards, a strict rules engine and tabular ML in the same system,
built by one developer.

## Decision

- **Frontend:** React + TypeScript + Vite + Tailwind CSS. TanStack Query for server state; Zod
  for runtime validation of API responses and forms.
- **Backend:** FastAPI + Pydantic + SQLAlchemy 2 + Alembic on Python 3.13. It is the same
  language as the ML stack, so models run in-process without a separate service.
- **Layering:** `api` (HTTP only) -> `services` (workflows; business rules as pure functions) ->
  `models`. Routers never contain business logic; rules are unit-testable without HTTP or a
  database.
- **Synchronous SQLAlchemy** sessions in FastAPI's threadpool. The workload is CRUD plus
  CPU-bound model inference, so async database I/O buys little and complicates the ML,
  scheduler and test code. Revisit if the Phase 13 load tests show connection-bound latency.

## Consequences

One language for API and AI, and simple deployment as a single container. Long-running work
(scoring, retraining) must go to background jobs, not request handlers.
