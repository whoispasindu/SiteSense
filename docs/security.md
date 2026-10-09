# Security

Every phase ends with a security and stability review of the whole app. Results are recorded
here, newest first. The baseline design is in [ADR 0003](adr/0003-security-baseline.md).

## Controls in place

| Area | Control | Where | Verified by |
| --- | --- | --- | --- |
| Secrets | Env-only, `SecretStr`, `.env` git-ignored, no credentials in `alembic.ini` | `core/config.py` | Gitleaks over full history (CI), `test_secrets_are_hidden_in_repr` |
| Config | Production refuses debug, wildcard/plain-HTTP origins, example passwords | `Settings._reject_unsafe_production_config` | `test_unsafe_production_settings_are_rejected` |
| Database | Least-privilege runtime role; separate migration owner; statement timeout | `infra/postgres/init/01-roles.sh`, `core/database.py` | CI "Least-privilege check" step |
| Errors | One envelope; no stack traces, exception text or submitted values | `core/errors.py`, `RequestContextMiddleware` | `test_errors.py` |
| Headers | CSP `default-src 'none'`, `frame-ancestors 'none'`, nosniff, DENY, no-referrer, COOP/CORP, `no-store`, HSTS in prod | `SecurityHeadersMiddleware`, `frontend/nginx.conf` | `test_middleware.py` |
| Request limits | Body size limit (declared and streamed), trusted hosts, CORS allow-list | `core/middleware.py`, `main.py` | `test_middleware.py` |
| Logging | JSON logs, request IDs, sensitive keys redacted, no query strings, uvicorn access log off | `core/logging.py` | `test_logging.py` |
| Log/header injection | Caller `X-Request-ID` accepted only if `[A-Za-z0-9._-]{8,64}` | `core/request_context.py` | `test_unsafe_incoming_request_id_is_replaced` |
| IDs | Random UUID primary keys | `models/base.py` | review |
| API docs | `/api/docs` and OpenAPI disabled in production | `main.py` | `test_api_docs_are_disabled_in_production` |
| Frontend | `dangerouslySetInnerHTML`, `innerHTML`, `eval` banned by lint; every response Zod-validated; same-origin paths only; `redirect: "error"`; crash page shows no details | `eslint.config.js`, `api/client.ts`, `RouteErrorPage.tsx` | ESLint in CI, `client.test.ts`, `RouteErrorPage.test.tsx` |
| Containers | Non-root users (API uid 10001, node, nginx-unprivileged); dev ports bound to 127.0.0.1 | Dockerfiles, `docker-compose.yml` | review |
| Supply chain | Pinned deps, Dependabot (pip, npm, actions, docker), pip-audit, npm audit, dependency review, CodeQL `security-extended`, actions pinned to SHAs, `permissions: contents: read`, `persist-credentials: false` | `.github/` | CI |

## Phase 0 review: 2026-10-09

**Scope:** the whole repository at the end of Phase 0 (backend skeleton, database bootstrap,
web shell, Docker, CI).

### OWASP Top 10 (2021) walk-through

| Risk | Phase 0 status |
| --- | --- |
| A01 Broken access control | No data endpoints yet; only public health checks. Auth and `require_role` / site scoping arrive in Phase 1, with a role-matrix test for every endpoint. Random UUID keys are ready. |
| A02 Cryptographic failures | No secrets stored yet. HSTS in production; secrets typed and never logged. Password hashing (argon2) is Phase 1. |
| A03 Injection | SQLAlchemy only, no string-built SQL (Ruff `S608` enforces this). Frontend bans raw HTML injection. Request IDs sanitised. |
| A04 Insecure design | Layering keeps business rules out of routers; ADRs record decisions; least-privilege database. |
| A05 Security misconfiguration | Unsafe production config fails startup; docs off in production; strict headers on every response including 500s; `Server` header removed. |
| A06 Vulnerable components | pip-audit: **0 known vulnerabilities**. npm audit: **0 vulnerabilities**. Dependabot configured. |
| A07 Identification and authentication failures | Not applicable until Phase 1 (lockout, token rotation, MFA planned). |
| A08 Software and data integrity failures | Actions pinned to commit SHAs; lockfile installs (`npm ci`); dependency review on PRs. |
| A09 Logging and monitoring failures | Structured logs with request IDs; every unhandled exception logged with traceback server-side. Audit log table is Phase 1. |
| A10 SSRF | No outbound calls yet. Frontend client refuses non-relative paths. External adapters (weather, LLM) will use fixed base URLs. |

### Findings fixed during the review

1. **Settings could diverge from the database actually used.** The engine was built from the
   global environment, not from the settings passed to `create_app`, so a test or tool could
   silently hit a different database. Fixed: each app owns a `Database` on `app.state`
   (`test_each_app_uses_its_own_database_settings`).
2. **Migration URL was not checked for the example password in production.** Fixed and tested.
3. **Validation errors echoed submitted values** (Pydantic's default `input` field), which
   would reflect passwords into responses. Fixed before merge: details keep only field,
   message and type.
4. **Unhandled exceptions bypassed security headers** when handled by Starlette's outermost
   error middleware. Fixed: `RequestContextMiddleware` produces the 500 inside
   `SecurityHeadersMiddleware`.
5. **Dev container permissions**: the frontend image ran as `node` but root owned
   `node_modules`. Fixed by building as `node` throughout.
6. **Database healthcheck could pass during init** (socket-only temporary server). Fixed by
   checking over TCP.
7. **Tests depended on the developer's shell.** Ambient `SITESENSE_*` variables changed test
   outcomes. Fixed with an autouse fixture that isolates the environment and ignores `.env`.
8. **Host-side database connections stalled on Windows.** `localhost` resolved to IPv6 `::1`
   first while Docker binds only `127.0.0.1`, so each connection waited for a timeout. Host
   URLs now use `127.0.0.1`.

### Stability checks

- Backend: Ruff, Ruff format, mypy `--strict`, pytest (coverage gate 90%).
- Frontend: ESLint (strict type-checked + jsx-a11y strict), `tsc`, Vitest (coverage gates), production build.
- Migrations: `upgrade head`, `check` (no drift), `downgrade base`, `upgrade head` in CI.
- Full stack started with `docker compose up --build` and exercised in a browser.

### Open items, owned by later phases

| Item | Phase |
| --- | --- |
| Authentication, lockout after 5 attempts, refresh rotation, audit log | 1 |
| Rate limiting on auth endpoints | 1 |
| Upload type and size checks, photo access control | 4 |
| TOTP for PM and procurement, full rate limiting, load test | 13 |
| Enable branch protection, secret scanning and push protection on GitHub (`scripts/github-bootstrap.sh`) | now, by the repo owner |

> **Private repository note.** While the repository is private on a free plan, GitHub does not
> offer code scanning, dependency review, secret scanning or branch protection. The CodeQL and
> dependency-review jobs skip themselves on private repositories; Gitleaks, pip-audit and npm
> audit still run on every pull request. Making the repository public (as the product guide
> recommends) turns all of them on at no cost.
