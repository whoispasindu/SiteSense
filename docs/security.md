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
| Passwords | argon2id, 12–128 chars, deny-list, no email name; admin-issued one-time passwords must be changed | `core/security.py` | `test_security_unit.py`, `test_temporary_password_must_be_changed_before_anything_else` |
| Sessions | 15-min JWT in memory; rotating refresh token (hashed, httpOnly, Secure, SameSite=Strict, path-scoped); reuse detection; 30-day cap; `session_version` revocation | `services/auth_service.py`, `api/v1/auth.py` | `test_auth_api.py`, browser check: tokens invisible to scripts, nothing in web storage |
| Brute force | Lockout after 5 failures (15 min), per-IP rate limits on sign-in, refresh and password change, uniform error and timing | `auth_service.login`, `core/rate_limit.py` | TC-09 test, rate-limit tests |
| Authorisation | Permission table; `require_permission` on every endpoint; site scoping returns 404 | `core/permissions.py`, `api/deps.py` | `test_role_matrix.py` (every endpoint × every role), `test_site_scoping.py` |
| CSRF | SameSite=Strict cookie read only by auth endpoints, plus Origin / Sec-Fetch-Site checks | `require_trusted_origin` | `test_cross_site_login_is_blocked` |
| Audit | Sign-ins, failures, lockouts, logouts, password changes, admin actions; append-only by grants | `services/audit.py`, migration 0002 | `test_database_guards.py` |
| Open redirect | Post-sign-in `next` must be a same-origin path | `safeNextPath` | `auth.test.tsx` |
| File uploads | BOQ import: .xlsx/CSV checked by content; 5 MB, 5,000 rows, 30 columns; zip-bomb and macro checks before opening; XML via defusedxml; formulas never evaluated; larger body limit on the upload route only; file never written to disk | `services/boq_import.py`, `BodySizeLimitMiddleware` overrides | `test_boq_import.py`, `test_projects_api.py` |
| Money | NUMERIC columns with check constraints; Decimal end to end; decimal strings in JSON | `models/project.py`, `schemas/project.py` | `test_projects_api.py` |
| Photo uploads | Magic-byte check (JPEG/PNG/WebP), full decode under a 50 MP budget, re-encode to a fresh JPEG with no metadata (GPS removed); random server-generated storage keys checked against a pattern; 10 MB, 12 per report, per-IP rate limit; files outside any served folder; served only through an authenticated, site-scoped endpoint | `services/photos.py`, `integrations/storage.py`, `api/v1/reports.py` | `test_report_photos.py` |
| Outbound calls (SSRF) | Weather: fixed https host, query built from stored coordinates only, redirects refused, 64 KB cap, response schema-validated, 5 s timeout; failures fall back to the cache | `integrations/weather.py`, `services/weather.py` | `test_weather.py` |
| Notifications | Per-user only (others answer 404); links restricted to in-app paths by service and database constraint; de-duplicated reminders | `services/notification_service.py`, migration 0005 | `test_reminders_notifications.py`, `reports.test.tsx` |
| Supply chain | Pinned deps, Dependabot (pip, npm, actions, docker), pip-audit, npm audit, dependency review, CodeQL `security-extended`, actions pinned to SHAs, `permissions: contents: read`, `persist-credentials: false` | `.github/` | CI |

## Phase 4 review: 2026-10-10

**Scope:** the whole repository at the end of Phase 4 (daily reports, photo uploads, weather,
scheduled reminders, notifications, and their screens). Design decisions are in
[ADR 0007](adr/0007-daily-reports-photos-weather.md).

### OWASP Top 10 (2021) walk-through

| Risk | Phase 4 status |
| --- | --- |
| A01 Broken access control | All 12 new endpoints are in the role matrix, which runs every endpoint as every role. Reports, photos and weather are reached only through the project's site scope (404 outside it). Editing, adding or removing photos is limited to the author on the day of submission. Notifications belong to one user; anyone else gets 404. **Fixed:** task progress inside a report did not check the progress permission itself, so it relied on only engineers filing reports. It now requires `schedule:progress` like a direct update, with a regression test. |
| A03 Injection | Report text is stored as text and rendered by React (escaped). Notification links can only be in-app paths, enforced by the service and by a `CHECK` constraint. Photo storage keys never come from the client and are pattern-checked, so path traversal is impossible. |
| A04 Insecure design | One report per project per day is enforced by a unique constraint, so a race between two submits ends in a clean 409. Reports lock at midnight after submission, and every create, correction and photo change is audited. Reminders are idempotent (unique `dedupe_key`), so several workers or a manual run never double-send. |
| A05 / DoS | Photos are capped at 10 MB, 50 megapixels and 12 per report, with a per-IP upload limit of 60/min. The larger body limit applies only to the photo route. A worst-case 12 MP noise image processes in 0.5 s. Report text fields are capped at 5,000 characters, the list at 100 per page and notifications at 30 per request. |
| A06 Vulnerable components | pip-audit **0** (new: Pillow 12.3.0, APScheduler 3.11.3), npm audit **0**. |
| A08 Software and data integrity | Uploaded files are never trusted: they are decoded, verified and re-encoded. The weather response is size-capped and schema-validated, and values outside physical ranges are dropped. |
| A09 Logging and monitoring failures | New audit events: `report.created` (with tasks updated), `report.updated` (fields), `report.photo_added`, `report.photo_deleted`. Weather outages, reminder runs and failed jobs are logged. |
| A10 SSRF | The only outbound call (Open-Meteo) uses a fixed host and refuses redirects; coordinates come from validated site records. |

### Privacy (PDPA)

- EXIF is removed on upload (by the browser, then always by the server), so photos do not carry
  the phone's GPS position or device details.
- Photos are visible only to signed-in staff assigned to the site, and the form asks engineers
  to photograph the work, not people.
- Client access to photos is a Phase 12 decision (approved photos only).

### Verification beyond unit tests

- **Mutation checks:** removing the author rule, the site scope on reports, the future-date
  rule, the "report already filed" condition in reminders, the owner check on notifications, or
  the stale-cache fallback each makes a test fail. Disabling the magic-byte check alone does not:
  the decoded format must still match a supported signature, so non-images are still rejected.
  That second layer is intended.
- **Browser, as the site engineer:** filed today's report with the weather pre-filled from the
  live forecast, a progress update and a photo, then saw it in the history. **As the PM:** saw
  the "report filed" notification and the 18:00 reminder for the site without a report.
- **Live weather:** `refresh-weather` fetched real forecasts for all three demo sites.

### Findings fixed during the review

1. **Progress permission not checked inside reports**, described above.
2. **The report page showed 0 photos right after submitting** (the cached report predated the
   uploads). The page now refetches after uploads.
3. **Reminder text said "the site engineer has been reminded"** when no engineer was assigned.
   It now says so plainly.

## UI redesign review: 2026-10-09

A front-end change only ([ADR 0006](adr/0006-clean-site-office-ui.md)): no API, permission or
data changes.

- **CSP unchanged.** The pre-paint theme script is a same-origin file
  (`public/theme-init.js`), so `script-src 'self'` still holds with no inline script or hash.
  Charts and bars set their sizes through the DOM style API, which `style-src 'self'` allows.
- **Local storage holds only the theme choice** (`sitesense-theme`). The script compares the
  stored value with fixed strings and never writes it into the page. Reads and writes are
  wrapped in try/catch, so blocked storage falls back to the system theme. Tokens stay in memory
  and in the httpOnly cookie, as before.
- **No new data paths.** The dashboard uses the existing, site-scoped `/projects` and
  `/schedule/summary` endpoints. Chart labels are rendered as text by React, never as HTML.
- **Dependencies:** added `@fontsource-variable/ibm-plex-sans` 5.3.0 (self-hosted font, SIL OFL)
  and removed Archivo. `npm audit` reports 0 vulnerabilities.
- **Checks:** ESLint (including jsx-a11y), strict TypeScript, 120 Vitest tests and a production
  build pass. Light and dark themes were checked in the browser at desktop and 375 px widths,
  with no horizontal page scroll.

## Phase 3 review: 2026-10-09

**Scope:** the whole repository at the end of Phase 3 (programme tasks, planned and actual
progress, S-curve, schedule screens).

### OWASP Top 10 (2021) walk-through

| Risk | Phase 3 status |
| --- | --- |
| A01 Broken access control | All 6 new endpoints are in the role matrix. Field-level rule: site engineers may change a task's `percent_complete` and nothing else (403 otherwise), tested and mutation-checked. Tasks are reached only through their project's site scope (404 outside it). |
| A04 Insecure design | Every progress change writes a dated snapshot, so the actual curve is history, not a recalculation that could be quietly rewritten. Changes are audited with from/to values. |
| A05 / DoS | **Fixed:** project and task dates had no upper bound, so a task ending in 9999 would make each S-curve request compute about 400,000 weekly points. Spans are now capped at 15 years (projects and tasks), tasks per project at 500, and the snapshot lookup uses binary search. Worst case: 787 points × 500 tasks in 0.17 s. |
| A06 Vulnerable components | pip-audit **0**, npm audit **0** (new: recharts). |
| A09 Logging and monitoring failures | `task.created`, `task.updated`, `task.progress_updated` (from/to) and `task.deleted` are audited. |

### Verification beyond unit tests

- **Mutation checks:** removing the progress-only rule, the snapshot write or the 15-year cap
  each makes a test fail.
- **Browser, as the PM:** the portfolio schedule (furthest behind first), the S-curve with
  history, Today and contract-end lines, and the programme timeline. Changing a task's progress
  moved the actual line at once (the Phase 3 "Done when"); the change was then reverted.

### Findings fixed during the review

1. **Unbounded dates (DoS)**, described above.
2. **The progress input rejected decimals** (`step=5`): the browser silently blocked "71.2". Now
   `step="any"`, with a regression test.
3. **Page-wide horizontal scroll:** a screen-reader-only label inside a scrollable table escaped
   its container. Every horizontal scroll container is now a positioning context.
4. **Timeline month labels overlapped** at the year boundary.
5. **Tests that named a specific "unbuilt" module** broke at every phase. They now derive it from
   the build plan.

## Phase 2 review: 2026-10-09

**Scope:** the whole repository at the end of Phase 2 (projects, BOQ import, budget lines, and
their screens), plus a re-check of everything from Phases 0 and 1.

### OWASP Top 10 (2021) walk-through

| Risk | Phase 2 status |
| --- | --- |
| A01 Broken access control | All 7 new endpoints are in the role matrix (every role, plus unauthenticated). Project lists and single projects are filtered by site; another site's project answers 404. A PM cannot open a project on a site they are not assigned to. A budget line is only reachable through its own project. Clients have no project access (their cost-free portal is Phase 12). |
| A03 Injection | ORM only. Search escapes LIKE wildcards (`%`, `_`, `\`), which a test proves. Uploaded text is length-checked and stored as data, never interpreted. |
| A04 Insecure design | BOQ import is validate-first (dry run), all-or-nothing, and audited. A project's code and site cannot be changed after creation, because the site decides who can see it. |
| A05 Security misconfiguration | The larger body limit applies only to the upload route; every other route keeps the 1 MB cap (tested). |
| A06 Vulnerable components | pip-audit **0**, npm audit **0** (new: openpyxl, defusedxml, python-multipart). |
| A08 Software and data integrity failures | Hostile spreadsheets: zip bombs, too many parts, macro workbooks, old binary .xls, fake .xlsx, XML entity expansion and formula cells are all refused or neutralised, each with a test. |
| A09 Logging and monitoring failures | `project.created`, `project.updated`, `boq.imported` (file, counts, total) and `budget_line.updated` (from/to) are audited. |

### Verification beyond unit tests

- **Load:** a 5,000-row workbook parses in 0.5 s and imports in 0.7 s; imports are rate-limited
  to 20 per minute per client.
- **Browser:** signed in as the QS, the project list showed only the QS's sites. Checked the
  overview KPIs and section bars, BOQ expansion, and a real multipart upload through the dev
  proxy, whose dry run reported the bad row and imported nothing.

### Findings fixed during the review

1. **Layering:** site-scoping helpers lived in the API layer, so services had to import from it.
   Moved to `app.core.scoping`.
2. **A loop-variable closure** in the parser (Ruff B023) could have read the wrong header if
   reused. Rewritten as an explicit helper.
3. **Wording:** "1 rows need fixing" and "Import 1 items" corrected.
4. **Flaky tests under load:** asynchronous waits raised for slower CI machines.

### Open items

| Item | Phase |
| --- | --- |
| Refuse or reconcile a BOQ re-import once material requests reference its items | 5 |
| Neutralise cells that start with `= + - @` in any CSV/Excel export (formula injection) | when exports arrive (11) |
| Users and projects lists are not paginated server-side yet | 13 |

## Phase 1 review: 2026-10-09

**Scope:** the whole repository at the end of Phase 1 (authentication, roles, users, sites,
audit log, and the web screens for them).

### OWASP Top 10 (2021) walk-through

| Risk | Phase 1 status |
| --- | --- |
| A01 Broken access control | Every endpoint declares its permission; the role-matrix test calls all 12 protected endpoints as all 6 roles and unauthenticated. Refused calls are proven side-effect free. Site scoping hides unassigned sites with 404. The web menu and route guards mirror the API but are not relied on. |
| A02 Cryptographic failures | argon2id passwords; refresh tokens stored as SHA-256 hashes; JWT algorithm pinned to HS256 with a 32+ character secret that production refuses to start without. Cookie is Secure and httpOnly. |
| A03 Injection | ORM only; all inputs are Pydantic models with `extra="forbid"`; the audit filter is pattern-validated. Emails validated and lower-cased, with a database check constraint. |
| A04 Insecure design | Admins never choose passwords; last-admin and self-lockout rules; role change and deactivation revoke sessions instantly; refresh-token reuse burns the whole session family. |
| A05 Security misconfiguration | Production additionally refuses the default JWT secret and an insecure cookie. |
| A06 Vulnerable components | pip-audit: **0**; npm audit: **0** (new: argon2-cffi, PyJWT, email-validator). |
| A07 Identification and authentication failures | Lockout (TC-09), rate limits, uniform failure answers with a dummy hash for unknown emails, forced change of temporary passwords, password policy mirrored in the UI. |
| A08 Software and data integrity failures | Audit log is append-only for the app role (UPDATE/DELETE revoked), verified by tests; roles table is read-only for the app. |
| A09 Logging and monitoring failures | Security events go to the audit log with actor, IP and user agent, and are visible to admins in the UI. Passwords and tokens never reach logs or audit details. |
| A10 SSRF | Still no outbound calls. |

### Verification beyond unit tests

- **Mutation checks:** the lockout, permission check, refresh-family revocation, site scoping and
  session-version check were each removed in turn; every removal made a test fail.
- **Browser walk-through** (local API + Vite against the Docker database): sign-in redirect with
  `next`, admin menu, user creation with one-time password, audit log, session restore on reload,
  tokens unreadable by page scripts, sign-out, engineer menu, 403 page, phone layout.

### Findings fixed during the review

1. **Demo and test accounts used a reserved `.test` domain** that the email validator rejects,
   so the seeded users could never have signed in. Switched to the RFC 2606 `.example` domain.
2. **Site codes typed in lower case were rejected** because the format check ran before
   upper-casing. Normalisation now runs first.
3. **Audit entries in one transaction shared a timestamp** (database `now()`), making order
   ambiguous. Entries now take the application clock.
4. **After sign-in, the user lost the page they asked for**: the signed-out guard redirected to
   `/` before the `next` path was followed. The guard now follows a safe `next` itself.
5. **Explicit sign-out kept `?next=`**, so the next person signing in on a shared device was
   sent to the previous user's page. A deliberate sign-out now starts clean.
6. **The top bar named pages the user could not open** (on the 403 page). It now checks
   permissions.
7. **Password change had no rate limit**, letting a stolen access token be used to guess the
   current password. Now rate-limited.
8. **Sign-in from `127.0.0.1:5173` would be refused** by the origin check in development. Added to
   the development origin list.
9. **Temporary passwords contained look-alike characters** (0/O, 1/l/I), error-prone when read
   out by phone. The alphabet now excludes them.

### Open items

| Item | Phase |
| --- | --- |
| Shared rate-limit store (Redis) when running more than one API instance; set `FORWARDED_ALLOW_IPS` behind a proxy so limits apply per real client IP | 13 |
| TOTP two-step verification for admin, PM and procurement (`mfa_enabled` and `MFA_ROLES` ready) | 13 |
| Self-service password reset by email (needs the email service) | 11 |
| Users screen loads the first 100 users; add server-side paging when a company exceeds that | when needed |
| Accepted risk: the "account locked" message reveals that an account exists after 5 failed, rate-limited, audited attempts (see ADR 0005) | — |

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
