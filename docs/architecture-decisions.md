# Architecture decisions

Short records of the main technical choices and why they were made. Add a new entry whenever a
decision is made or changed; these feed the "design decisions" parts of the reports and video.

Format: context, decision, consequences.

---

## AD-01: One FastAPI backend that also runs the AI models

- **Context:** The AI features (risk model, report classifier) are written in Python. A separate
  AI service would mean two deployments, a network hop and extra failure points.
- **Decision:** A single FastAPI (Python) backend holds the API, business rules and AI module in
  one process.
- **Consequences:** Simple to deploy and test. If model scoring ever gets slow, the `ai/` package
  can be moved to its own worker without changing the API.

## AD-02: React + TypeScript single-page app built with Vite

- **Context:** The product is dashboard-heavy (risk rankings, S-curves, approval queues), and the
  report pages must also work in a phone browser.
- **Decision:** React with TypeScript, Vite for builds, Tailwind CSS for styling.
- **Consequences:** Type checking catches mismatches with the API early. Tailwind makes a
  responsive layout quick without a component library.

## AD-03: PostgreSQL with SQLAlchemy and Alembic

- **Context:** The data is strongly relational (project → BOQ items → requests → approvals → POs)
  and the business rules depend on constraints.
- **Decision:** PostgreSQL, accessed through the SQLAlchemy ORM, with schema changes managed by
  Alembic migrations.
- **Consequences:** Parameterised ORM queries protect against SQL injection. Every schema change is
  a reviewed, versioned file. CI runs `alembic check` so a model change without a migration fails.
  Constraint names follow a fixed naming convention (`app/models/base.py`) so migrations can
  refer to them.

## AD-04: One error format for the whole API

- **Context:** The frontend needs to show useful messages, and the brief marks error handling
  ("without crashes"). Stack traces must never reach users (security).
- **Decision:** Every error is returned as `{"error": {"code", "message", "details?"}}`. Services
  raise `AppError` subclasses; unexpected exceptions are logged with a request ID and returned as a
  generic 500.
- **Consequences:** The frontend has one place to handle errors (`ApiError`). Each log line can be
  traced back to a request through its `X-Request-ID`.

## AD-05: Structured JSON logs

- **Context:** The app needs an audit trail and logs that can be searched when something goes
  wrong in the deployed demo.
- **Decision:** Log every request as one JSON line (method, path, status, duration, request ID).
- **Consequences:** Logs can be filtered by request ID or status code. Business audit records
  (approvals, logins) still go in the `audit_logs` table, starting in Phase 1.

## AD-06: React Query for server data, a typed fetch wrapper for requests

- **Context:** Most frontend state is data from the API (projects, reports, risk scores).
- **Decision:** React Query caches and refreshes server data. A small typed wrapper around `fetch`
  (`src/api/client.ts`) handles JSON and errors. Client-only state (if needed) goes in Zustand.
- **Consequences:** Less hand-written loading and caching code. 4xx errors are not retried because
  the answer would not change.

## AD-07: Docker Compose for local development, GitHub Actions for CI

- **Context:** Group members and markers must be able to run the project easily, and the brief
  rewards scalability and repeatable deployment.
- **Decision:** `docker compose up` starts PostgreSQL, the backend and the frontend. GitHub Actions
  runs linting, type checks, migrations and tests on every pull request.
- **Consequences:** Nobody has to install PostgreSQL by hand, and broken code is caught before it
  reaches `main`. The same backend image is the starting point for deployment in Phase 13.

## AD-08: Ruff and oxlint for linting

- **Context:** The guide names Ruff and ESLint. The current Vite React template ships with oxlint
  instead of ESLint.
- **Decision:** Ruff for Python (lint and format), oxlint for TypeScript.
- **Consequences:** Both are fast enough to run on every save. oxlint covers the same core rules as
  ESLint's recommended set; ESLint can be added later if a rule is needed that oxlint lacks.
