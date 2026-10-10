# Contributing to SiteSense

Thanks for helping. This guide covers local setup, the workflow, and what a pull request needs.

## Local setup

Follow [Run it locally](README.md#run-it-locally). `docker compose up --build` gives you the
database, API and web app with hot reload.

## Workflow

1. Pick or open an issue. Each build phase has a milestone.
2. Branch from `main`, named after the work: `feature/SS-42-report-photos`, `fix/SS-51-claim-rounding`.
3. Make small commits with clear messages.
4. Open a pull request against `main` and fill in the template. CI must pass before merging.

`main` is protected: no direct pushes, and every change arrives through a reviewed pull request.

## Code style

| Area | Tooling | Command |
| --- | --- | --- |
| Python | Ruff (lint + format), mypy strict | `ruff check . && ruff format . && mypy app tests` |
| TypeScript | ESLint (strict, type-aware, jsx-a11y), tsc | `npm run lint && npm run typecheck` |

Match the surrounding code: layering in the backend is `api` (HTTP only) → `services`
(workflow and business rules) → `models`. Business rules (BR-01 to BR-12) live in the services
layer as pure, separately tested functions.

## Tests are part of the change

- Every endpoint gets API tests, including the **forbidden** cases for each role.
- Every business rule gets unit tests, and you should check that they fail when the rule is broken.
- UI changes get Testing Library tests that query by role and accessible name.

## Security checklist for every pull request

- [ ] Authorisation is checked on the server for every new endpoint (never only in the UI)
- [ ] Input is validated with Pydantic (backend) and Zod (frontend)
- [ ] No secrets, tokens or real personal data in code, tests, fixtures or logs
- [ ] Errors use the standard envelope and leak no internal detail
- [ ] New dependencies are necessary, maintained, and pass `pip-audit` / `npm audit`

Report vulnerabilities privately; see [SECURITY.md](SECURITY.md).
