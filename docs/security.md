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
| Data on devices | The installable app's service worker stores only the app shell and fingerprinted files; it never stores or answers anything under `/api/`, and handles only same-origin GETs ([ADR 0018](adr/0018-installable-app.md)) | `frontend/src/pwa/sw.ts` | `src/pwa/sw.test.ts` (no API request answered or stored), `src/pwa/pwa.test.tsx` |
| Request limits | Body size limit (declared and streamed), trusted hosts, CORS allow-list | `core/middleware.py`, `main.py` | `test_middleware.py` |
| Logging | JSON logs, request IDs, sensitive keys redacted, no query strings, uvicorn access log off | `core/logging.py` | `test_logging.py` |
| Log/header injection | Caller `X-Request-ID` accepted only if `[A-Za-z0-9._-]{8,64}` | `core/request_context.py` | `test_unsafe_incoming_request_id_is_replaced` |
| IDs | Random UUID primary keys | `models/base.py` | review |
| API docs | `/api/docs` and OpenAPI disabled in production | `main.py` | `test_api_docs_are_disabled_in_production` |
| Frontend | `dangerouslySetInnerHTML`, `innerHTML`, `eval` banned by lint; every response Zod-validated; same-origin paths only; `redirect: "error"`; crash page shows no details | `eslint.config.js`, `api/client.ts`, `RouteErrorPage.tsx` | ESLint in CI, `client.test.ts`, `RouteErrorPage.test.tsx` |
| Containers | Non-root users (API uid 10001, node, nginx-unprivileged); dev ports bound to 127.0.0.1; production: read-only file systems, only the HTTPS proxy publishes ports, the database unreachable from the host, migrations as the owner in a one-shot container | Dockerfiles, `docker-compose.yml`, `docker-compose.prod.yml` | production stack run locally (Phase 13) |
| Passwords | argon2id, 12–128 chars, deny-list, no email name; admin-issued one-time passwords must be changed | `core/security.py` | `test_security_unit.py`, `test_temporary_password_must_be_changed_before_anything_else` |
| Sessions | 15-min JWT in memory; rotating refresh token (hashed, httpOnly, Secure, SameSite=Strict, path-scoped); reuse detection; 30-day cap; `session_version` revocation | `services/auth_service.py`, `api/v1/auth.py` | `test_auth_api.py`, browser check: tokens invisible to scripts, nothing in web storage |
| Brute force | Lockout after 5 failures (15 min), per-IP rate limits on sign-in, refresh and password change, uniform error and timing | `auth_service.login`, `core/rate_limit.py` | TC-09 test, rate-limit tests |
| Two-step sign-in | TOTP (RFC 6238) required for Company Admin, PM, QS and Procurement, optional for Site Engineer and Client; a code works once (last step stored); wrong codes count towards the lockout; challenge tokens (5 min, own type) never act as access tokens; secrets AES-GCM-encrypted and bound to the user; 10 recovery codes as keyed hashes, single use; admin reset audited and never for oneself; production refuses enforcement off, the development key or a key equal to the JWT secret | `core/totp.py`, `core/secretbox.py`, `services/mfa_service.py`, `auth_service.verify_second_factor` | `test_mfa.py` (RFC vectors, replay, lockout, reset), `test_config.py`, browser check |
| Request budgets | Every write: 120 a minute per signed-in user (per IP before sign-in or with a forged token); what-if and weekly PDF 20, report analysis 30, BOQ import 20, photo upload 60 per user; sign-in steps per IP | `api/deps.py: limit_writes, rate_limit`, `api/router.py` | `test_write_limits.py` (every write route in the schema, forged tokens, sign-in not blocked) |
| Demo mode | Only accounts the seed created skip two-step codes; emails only logged; nightly reset as the schema owner, refused outside demo mode and on a database without seeded demo accounts | `services/demo_service.py`, `integrations/email.py`, `core/scheduler.py` | `test_demo.py` |
| Authorisation | Permission table; `require_permission` on every endpoint; site scoping returns 404 | `core/permissions.py`, `api/deps.py` | `test_role_matrix.py` (every endpoint × every role), `test_site_scoping.py` |
| CSRF | SameSite=Strict cookie read only by auth endpoints, plus Origin / Sec-Fetch-Site checks | `require_trusted_origin` | `test_cross_site_login_is_blocked` |
| Audit | Sign-ins, failures, lockouts, logouts, password changes, admin actions; append-only by grants | `services/audit.py`, migration 0002 | `test_database_guards.py` |
| Open redirect | Post-sign-in `next` must be a same-origin path | `safeNextPath` | `auth.test.tsx` |
| File uploads | BOQ import: .xlsx/CSV checked by content; 5 MB, 5,000 rows, 30 columns; zip-bomb and macro checks before opening; XML via defusedxml; formulas never evaluated; larger body limit on the upload route only; file never written to disk | `services/boq_import.py`, `BodySizeLimitMiddleware` overrides | `test_boq_import.py`, `test_projects_api.py` |
| Money | NUMERIC columns with check constraints; Decimal end to end; decimal strings in JSON | `models/project.py`, `schemas/project.py` | `test_projects_api.py` |
| Photo uploads | Magic-byte check (JPEG/PNG/WebP), full decode under a 50 MP budget, re-encode to a fresh JPEG with no metadata (GPS removed); random server-generated storage keys checked against a pattern; 10 MB, 12 per report, per-IP rate limit; files outside any served folder; served only through an authenticated, site-scoped endpoint | `services/photos.py`, `integrations/storage.py`, `api/v1/reports.py` | `test_report_photos.py` |
| Outbound calls (SSRF) | Weather: fixed https host, query built from stored coordinates only, redirects refused, 64 KB cap, response schema-validated, 5 s timeout; failures fall back to the cache. Claude: the SDK's fixed API host, no user-supplied URL. SMTP: host from configuration only. Only these three modules may import a network client | `integrations/weather.py`, `services/weather.py` | `test_weather.py` |
| Approvals | Stage-and-role checks, segregation of duties (BR-04), state machine (invalid transitions 409), order prices more than 5% over approval go back to the PM (BR-14), row locks against double approval and quantity races | `rules/materials.py`, `services/materials_service.py`, `services/procurement_service.py` | `test_rules_materials.py`, `test_materials_api.py` |
| Notifications | Per-user only (others answer 404); links restricted to in-app paths by service and database constraint; de-duplicated reminders | `services/notification_service.py`, migration 0005 | `test_reminders_notifications.py`, `reports.test.tsx` |
| AI models | Model files are JSON data validated before use (structure, feature indexes, finite numbers, children after parents, size limits); no pickle/joblib loading; golden predictions prove the scorer matches training; CI retrains and checks the shipped model is reproducible | `ai/risk/model.py`, `ml/check_model.py` | `test_risk_model.py`, CI ML job |
| Large model files | ONNX weights live in a GitHub Release, not the repository; a committed manifest pins SHA-256 and size; `fetch_models.py` verifies before moving a file into place and the backend verifies again before onnxruntime parses it; plain file names only; 300 MB cap; mismatch or missing means the TF-IDF fallback; ONNX is an operator graph, not pickled code | `scripts/fetch_models.py`, `ai/nlp/transformer.py` | `test_report_transformer.py` (tamper, size, names, fallback, parity), CI fetches and runs them with `SITESENSE_REQUIRE_MODELS=1` |
| Outbound calls (ML runtime) | onnxruntime's telemetry to Microsoft is switched off before it is imported, in code and in the image | `ai/nlp/transformer.py`, `backend/Dockerfile` | `test_onnxruntime_telemetry_is_off_before_onnxruntime_is_imported`; checked in the container: no connection |
| Personal data in free text | Names of site people, the author, titled names and common Sri Lankan names (any case) become `[PERSON]` before classification and storage; only the weather client may call out of the server | `ai/nlp/text.py: redact`, `ai/nlp/names_lk.txt`, `services/issue_service.py` | `test_names_are_redacted_before_storage`, `test_report_nlp.py`, `test_outbound_calls.py`, ML `test_the_name_list_holds_no_word_from_the_report_data` |
| Contract changes | The contract value and planned end change only through approved variations once a project is under way; claims are calculated (BR-08) and a database check keeps their figures consistent; one claim waits at a time (partial unique index and a project lock); variation approval locks the variation, project and budget line and applies everything in one transaction, audited before and after; each variation keeps the BR-09 limit it was routed with; only the Company Admin changes a limit (reason audited) | `rules/claims.py`, `rules/variations.py`, `services/claim_service.py`, `services/variation_service.py`, `services/project_service.py: contract_locked`, migration 0010 | `test_rules_cost.py`, `test_contract_api.py`, `test_the_contract_changes_only_through_variations_once_under_way` |
| Client view | Clients reach only the projects the Company Admin links them to, never through a site; another client's project answers exactly like a missing one; client-only schemas built field by field (no budget, cost, rate, risk score or internal comment); approved and paid claims only; photos private until the PM shares them, and shared copies carry no metadata; only linked clients are notified (TC-07) | `services/client_access.py`, `services/portal_service.py`, `schemas/portal.py`, `services/variation_service.py: client_out`, migrations 0014-0015 | `test_client_portal.py` (two clients on one site, schema walk), `test_contract_api.py`, role matrix |
| Programme | Links only inside one project, never a loop (checked under a project row lock), lag 0–365, at most 2,000 per programme; one progress path refuses stopped tasks (BR-11) from the task list and daily reports; only a PM changes or clears a stop-work flag, audited; holidays only by the Company Admin, 2000 to 2100, audited; working-day arithmetic is bounded to 30 years and a network past it degrades with a warning; pour alerts read the forecast cache only and are de-duplicated by a fixed-length hash | `rules/calendar.py`, `rules/schedule.py`, `services/network_service.py`, `services/schedule_service.py: apply_progress`, `services/issue_service.py: set_stop_scope`, migration 0011 | `test_rules_schedule.py`, `test_network_api.py`, role matrix |
| Risk and supplier models | Plain JSON only (`sitesense-risk-v2`, `sitesense-supplier-v1`, the rain climate), each validated on load (kinds, sizes, finite numbers, node counts, range inputs, constants); golden rows prove the pure-Python scorers match training, including SHAP values; CI retrains both models and the climate table and checks they reproduce; the what-if planner stores and changes nothing and only the PM uses it; sign constraints mean no recovery action can worsen a forecast; the BR-12 override is PM-only, strict-boolean and audited | `ai/risk/model.py`, `ai/risk/climate.py`, `ai/supplier/model.py`, `services/risk_service.py: what_if`, `services/supplier_service.py`, `ml/check_model.py` | `test_risk_model.py`, `test_risk_whatif.py`, `test_supplier_api.py`, `ml/tests`, role matrix |
| AI briefing (LLM) | The model receives only allow-listed facts (`extra="forbid"` models of numbers, enumerated words, project codes and names, rule IDs), built per reader with their own visibility; a fixed instruction; JSON-schema output with codes limited to the reader's projects; answers validated and source counts made by the server; optional key held as `SecretStr` and never logged; one retry, 20 s timeout, rule-based fallback; at most one new answer per reader every 15 minutes | `ai/briefing`, `integrations/llm.py`, `services/briefing_service.py` | `test_briefing_leaks.py` (real SDK request captured for every role), `test_briefing.py`, `test_outbound_calls.py` |
| Email | Bodies built from the alert's title, a fixed sentence and links only, never its text; subject stripped of line breaks; TLS required in production and an https app link; transactional outbox, five attempts, errors recorded by type only; per-user choices audited; stop-work always sent; the weekly PDF only to cost roles; without SMTP, logged not sent | `services/alerts.py`, `services/channels.py`, `integrations/email.py`, `services/weekly_report.py` | `test_alerts_email.py`, `test_config.py` |
| Supply chain | Pinned deps, Dependabot (pip, npm, actions, docker), pip-audit, npm audit, dependency review, CodeQL `security-extended`, actions pinned to SHAs, `permissions: contents: read`, `persist-credentials: false` | `.github/` | CI |

## Phase 13 review: 2026-10-16

Scope:

- two-step sign-in (migration 0017) and its screens;
- request budgets on every write;
- demo mode and the nightly reset;
- the production setup (`docker-compose.prod.yml`, Caddy, the scheduler process);
- indexes (migration 0018) and the purchase-order list;
- the accessibility checks;
- the deployment guide.

This review also consolidates the OWASP Top 10 for the whole app, as Phase 13 asks.

### OWASP Top 10 (2021): the whole app

| Risk | What SiteSense does | Verified by |
| --- | --- | --- |
| **A01 Broken access control** | A permission on every endpoint, never a role name in a route. Site scoping answers 404, not 403. Clients reach only linked projects, and another client's records answer like missing ones. Segregation of duties (BR-04). The client portal uses separate schemas. Only the PM changes stop-work, handover and photo sharing. Users reach only their own notifications and two-step settings. The admin's two-step reset is never for their own account | `test_role_matrix.py` (every endpoint × every role), `test_site_scoping.py`, `test_client_portal.py` (two clients on one site, schema walk), mutation checks each phase |
| **A02 Cryptographic failures** | argon2id passwords. Refresh tokens and recovery codes stored only as hashes. Authenticator secrets AES-GCM-encrypted under a key derived per purpose and bound to the user's ID. HSTS and HTTPS-only origins, cookies and email links in production. No secrets in the repository | `test_security_unit.py`, `test_mfa.py` (secretbox, wrong owner), `test_config.py`, Gitleaks in CI |
| **A03 Injection** | SQLAlchemy with bound parameters only. Pydantic on every input (`extra="forbid"`, lengths, patterns, strict numbers). React text rendering, with `innerHTML` banned by lint. BOQ files parsed without formulas or macros. Email subjects stripped of line breaks. The LLM gets structured facts only | Schema tests per phase, `test_boq_import.py`, `test_briefing_leaks.py`, ESLint in CI |
| **A04 Insecure design** | Business rules (BR-01 to BR-14) in pure, tested functions. State machines refuse invalid steps (409). Row locks where two people can act at once. Contract changes only through approved variations. The what-if planner stores nothing. Demo mode cannot delete real data (the reset refuses a database without the seeded demo accounts) | `test_rules_*.py`, `test_contract_api.py`, `test_demo.py` |
| **A05 Security misconfiguration** | Production refuses to start with:<br>• debug on;<br>• wildcard or plain-HTTP origins;<br>• example passwords;<br>• development JWT or MFA keys, or an MFA key equal to the JWT secret;<br>• two-step enforcement off;<br>• insecure cookies;<br>• SMTP without TLS.<br>API docs are off in production. Strict security headers on the API and the web app. Production containers are read-only, and only the proxy is reachable | `test_config.py`, `test_middleware.py`, production stack run locally |
| **A06 Vulnerable and outdated components** | Pinned dependencies, Dependabot, pip-audit and npm audit on every pull request, dependency review, CodeQL | Final audit results below |
| **A07 Identification and authentication failures** | 15-minute access tokens held in memory, and rotating refresh tokens with reuse detection. Lockout after 5 failures, counting wrong second-factor codes too. Two-step sign-in for the roles that see costs or run the company: each code works once, and recovery codes are single use. Temporary passwords must be changed. Sessions end on password change, deactivation, role change or a two-step reset | `test_auth_api.py`, `test_mfa.py`, browser check of sign-in, the code step and a recovery code |
| **A08 Software and data integrity failures** | CI actions pinned to SHAs. Models are JSON data validated before use; the ONNX weights are pinned by SHA-256 and checked twice; no pickle. The audit log is append-only by database grants, and the demo reset needs the schema owner for exactly that reason | `test_risk_model.py`, `test_report_transformer.py`, `test_database_guards.py` |
| **A09 Security logging and monitoring failures** | JSON logs with request IDs and sensitive keys redacted. The audit log records sign-ins, failures, lockouts, two-step set-up, renewal, removal, resets and challenges, and every approval and admin action, with before and after. Scheduled-job failures are logged without stopping the scheduler | `test_logging.py`, audit assertions across the suites |
| **A10 Server-side request forgery** | Only three modules may call out: the weather client (fixed host, no redirects, size cap), the Claude SDK (fixed host) and SMTP (configured host). No user-supplied URL is ever fetched | `test_outbound_calls.py`, `test_weather.py` |

### What Phase 13 adds, by risk

- **A01.** The admin reset is in the role matrix (Company Admin only). The six `/auth/mfa`
  endpoints act only on the caller's own account (`test_mfa.py`): enrolment, renewal and removal
  are for one's own account only. Removal is refused for required roles. The admin reset is admin-only and never
  for oneself.
- **A04 / DoS.** Every write now has a budget per signed-in user. A test calls every write endpoint
  in the API schema with a budget of one and checks that the second call is refused. Forged tokens
  count against the IP, and each new forged token gets no fresh budget. The CPU-heavy budgets moved
  from per IP to per user. Sign-in keeps its own per-IP budgets and is not blocked by an office's
  other writes.
- **A07.** Two-step sign-in, as above. A right password with a code still due does not reset the
  failure count, so alternating the right password with guessed codes still locks the account.
- **A05.** The production setup runs read-only, with one HTTPS origin and the database hidden. It
  starts only with real secrets. Empty variables count as unset, so an optional setting left blank
  cannot fail validation.
- **Privacy.** Demo mode never sends email, even with a mail server configured. The demo addresses
  are not real mailboxes.

### Final audit results (16 October 2026)

| Check | Result |
| --- | --- |
| pip-audit: backend runtime and dev requirements | No known vulnerabilities |
| pip-audit: ML pipeline (`ml/requirements.txt`) | No known vulnerabilities |
| pip-audit: transformer training (`ml/requirements-transformer.txt`) | No known vulnerabilities; `torch` (CPU build from the PyTorch index) cannot be looked up on PyPI, as before |
| pip-audit: load test (`loadtest/requirements.txt`, Locust 2.46.5) | No known vulnerabilities |
| npm audit: frontend, with `axe-core` 4.13.0 added | 0 vulnerabilities |
| Secret patterns (Claude, AWS, GitHub keys, private keys) over tracked files and history | None found; `.env.prod` is git-ignored |
| Gitleaks over the full history, CodeQL `security-extended` | Run in CI on the pull request |

### Verification beyond unit tests

- **Mutation checks: 22 of 22** deliberate faults fail a test:
  - a TOTP code accepted twice;
  - the demo skip applied to every account;
  - required roles not made to enrol;
  - an admin resetting their own;
  - a recovery code reusable;
  - wrong codes not counted towards lockout;
  - the password alone signing an enrolled user in;
  - a challenge token accepted as an access token;
  - production allowing enforcement off, or an MFA key equal to the JWT secret;
  - demo mode sending real email;
  - the demo reset running outside demo mode or on a database without demo accounts;
  - the nightly reset scheduled outside demo mode;
  - writes unlimited;
  - the write budget removed from the API router;
  - a forged token getting a budget of its own;
  - sign-in counted in the write budget;
  - the weekly PDF's heavy budget removed;
  - the purchase-order list back to one query per order;
  - an image without alt text (axe);
  - faint text lightened below 4.5:1 (contrast test).

  The first backend run caught 13 of the 16 then written: one had a pattern that did not match the
  file and was rerun, and the two survivors showed missing tests:
  - nothing tried an MFA key equal to the JWT secret;
  - the forged-token test sent the same token every time.

  Both now have tests.
- **In the browser** (dev stack, demo mode off for the check):
  - the demo PM is sent to set-up before anything else;
  - the QR code and key show;
  - a code from the key enables two-step sign-in and shows ten recovery codes once;
  - the security page says it is required and offers no switch-off;
  - signing out and in asks for a code, and a recovery code signs in;
  - the audit log records the set-up, the challenge and the sign-in with `second_factor:
    recovery_code`.

  The dev data was then reset with `reset-demo`.
- **The production setup** (`docker-compose.prod.yml`), run locally:
  - with real secrets, the health check answers through Caddy over HTTPS, with HSTS and the strict
    CSP;
  - sign-in works on one origin;
  - `reset-demo` runs from the scheduler container as the owner (7,058 rows and 8 photo files
    removed, then reseeded);
  - the 5-minute, 50-user load test ran against it with 0 errors ([performance.md](performance.md)).
- **Accessibility:** axe on every tested screen, the contrast test and a keyboard pass
  ([accessibility.md](accessibility.md)).

### Findings fixed during the review

1. **The CPU-heavy budgets were per IP.** An office sharing one connection would have shared one
   report-analysis budget. They are now per signed-in user.
2. **The purchase-order list ran one query per order**, each also joining the request, project,
   item and requester. Found by the load test (95th percentile 1.1 s). The lines now load in one
   batch, with a test on the query count.
3. **Form field borders were about 1.6:1**, below WCAG 1.4.11's 3:1, in both themes. Fields now have
   a border colour of their own.
4. **Smaller accessibility findings from axe:**
   - error pages without a main landmark;
   - two unnamed complementary landmarks;
   - the demo banner outside any landmark;
   - an `aria-label` on a plain `div`;
   - photo alt text repeating the caption.
5. **The production health check was refused by the API's own host check.** It now sends an
   allowed host name.
6. **Optional settings left empty failed validation**, as Compose passes them as empty strings. They
   now count as unset.
7. **Two mutation survivors**, now covered by tests (above).

### Open items

- **No public demo yet** (no hosting budget). The deployment guide is ready.
- **Rate-limit counters are per API process.** With 4 workers, the per-IP sign-in budget is up to 4
  times looser. Behind two proxies (Vercel, then Render), the per-IP budgets rely on forwarded
  headers a client can pad. Lockout (in the database) and the per-user budgets are not affected. A
  shared store such as Redis is the fix if several API machines are needed.
- **A screen-reader session** belongs in Phase 14's user acceptance tests.

## Phase 12 review: 2026-10-13

Scope:

- the client portal (`/client/projects`, `/client/projects/{id}`, `/claims`, `/client/photos/{id}`);
- client access per project (`project_clients`, migration 0015) and its use in the Phase 8 variation pages;
- the published handover date and its reminder (`handover_publications`, migration 0014);
- photo sharing and milestones;
- the Company Admin's project links;
- the client's top navigation and the PM's Client view tab.

### OWASP Top 10 (2021) walk-through

- **A01 Broken access control.** The 11 new endpoints are in the role matrix for every role.
  - **Clients reach projects only through the links the Company Admin sets, never through a site.**
    The review found the demo had two clients' projects on one site. Site scoping would have shown
    each client the other's progress and payments, so the project owner chose links per project
    (below).
  - Every client path goes through `client_access`:
    - the portal pages and photos;
    - variation lists, views and decisions;
    - the notifications for a variation or a new handover date, and the emails built from them.
  - A project the client is not linked to, or a record on one, answers exactly like a record that
    does not exist: the same status, code and message. This is tested for every client endpoint with
    two clients on one site, so a client cannot even learn that another project exists.
  - Publishing or confirming the handover date, sharing photos and flagging milestones are for the PM
    only. Programme and report readers see the state.
  - Links are set only by the Company Admin, only on client accounts, and are cleared on a role
    change.
  - Mutation-checked (below).
- **A03 Injection.**
  - Reasons are 3 to 300 characters and milestone names 2 to 80 characters, stripped. All are
    rendered as text by React.
  - Share calls take at most 100 UUIDs and strict booleans.
  - Unknown fields are refused throughout.
- **A04 Insecure design.**
  - Client responses use their own schemas, never subclasses of internal ones, built field by field.
    A test walks every client response, fully populated, for 30 internal field names at any depth (the
    guide's schema test, TC-07). Others check that no client schema declares one, and that none extends
    an internal class.
  - Submitted and returned claims stay internal.
  - Reviews that confirm a date unchanged are internal.
  - Who shared or uploaded a photo is never sent to the client.
  - Photos are private by default. The bulk share is all-or-nothing and limited to the project's own
    photos.
- **A05 / DoS.** On demo data the client project view takes about 22 ms, claims 14 ms, the list 6 ms. Photos are capped at 60 per
  view and 100 per share call. A publication takes a row lock on the project, so two quick saves
  cannot interleave.
- **A08 Data integrity.**
  - Publications are append-only rows.
  - Every publish, confirm, share change and link change is audited, with before and after.
- **Privacy.**
  - Shared copies leave the server without EXIF, GPS, device, timestamps, XMP, ICC or comments. Each
    file is re-checked on the way out, as well as at upload.
  - The PM is reminded to check for faces and unsafe moments before sharing.
- **Outbound calls.** None added.

### Verification beyond unit tests

- **Mutation checks: 30 of 30** deliberate faults fail a test:
  - cancelled projects shown;
  - any project, variation or photo opened by ID;
  - every variation listed;
  - every client, or the site's clients, told about a project;
  - another project's photo shared through this one;
  - the client copy keeping its metadata;
  - uploads keeping the comment;
  - submitted claims shown;
  - retention summed instead of cumulative;
  - either reminder threshold disabled;
  - an unchanged date announced again;
  - milestones expected after the published date;
  - a milestone name without a milestone;
  - staff linked to projects;
  - links kept after a role change;
  - an internal field added to a client schema;
  - publishing or sharing opened to readers;
  - share changes not audited;
  - the photo clean-up writing on a dry run, or never writing;
  - the retention date ignoring the published date, the defects period or short months;
  - the defects period not strict, or unbounded.

  The first run caught 22. The survivor (sharing another project's photo) showed that the test only
  tried a random ID; it now tries a real photo of another project on the same site.
- **In the browser** (demo data):
  - the client opens straight into Havelock (their only project) under the top navigation, with
    progress, the published date and its reason, earlier dates, milestones, three shared photos (the
    newest stays private) and payments with the retention held;
  - the PM's Client view tab shows the date, suggestions and history;
  - sharing and unsharing a photo through the UI moves the count from 3 to 4 and back.

### Findings fixed during the review

1. **Clients saw every project on their site** (Phase 1 and 8 design). Fixed by linking clients to
   projects (migration 0015), applied to every client path, with the two-clients test.
2. **Uploads kept JPEG comments** (since Phase 4). Pillow writes `info["comment"]` back when saving,
   even with no arguments, so a comment such as a name or a place survived the "fresh" re-encode. The
   Phase 4 review had listed comments as dropped. The re-encode now clears the info dictionary, and a
   test uploads a commented JPEG and checks both sizes. Photos stored before the fix are cleaned on
   the way to clients, and `python -m app.cli strip-photo-metadata` re-encodes the stored files once
   (audited, safe to rerun). On the dev data it found nothing to clean, since the data was reseeded
   after the fix; with metadata planted in one photo it cleaned that file and then found nothing.
3. **Sharing could flush a half-updated photo.** Reading the user's ID mid-loop, after an earlier
   commit, triggered a query that flushed a row with `shared_with_client` set but no date. That broke
   the check constraint. The loop now reads its values first and runs with autoflush off. This was
   found by the demo seed.
4. **Old migrations were reformatted by a formatter run.** They were restored; past migrations are
   never edited.

### Open items

- Existing client accounts must be linked to their projects after upgrading (no automatic backfill:
  it would recreate the site leak).
- The retention due date is an expectation (published handover plus the defects period). Recording
  the actual handover date would make it exact.

## Phase 11 review: 2026-10-12

Scope:

- portfolio analytics (`GET /analytics/portfolio`);
- the daily briefing (`GET /briefing/today`): the facts, the rule writer, the Claude client and
  the fallback;
- email: the alert rules, the channel interface, the outbox, SMTP, the digest and the Monday job;
- the weekly PDF (`GET /reports/weekly.pdf`);
- email preferences (`GET`/`PUT /me/notification-preferences`, migration 0013);
- the new dashboard and the Email settings page.

### OWASP Top 10 (2021) walk-through

- **A01 Broken access control.** The 5 new endpoints are in the role matrix for every role.
  - The portfolio and briefing go to project readers, scoped to their sites. `cost` and `risk`
    are `null` without `cost:read` or `risk:read`.
  - The approval queue holds only what the reader acts on, never their own request or variation.
  - The PDF needs `cost:read`. It is mounted before the reports router, so the path is never read
    as a report ID (tested).
  - Preferences are the caller's own. The weekly PDF can't be taken by a role without cost access
    (422), and the Monday job checks again before queuing.
  - Mutation-checked (below).
- **A02 Cryptographic failures.** In production, SMTP must use STARTTLS or implicit TLS (with
  certificate checks from `ssl.create_default_context`) and email links must be https. The API
  refuses to start otherwise (tested). The Claude SDK talks https to its fixed host.
- **A03 Injection.**
  - Email subjects are stripped of line breaks (header injection, tested). Bodies are plain text.
  - Everything printed in the PDF is escaped before ReportLab's paragraph markup (tested with a
    project named `<b>& </para>`).
  - Preference fields are strict booleans and unknown fields are refused.
  - The model's answer is validated against a schema; codes it did not receive are rejected.
    React renders the bullets as text.
- **A04 Insecure design.**
  - The model receives only `Facts`: allow-listed, `extra="forbid"` models of numbers, enumerated
    words, project codes and names, and rule IDs. The leak test runs the real SDK client over a
    fake transport for every reading role and fails if any seeded secret appears in the HTTP body:
    report text, issue snippets, action summaries, notes, comments, variation descriptions, the
    client's name, site, task and supplier names, people's names and emails.
  - The model never states counts; the server computes them.
  - Emails carry a title, a fixed sentence and links, never an alert's body (comments, names,
    amounts, report text). Stop-work emails can't be switched off.
- **A05 / DoS.**
  - The model is called at most once per reader every 15 minutes, and after a failure not again
    for 10. One SDK retry, a 20 s timeout. The database connection is released while the model
    writes. Without a key nothing is called or stored.
  - On demo data: portfolio 12 to 98 ms, briefing 16 to 76 ms, PDF about 110 ms (4 KB). Each
    reader's site scope bounds the work.
  - The outbox sends 50 rows a minute with `SKIP LOCKED`, so two API workers never send the same
    email. It gives up after five attempts. Attachments are capped at 5 MB by a database check.
    The digest lists at most 25 titles.
- **A06 Vulnerable components.** New: `anthropic` 1.13.0 (official SDK), `reportlab` 5.0.1, and
  `types-reportlab` for development. pip-audit **0**, npm audit **0**.
- **A08 Data integrity.** The briefing cache is keyed by the facts' SHA-256 and the model name.
  Preference changes are audited (`user.notification_preferences_changed`, before and after), and
  so is each PDF download (`report.weekly_downloaded`). Outbox errors record the exception type
  only, never server text.
- **A09 Logging.** The key is a `SecretStr`. Logs say which source wrote a briefing and how many
  bullets, never the facts or the text. Without SMTP, emails are logged; their bodies hold no
  sensitive text by design.
- **Outbound calls.** `test_outbound_calls.py` now also watches `anthropic` and `httpx2`. It
  allows two new modules, with what each sends: `integrations/llm.py` (the facts) and
  `integrations/email.py` (alert emails).

### Privacy

- Project names go to Anthropic when a key is set (the project owner's decision). A project named
  after a person would carry that name, so the project form says: "Name projects by place or code,
  not by a person’s name."
- High-severity emails follow only the author's confirmed severity, and only when the author asks
  for the alert. The AI's suggestion alone alerts nobody, in the app or by email (tested).
- An email's title can name the person who decided a variation ("VO-0003 approved by …"). These go
  to colleagues on the same project (PM, QS, the raiser), never to the client, whose only email is
  "VO-… needs your decision".
- Digests and the PDF cover only the reader's own sites.

### Verification beyond unit tests

- **Mutation checks: 27 of 27** deliberate faults fail a test:
  - the email carrying the alert's body;
  - stop-work switchable;
  - an empty digest sent;
  - urgent alerts repeated in the digest;
  - the PDF by default for QSs, for every role, or twice a week;
  - failures retried for ever;
  - subject header injection;
  - an engineer opting into the PDF;
  - the client's name, cost or risk reaching the model;
  - facts accepting undeclared fields;
  - the model's unknown codes or own counts accepted;
  - a refusal taken as an answer;
  - either call limit removed;
  - approving your own request;
  - cost shown to every role;
  - other sites counted;
  - removed issue suggestions counted;
  - two points behind counted as behind;
  - the model range not moved from the budget;
  - the PDF route shadowed;
  - the download not audited.
- **In the browser** (demo data, no key, no SMTP):
  - the PM's dashboard shows the rule-based briefing with its label and source counts;
  - the KPIs, approval queue, alerts, weather for both sites, the risk ranking, the cost ruler with
    the model's range, and issues per week all render;
  - the PDF downloads with the session (401 without it);
  - a site engineer sees no cost, risk, PDF or approval queue;
  - the settings page saves, and stop-work stays locked on;
  - no horizontal scroll at 375 px.
- **The PDF** was opened and read: KPIs, the rule-based points, the project table with likely
  ranges, and issues per week.

### Findings fixed during the review

1. **The rule-based briefing went stale.** It was cached by its facts, so a change to the
   templates did not show until the facts changed. Without a key it is now written fresh on every
   request and not stored. The cache stays only to limit calls to the model.
2. **A tie read as a trend.** "Most often weather (1)" was written when three kinds had one issue
   each. Ties now read "spread across 3 kinds" (tested).
3. **Production could have sent mail in clear text, or links over http.** The production check
   refuses both now (tested).
4. **Old tests built production settings without an https app link.** They were updated, and the
   check stays strict.
5. **Download errors spoke of "the photo".** The blob helper now names what it loads.

### Open items

- SMS alerts for stop-work and high risk: roadmap. The `Channel` interface is ready.
- If the model provider's terms or region change, revisit sending project names. The facts can
  drop them for codes alone without other changes.

## Phase 10 review: 2026-10-12

Scope:

- risk model 1.2 (rain, issue #27) and 2.0: likely ranges, SHAP drivers, the straight line against
  the trees;
- the rain climate table;
- the what-if planner and the project Risk tab;
- the forecast handover shown two ways;
- the supplier on-time model and BR-12: critical-path items, the PM's override (migration 0012), the
  purchase-order and request screens;
- the demo seed's supplier history.

### OWASP Top 10 (2021) walk-through

- **A01 Broken access control.** The 5 new endpoints are in the role matrix for every role.
  - The what-if planner: only the PM (`risk:what_if`), on their own sites (404 otherwise).
  - Supplier on-time, supplier outlook and critical-path reads: material readers. Project-specific
    calls go through the site scope.
  - The critical-path override: only the PM. The role is checked before the request is looked up,
    so a non-PM learns nothing about whether it exists (fixed, below).
  - Mutation-checked (below).
- **A03 Injection.** Action ids are a closed list, each at most once, at most four. Costs are
  decimals of 15 digits with 2 places, never negative. The override is a strict boolean (fixed,
  below). Dates are parsed by the schema. Supplier names and reasons are rendered as text by React.
- **A04 Insecure design.**
  - The planner calculates only: no score, audit entry or project field changes (tested).
  - Every input an action changes has a fixed direction in both models, and a test runs every
    action and combination at both strengths against the shipped model: no forecast, and no end of
    a range, gets worse.
  - A blank action cost is called out, never treated as free.
  - BR-12 suggests only; it never blocks or changes an order.
  - Each range always contains its forecast, even where the fitted offsets cross.
- **A05 / DoS.**
  - A full what-if (four actions) takes about 100 ms on demo data; the supplier outlook about 16 ms.
  - Model files are refused beyond fixed sizes (trees, nodes, towns).
  - Supplier records are computed from order lines already due, company-wide, on each request. This
    is fine at the current scale; an aggregate table is the step if it grows.
- **A06 Vulnerable components.** scipy is now pinned for training only (the backend does not use it).
  pip-audit **0** (backend and ML), npm audit **0**.
- **A08 Data integrity.**
  - Model and climate files are data, never code. Golden rows in each model file are checked against
    the training code's own outputs, SHAP values included.
  - CI retrains the risk model, the supplier model and the climate table from the commit, and checks
    they match what ships.
  - The override is audited (`material_request.critical_path_set`, before and after).
- **Outbound calls.** None added. The rain climate is a local table, and `test_outbound_calls.py`
  still lists only the weather client.

### Privacy

- A supplier's record pools every site's orders. Users see the rate, its range and how many
  deliveries it rests on, never another site's orders.
- Forecasts and drivers are about projects, never people. The new inputs are rain and deliveries.

### Verification beyond unit tests

- **Mutation checks: 19 of 19** deliberate faults fail a test:
  - TreeSHAP not unwinding a repeated feature;
  - ranges not ordered around the forecast, ignoring the programme still to run, or not stored;
  - the crew cap removed;
  - an action's effect collapsed to one number;
  - entered costs not added, or blank costs treated as free;
  - the planner opened to every risk reader;
  - the 28-day floor on wet days ahead dropped;
  - every site given the national climate;
  - the supplier rate not smoothed;
  - overdue lines counted as on time, or lines due today counted;
  - the low-data and BR-12 lines moved;
  - near-critical tasks or the PM's override ignored;
  - anyone setting the override.

  The first run caught 18. The survivor (costs not added) exposed a test that derived its expected
  value from the response it checked; it now compares the same plan with and without the cost.
- **Exactness.** The backend's TreeSHAP values match LightGBM's to 1e-13 on the golden rows and on
  a 30-tree bagged model, and equal brute-force Shapley values on a small hand-built tree.
- **In the browser** (demo data):
  - the risk panel and dashboard ranking show every forecast with its range;
  - the Schedule tab shows both handover dates, with the disagreement note;
  - the planner with two actions and an entered cost moves the cost forecast by the cost's share of
    the budget;
  - procurement choosing an unreliable supplier for a critical-path request gets the BR-12
    suggestion, with both suppliers' chances and deliveries.

### Findings fixed during the review

1. **"yes" was accepted as true** for the critical-path override (lax boolean parsing). It is a
   strict boolean now; a test sends "yes" and gets 422.
2. **The override revealed whether a request exists.** Non-PMs got 404 for requests outside their
   view and 403 inside it. The role is now checked first: 403 for everyone who isn't the PM.
3. **The straight line's explanations were nonsense.** The five project-type columns always sum to
   one, duplicating the intercept, and the fit found huge cancelling coefficients. Predictions were
   right, drivers were not. One type is now the reference category.
4. **Quantile trees could not be constrained.** LightGBM refuses monotone constraints with the
   quantile objective, so a recovery action could have widened a range upwards. Ranges are now
   offsets around the forecast that depend on nothing an action changes.
5. **The supplier model's recorded hash didn't match its file** (Windows line endings, normalised by
   Git). Model and metrics files are now written with LF everywhere.
6. **Two inputs had no direction in the overrun model** (crew and the 14-day rain forecast), so an
   action touching them could, in principle, raise the cost forecast. Both are now constrained.

### Open items

- Real data: `RAIN_ALLOWANCE`, the supplier effects and the starting on-time rate are assumptions,
  stated as such in the model cards. Replace them with a contractor's records.
- The near-critical float for BR-12 is an environment setting (`SITESENSE_BR12_FLOAT_DAYS`), not a
  screen for the Company Admin.
- Supplier suggestions don't know which materials a supplier sells ("if they supply it").
- Supplier records are recomputed per request; aggregate them if order history grows large.

## Phase 9 review: 2026-10-11

Scope: task links and the critical path (`rules/schedule.py`), the working calendar and holidays
(`rules/calendar.py`, `services/calendar_service.py`), the forecast, BR-06 pour checks and alerts,
BR-11 stop-work scope and blocking, migration 0011, the Gantt, the stop-work picker and banner, the
holidays page, the working week on projects, and the demo seed.

### OWASP Top 10 (2021) walk-through

- **A01 Broken access control.** The 7 new endpoints are in the role matrix for every role.
  - The network: PM, QS and Site Engineer, on their own sites (404 otherwise).
  - Links: only a PM adds or removes them. Both tasks must be in the project, and a link on another
    site answers 404.
  - Stop-work scope: only a PM, on open flags, through the report's site scope. The task IDs given
    are checked against the project, whoever sends them, at confirmation and on change.
  - Holidays: only the Company Admin (`holidays:manage`).
  - Mutation-checked (below).
- **A03 Injection.** Holiday and task names are stored as text and rendered by React. The working
  week is checked by the schema (each ISO weekday once) and again by a database check.
- **A04 Insecure design.**
  - All progress goes through one function, so BR-11 cannot be bypassed by the daily report path;
    both paths are tested.
  - Loops are refused under a project row lock, so two links added at once cannot close one.
  - The critical path and forecast are calculated on the server; the browser only draws them.
  - Actual dates are kept by progress updates and guarded by database checks (started when there is
    progress, finished at 100%, in order).
- **A05 / DoS.**
  - At most 500 tasks (Phase 3) and 2,000 links per programme; lag 0–365; stop-work lists at most
    500 tasks; holiday names 80 characters.
  - Working-day counting is arithmetic and shifting jumps whole weeks. A 500-task, 15-year
    programme is calculated in about 15 ms (it took 1.2 s day by day); Havelock's network takes
    about 10 ms. The calendar never searches more than 30 years.
  - Stopped days are counted over merged date ranges, so many flags do not multiply the work.
- **A06 Vulnerable components.** No new dependencies. pip-audit **0**, npm audit **0**.
- **A08 Data integrity.** New audit entries: `dependency.added` and `.removed`, `holiday.added` and
  `.removed`, and `report_action.stop_scope_changed` with the scope and tasks before and after.
  Clearing a flag or changing its scope re-scores the project's risk.
- **A09 Logging.** The daily pour check runs project by project. A failure is logged with the
  project code, rolled back, and does not stop the others.
- **SSRF / outbound calls.** None added. BR-06 reads the weather cache that the existing refresh
  fills; `test_outbound_calls.py` still lists the weather client as the only caller.

### Privacy

- Pour alerts name the task, the project and the rain days; they go only to the site's project
  managers, in the app.
- The holiday seed is public data: the government's 2026 list, with the May Day holiday moved to
  31 May as amended on 21 April 2026. The Company Admin can correct it.

### Verification beyond unit tests

- **Mutation checks: 12 of 12** deliberate faults fail a test:
  - CPM: lag ignored in the forward pass, lag ignored in the backward pass, the forward pass off by
    one, "critical" needing negative float;
  - the forecast: the task's own rate trusted from day one, stopped days counted as work, cleared
    flags counting forever;
  - BR-06: 10 mm not counted as heavy, alerts ignoring a new rain day;
  - links: the loop check removed;
  - BR-11: progress on a stopped task accepted; anyone changing a flag's scope.

  The first run caught 10. The two survivors (lag in the backward pass, cleared flags) had no test
  that could see them; both now do.
- **A randomised check** compares the fast calendar arithmetic with a day-by-day walk over 300
  random working weeks, holiday sets and spans.
- **In the browser** (demo data):
  - the PM sees the Gantt with the critical chain, slip, links, today line and rain marks;
  - the engineer files a report with a safety problem, confirms the AI tag and stop-work, and sees
    the in-progress tasks pre-ticked. They narrow it to one task; the Gantt shows it STOPPED and
    hatched, and the banner names it with "Only the project manager can clear it";
  - the PM adds a task to the flag, then clears it;
  - the Company Admin sees the 2026 holidays and the warning for 2027;
  - the working week in the project dialog;
  - no horizontal page scroll at 1440 px or 375 px, and on a phone the Gantt opens at today.

### Findings fixed during the review

1. **A long wet spell broke the pour alert.** The de-duplication key listed every rain day and
   overflowed its 120-character column with 9 days (found against the live forecast in the browser
   check). It is now a hash of the days, and the message names at most 5.
2. **A runaway network returned 500.** Long chains of 365-day lags, or very slow work stretched
   10×, could push dates past the calendar's 30-year limit. The network and the task list then
   failed. Now the network falls back to each task's own dates, with no critical path and a warning
   the PM can act on.
3. **Day-by-day arithmetic was slow** at the limits: about 3 s per request for a 500-task, 15-year
   programme, and the task list calls it too. It is now arithmetic, about 100 times faster, with the
   same results.
4. **No cap on links.** A programme now has at most 2,000.
5. **The scope-change audit recorded the IDs as sent**, not the ones validated. It now records the
   stored tasks.
6. **Holiday dates were unbounded.** They are now 2000 to 2100, in the API and the form.
7. **The Gantt's screen-reader table widened the page.** A visually hidden table ignores its 1 px
   width, so the whole page scrolled sideways at desktop width. It is now wrapped in a hidden block.
8. **The stop-work banner showed only on the Overview.** It now shows on the Schedule tab too, next
   to the stopped tasks.

### Open items

- Only finish-to-start links. Start-to-start and finish-to-finish can come later without changing
  stored links.
- One holiday list per company: projects in another country would need their own.
- A flag counts its first day as stopped even if it is raised late in the afternoon.
- Rain barely moves the risk score: the simulator's rain effect is to be reviewed before the
  Phase 10 retrain ([#27](https://github.com/whoispasindu/SiteSense/issues/27)).

## Phase 8 review: 2026-10-11

Scope: cost forecasts and variance alerts (`rules/cost.py`, `services/cost_service.py`), progress
claims (BR-08), variation orders (BR-09, TC-10), the client's variation view, the Company Admin's
variation limit, migration 0010, the cost overview, the budget, claims, variations, client and admin
screens, and the demo seed.

### OWASP Top 10 (2021) walk-through

- **A01 Broken access control.** The 19 new endpoints are in the role matrix for every role.
  - Claims: only a QS submits and records payment; only a PM approves; both read.
  - Variations: the PM and QS raise and read; only the QS prices; only a PM decides, and never on a
    variation they raised; only the raiser withdraws; the raiser or a QS revises.
  - The client sees and decides only on variations sent to them, on their own sites; anything else
    answers 404.
  - The BR-09 limit needs `variation_limits:manage`, which only the Company Admin holds.
  - Every project route goes through the site scope.
  - Mutation-checked (below).
- **A03 Injection.** Titles, descriptions and comments are stored as text and rendered by React.
  Amounts and percentages are validated decimal strings with fixed precision.
- **A04 Insecure design.**
  - The claim amount is calculated, never accepted from the client, so BR-08 cannot be exceeded; a
    database check keeps the stored figures consistent.
  - The contract changes only through approved variations once work starts (fixed, below).
  - Approval re-checks that the contract and budget stay positive.
  - A revision of a variation the client has seen goes back to the client.
  - A limit change never re-routes work already sent.
  - Races were tested against the running API (below).
- **A05 / DoS.** Claims are capped at 200 sections, with percentages from 0 to 100 at two decimals.
  Money changes are within ±10¹³ at two decimals. Time impact is at most 3,650 days. Text is limited
  to 5,000 characters for descriptions, 1,000 for comments and 500 for a limit reason. The overview
  makes a few indexed queries per project on the caller's sites.
- **A06 Vulnerable components.** No new dependencies. pip-audit **0**, npm audit **0**.
- **A08 Data integrity.** Every claim and variation step is audited:
  - `claim.submitted`, `claim.decided` and `claim.paid`;
  - `variation.raised`, `.priced`, `.revised`, `.decided`, `.client_decided` and `.withdrawn`;
  - `variation.applied`, with the contract value, budget line, planned end and task end before and
    after;
  - `project.variation_limit_changed`, with from, to and reason.
- **A09 Logging.** A failed variance check is logged with the project code and never undoes the
  approval, order or delivery that triggered it.

### Privacy

- The client's view carries no budget change, section budget or internal comment. Internal people
  appear as "Contractor". TC-07 still holds: a client gets 403 on budgets, claims and the cost
  overview.

### Verification beyond unit tests

- **Mutation checks: 23 of 23** deliberate faults fail a test. These cover:
  - claims: no retention; progress allowed to go down; previous claims not deducted; the BOQ total
    used instead of the contract value; an unapproved claim marked paid;
  - BR-09: the limit boundary made inclusive; the time impact ignored; omissions ignored; a PM
    approving their own variation, by routing or by decision; the client allowed to reject; a
    revision skipping the client; a revision keeping the old price;
  - approval: the planned end or the budget line not changed; BR-02 ignoring variations;
  - the client: internal comments shown; unsent variations visible;
  - the limit change not audited as such; the contract editable directly;
  - the forecast ignoring committed work; the alert line at the budget; variance alerts repeating.

  The first run caught 22. The survivor (alerts repeating) was hidden by the notifications'
  same-day de-duplication; a next-day test now catches it.
- **Races, against the running API:** two simultaneous claim submissions gave 201 and 409. Two
  simultaneous client approvals of the same variation gave 200 and 409, and the contract changed
  once.
- **In the browser** (demo data):
  - the PM approves a claim from the calculation sheet;
  - the client sees why a variation needs them and approves it, and the contract value, planned
    end, task and audit log update (TC-10);
  - the QS prices a PM's variation and sees it routed to the client, with the reason;
  - the QS's new-claim form recalculates as percentages are typed.

### Findings fixed during the review

1. **The contract could be changed without a variation.** Since Phase 2 a PM could edit an active
   project's contract value and planned end directly. That bypassed the QS's price, BR-09 and the
   client's approval. Now those fields change directly only while a project is in planning with no
   claim or variation (`contract_locked`). The edit dialog shows them read-only, and both are tested
   and mutation-checked.
2. **Margins were understated after a variation.** The budget included the variation's budget
   change, but the BOQ value did not include its contract change. Project and section totals now
   carry approved variations, and every margin uses BOQ plus variations.
3. **Locking a project row failed** ("FOR UPDATE cannot be applied to the nullable side of an outer
   join", because the site is loaded with a join). Found by the tests before it shipped; the locks
   now name the project table only.
4. **Money totals could come back as "0" rather than "0.00"** when nothing had been summed. Every
   money field in claim and variation responses is now rounded to cents.
5. **Two navigation errors.** The phase marker was still 5, so finished modules showed as "Soon".
   Moving it to 8 would have linked "Risk & what-if" to a page that does not exist yet; that item now
   arrives with the what-if planner (Phase 10).

### Open items

- Retention release at practical completion (close-out).
- Decided for the Phase 12 portal: clients also see variations a PM approved under their limit,
  labelled and read-only, with no internal costs ([Phase 12 plan](plans/phase-12-client-portal.md)).
  Until then they see only variations sent to them.
- Committed cost covers materials only, so the forecast is a materials-led trend. Labour, subcontract
  and plant costs: [#26](https://github.com/whoispasindu/SiteSense/issues/26).
- Variation counts as a risk model input: risk model v2 (Phase 10).

## Phase 7 review: 2026-10-11

Scope: the report-issue training code and data (`ml/nlp/`), the TF-IDF scorer, the DistilBERT ONNX
runtime and its manifest, `scripts/fetch_models.py`, the tagger and redaction, report issues and
follow-up actions (migration 0009, five endpoints), the material-request link, risk model 1.1.0 with
issue features, the AI check screen and the stop-work banner.

### OWASP Top 10 (2021) walk-through

- **A01 Broken access control.** The five endpoints are in the role matrix for every role. Reading
  needs `reports:read` and the report's site (404 elsewhere). Only the author, on the day of the
  report, can analyse or confirm (403 otherwise). Only a project manager can clear stop-work
  (BR-11); the author and the QS get 403. A material request can only close an open material
  follow-up of the same project. Mutation-checked (below).
- **A03 Injection.** Report text reaches the classifier as data; it is a classifier, not a language
  model, so there are no instructions to inject. Snippets are rendered by React as text.
  Notification links are fixed in-app paths.
- **A04 Insecure design.** The AI only suggests: nothing changes until the author confirms, and
  every follow-up box starts unticked. Follow-ups must match a confirmed issue (a stop-work needs a
  confirmed safety issue). Confirmation happens once. **Fixed:** two simultaneous confirmations
  (below).
- **A05 / DoS.** Problems text is capped at 5,000 characters, tagging at 20 sentences of 300
  characters, the tokenizer at 48 tokens, confirmation at 30 issues of 300 characters. A worst-case
  analysis takes 0.4 s of CPU; onnxruntime is limited to 2 threads. **Fixed:** analysis is now rate
  limited (below). The model loads once per worker (about 2 s, about 270 MB).
- **A06 Vulnerable components.** New in the backend: onnxruntime 1.31.0 and tokenizers 0.23.3.
  pip-audit **0** for the backend, the ML stack and the transformer extras (torch, transformers,
  safetensors, onnx). The extras are now audited in CI too. npm audit **0** (no new packages).
- **A08 Software and data integrity.** No pickles anywhere: the TF-IDF model is validated JSON, and
  ONNX is an operator graph. The weights are pinned by SHA-256 in a committed manifest, checked by
  the fetch script and again before parsing. Tampered, resized and wrongly named files are refused,
  and file names in the manifest cannot contain paths. Golden rows prove the backend reproduces
  training. The release holding the files is a pre-release of this private repository; CI reads it
  with the read-only workflow token.
- **A09 Logging.** New audit events: `report.issues_confirmed` (kept, removed, added and edited
  counts, follow-ups) and `report_action.closed`. Falling back to TF-IDF is logged once with the reason. The report text
  itself is not logged.
- **A10 SSRF and outbound calls.** **Fixed:** onnxruntime called Microsoft's telemetry service
  (below).

### Privacy and responsible AI

- Names are redacted to `[PERSON]` before anything else: people on the project's site, the author,
  titled names ("Mr Perera", "supervisor Nimal") and common Sri Lankan names without a title
  ("sunil absent"). The stored snippet is the redacted sentence.
- No real report text was used for training. The training data is synthetic, and the test sentences
  were written by the project.
- Each issue keeps what the AI said beside what the author confirmed, with the model version, so
  disagreement can be measured later.
- The model card states what the model is weak at. Severity is weak (macro F1 0.50) and leans
  towards "high", which is why the PM alert is never pre-ticked.

### Verification beyond unit tests

- **Mutation checks: 17 of 17** deliberate faults fail a test. These cover low-confidence never
  flagged, names reaching the classifier, repetition not raising severity, injury not high,
  unkept suggestions confirmed, anyone clearing stop-work, stop-work without a safety issue,
  re-analysing after confirming, a non-author confirming, no re-score after confirming,
  suggestions counted as risk inputs, the hash not checked, a follow-up from another project,
  the backend copy of the severity rules drifting from `ml/`, the common-name list switched off, an
  everyday word added to it, and a new module importing a network client.
- **Race, against the running API:** two simultaneous confirmations of the same report. Without the
  fix, both succeeded (3 of 3 runs), doubling the stop-work flag, the PM alert and the
  notifications. With it: 200 and 409, one of each (3 of 3).
- **Outbound connections, in the container:** watching the process's own sockets while loading and
  running the model. Before the fix: one HTTPS connection to `mobile.events.data.microsoft.com`.
  After: none.
- `fetch_models.py` against the published release: both files downloaded and byte-identical to
  the exported ones.
- In the browser: the engineer files a report, sees the tags (an unsure one highlighted), edits a
  category, ticks stop-work and the PM alert, and confirms. The PM sees the banner on the project and
  clears it.

### Findings fixed during the review

1. **onnxruntime sent telemetry to Microsoft.** The Linux build of onnxruntime 1.31 opens a
   connection to Microsoft's event collector when a model is loaded. A server holding site reports
   must not call third parties. `ORT_DISABLE_TELEMETRY=1` is now set before onnxruntime is imported
   (code and Docker image), and a test fails if anything imports onnxruntime before that.
2. **Two simultaneous confirmations both succeeded**, duplicating follow-ups and alerts (two tabs or
   a double submit). Analysis and confirmation now lock the report row first, so the second waits,
   sees the first, and gets 409.
3. **Analysis had no rate limit.** At up to 0.4 s of CPU a call, a signed-in author could keep a
   worker busy. It is now limited per client (30 a minute, configurable), tested.
4. **The transformer requirements file was missing.** The training script referred to
   `requirements-transformer.txt`, but it had not been committed, so the PyTorch training stack was
   neither pinned nor audited. It is now pinned and audited in CI.
5. **No test held the two copies of the severity rules together.** The backend cannot import `ml/`,
   so it keeps a copy; a test now fails if the code differs.
6. **Stale or wrong comments.** The confidence threshold was described as chosen on validation data
   (it is a fixed round number; its behaviour on the test set is in the model card). The model was
   described as 67 MB (it is 266 MB at full precision).
7. **The 8-bit model was batch-dependent.** Found while exporting: its activations are quantised per
   input, so a sentence's score changed with its neighbours (0.087 on the golden rows). Full
   precision ships, and a test checks a sentence scores the same alone or in a batch.
8. **Redaction missed untitled first names** ([#23](https://github.com/whoispasindu/SiteSense/issues/23)).
   A worker without an account, named without a title ("sunil absent"), was stored as written.
   Redaction now also removes 236 common Sri Lankan given names and surnames in any case. The list
   shares no word with the 1,719 data sentences (tested) and holds no ordinary English word.
   A new test lists every module that imports a network client (today only the weather client) and
   fails if another appears, so report text cannot reach an outside service without review.
   Mutation-checked: switching the list off fails 7 tests; adding a network import fails the guard.

### Open items

- A rare name that is not on the list and has no title still gets through redaction; a site worker
  list or a local name recogniser would close that gap.
- Measure the classifier on real, consented, confirmed tags before trusting the numbers.
- BR-11 blocking of related programme tasks: Phase 9.
- Memory: each API worker holds the 266 MB model. Size the workers accordingly, or move tagging to a
  background job if workers multiply.

## Phase 6 review: 2026-10-10

Scope: the synthetic data generator and training code (`ml/`), the risk model scorer and feature
builder (`app/ai/risk/`), daily scoring and the BR-10 alert, the risk endpoints, the dashboard and
project risk panels, the planned-crew field, the 14-day weather fetch and the extended demo seed.

### OWASP Top 10 (2021) walk-through

- **A01 Broken access control.** Risk is `risk:read` only (PM, QS). The project endpoint uses the
  same site check as every project route (404 elsewhere); the ranking lists only the caller's
  projects. Both endpoints are in the role matrix for every role. A new test fails if any API route
  is missing from the matrix. Mutation-checked: opening risk to `projects:read` fails the tests.
- **A03 Injection.** Features come from ORM queries over stored data; no user input reaches the model
  directly. Drivers are generated text over numbers, rendered as text.
- **A04 Insecure design.** A score suggests, it never acts. Scoring after a report is best effort: a
  failure is logged and the report is still saved. One failing project does not stop the daily job.
  The High alert fires on entry only, so it cannot be turned into a notification flood.
- **A05 Misconfiguration.** The weather client is unchanged (fixed host, no redirects, 64 KB cap);
  14 days of daily data is a few kilobytes.
- **A06 Vulnerable components.** The training stack (LightGBM, pandas, scikit-learn, Jupyter) lives
  only in `ml/` and is not installed in the backend image. It is pinned, pip-audited in CI (0
  findings) and covered by Dependabot.
- **A08 Software and data integrity.** The backend never unpickles a model. The JSON model is
  validated before use; a malformed file is refused (13 malformed variants tested). Golden rows
  prove the scorer reproduces LightGBM exactly, and CI retrains from the committed code and data and
  fails if the shipped model is not reproduced. The training data's SHA-256 is recorded in the model.
- **A09 Logging.** Scoring failures log the project code and the exception, no personal data.
- **Denial of service.** Model size is capped (5,000 trees, 65,536 nodes a tree). Scoring is a few
  hundred tree walks plus a handful of queries per project; the risk endpoints only read.

### Privacy and responsible AI

- Training data is simulated; no personal data is used. Features describe projects, never people.
- Every forecast shows its drivers, the inputs it was missing, the model version, and that it is an
  estimate from a model trained on simulated projects.

### Verification beyond unit tests

- **Mutation checks: 12 of 12** deliberate faults fail a test. These cover the BR-10 thresholds,
  the alert repeating, the alert reaching the QS, cost ignored in the score, the split direction,
  accepting a child-before-parent tree, delivery lateness, Saturdays, heavy rain at exactly 10 mm,
  scoring completed projects, and opening risk to engineers. The first run caught 11; the survivor
  (an on-time delivery counted late) now has a test.
- Retraining from scratch gives an identical model (trees, golden predictions and data hash).
- Seeded the demo database and checked the scores end to end in the browser as a PM.

### Findings fixed during the review

1. **The cost feature could not mean the same in training and live use.** The simulator compared
   all costs with progress; the app only tracks material commitments, so every live project would
   have looked well under budget. It now compares committed cost with the budgeted value of the same
   quantities, on both sides, and the model was retrained.
2. **A same-day re-score of a High project reported a new alert.** The notification was suppressed by
   its de-duplication key, but the logic was wrong. The comparison now includes the existing score
   for the day; tested.
3. **The ranking used a deprecated SQLAlchemy construct** that turns into a 500 under the test
   settings; replaced with a plain latest-date subquery before it shipped.
4. **The role matrix had drifted** (a path parameter renamed) and nothing checked that every route
   was listed. Added the route-coverage test.
5. **Drivers are relative to a typical project**, which could read as contradictory ("behind plan"
   lowering the forecast). The panel now says what they are compared with.
6. **A flaky frontend test** built its "just now" timestamp when the file loaded; it now stamps it
   when the request is made.

### Open items

- Validate the simulator's assumptions with a contractor's real projects before trusting the
  numbers (owner: product).
- SHAP drivers, likely ranges and the what-if planner: risk model v2 (Phase 10).
- Issue counts from report NLP (Phase 7) and variations (Phase 8) as model inputs.
- Site overheads are not tracked, so the overrun forecast stays weak until they are.

## Phase 5 review: 2026-10-10

**Scope:** the whole repository at the end of Phase 5 (material requests, approvals, suppliers,
purchase orders, deliveries, the rules engine and the budget view). Design decisions are in
[ADR 0008](adr/0008-materials-approvals-costs.md), and the rules in
[business-rules.md](business-rules.md).

### OWASP Top 10 (2021) walk-through

| Risk | Phase 5 status |
| --- | --- |
| A01 Broken access control | All 18 new endpoints are in the role matrix. Decisions are checked by stage and role: a site engineer approving gets 403 and nothing changes (TC-01), and an approver cannot decide their own request (BR-04, TC-05, for both the QS and the PM). The PM cannot skip the QS check. Only the requester edits (after "change requested") or cancels. Requests, orders and budgets are site-scoped (404 outside); procurement is company-wide by design. Budget figures need `cost:read` (PM, QS); clients never get them (TC-07). |
| A04 Insecure design | Business-logic abuse was walked through. **Price creep at ordering:** the order price may not exceed the approved price. **Splitting a request to dodge BR-01:** the line check is cumulative, so splitting does not help. **Editing after approval:** edits are only possible in "change requested", and they resubmit to the QS. **Stale routing:** the level is re-checked when the QS approves. **Double ordering:** unique request per order line. **Over-delivery:** refused. |
| A04 Race conditions | Row locks on the BOQ item (request creation, BR-02), the request (decisions), the requests being ordered, and the order (deliveries). Verified against the running API: of two simultaneous requests that together exceed the allowance, one is accepted and the other refused. |
| A05 / DoS | Lists are capped at 100 per page and orders at 50 lines; notes are limited to 2,000 characters and comments to 1,000. Needed-by is within 2 years and expected delivery within 1. The live rules check is debounced in the browser and runs a fixed number of indexed queries. |
| A06 Vulnerable components | pip-audit **0**, npm audit **0** (no new dependencies). |
| A08 Data integrity | Committed and spent cost are derived from order lines and deliveries, so no stored totals can drift. Money is NUMERIC with check constraints (quantities and prices > 0) and exact decimals end to end. |
| A09 Logging and monitoring failures | New audit events: `material_request.created`, `.updated` and `.decided` (from/to status), `purchase_order.issued`, `delivery.recorded`, `supplier.created` and `.updated`. Every decision also notifies the people concerned. |

**Cost visibility (amended at the project owner's request).** Rates and amounts are now limited
to the PM, QS and procurement (`rates:read`). This reverses the earlier choice that let every
internal project role see section budgets.

- **Enforcement.** Site engineers receive role-specific response schemas that do not declare any
  cost field: projects, BOQ, schedule summary, item picker, requests and rule checks, and purchase
  orders. The BR-01 and BR-13 results are filtered out of their rule checks.
- **Prices.** Engineers cannot send a price (`422 price_not_allowed`); the QS prices their requests.
- **Tests.** `test_cost_visibility.py` walks every endpoint an engineer can call and fails on any
  cost field at any depth. Mutation-checked: making the visibility helper return everything makes
  it fail. It also confirms that PM, QS and procurement still receive the cost fields, and that
  clients are refused all of these endpoints.

### Verification beyond unit tests

- **Mutation checks (10 of 10 caught):** breaking any of these makes a test fail:
  - the BR-01 threshold
  - the BR-02 allowance
  - the BR-04 own-request check
  - the BR-05 order gate
  - the order-price cap
  - the over-delivery check
  - the stage permission (TC-01)
  - spent-cost derivation
  - the BOQ freeze
  - excluding rejected or cancelled requests from BR-02
- **Concurrency:** two parallel over-allowance requests against the running API, described above.
- **Browser, end to end:**
  - As the QS, approved a request from the pipeline and saw the cost-control panel with real
    committed and spent figures.
  - As procurement, ordered two approved requests on one purchase order and recorded a partial
    delivery. The order and request statuses and the budget moved accordingly (the Phase 5
    "Done when").

### Findings fixed during the review

1. **Procurement could reach the decision endpoint** and was only refused deeper in the service.
   The endpoint now requires a request or approval permission up front, so the refusal is
   consistent and tested in the role matrix.
2. **The rule check on an approved or ordered request counted its own cost twice** in the
   budget-line figure. The request's own contribution is now excluded.
3. **BOQ re-import would have orphaned requests.** The import is now refused once requests exist,
   with a `RESTRICT` foreign key as a backstop.
4. **Mislabelled rules in Phase 4:** the daily-report deadline is BR-07 (was written as BR-11),
   and heavy rain is BR-06 (was BR-08). Corrected in code and docs, using the build guide's rule
   table.
5. **Rule messages showed raw decimals** ("400.000 of 1650.000"). They now read "400 of 1,650".
6. **Rates and amounts reached site engineers** (contract values, BOQ rates, request prices, order
   totals). They are now limited to `rates:read` by role-specific schemas, as described above.
7. **The schedule summary embedded the full project summary**, including its contract value and
   totals. It now uses the cost-free project card for engineers.
8. **Rule messages with amounts in the request history.** The first version of the send-back at
   ordering wrote the BR-13 message ("committed cost would be LKR …") into the history comment,
   which engineers can read. The history now gives the reason in words only. The full messages go
   to procurement in the order response and to the audit log. The cost-visibility test now walks a
   sent-back request and fails on any string containing "LKR". Mutation-checked: restoring the old
   comment makes it fail.
9. **Price pending and ordering, reviewed.** `price_required` is enforced in the service, not only
   in the screen. The order path still locks the requests and re-checks BR-05 first. A line sent
   back drops out of the running committed total, so it cannot block the lines after it. A request
   the PM approved is re-sent only if its order amount exceeds the approved amount, so procurement
   cannot raise a price past the PM unseen, and the PM is not asked twice for the same excess.

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
