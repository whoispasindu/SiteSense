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
| Approvals | Stage-and-role checks, segregation of duties (BR-04), state machine (invalid transitions 409), order prices more than 5% over approval go back to the PM (BR-14), row locks against double approval and quantity races | `rules/materials.py`, `services/materials_service.py`, `services/procurement_service.py` | `test_rules_materials.py`, `test_materials_api.py` |
| Notifications | Per-user only (others answer 404); links restricted to in-app paths by service and database constraint; de-duplicated reminders | `services/notification_service.py`, migration 0005 | `test_reminders_notifications.py`, `reports.test.tsx` |
| AI models | Model files are JSON data validated before use (structure, feature indexes, finite numbers, children after parents, size limits); no pickle/joblib loading; golden predictions prove the scorer matches training; CI retrains and checks the shipped model is reproducible | `ai/risk/model.py`, `ml/check_model.py` | `test_risk_model.py`, CI ML job |
| Large model files | ONNX weights live in a GitHub Release, not the repository; a committed manifest pins SHA-256 and size; `fetch_models.py` verifies before moving a file into place and the backend verifies again before onnxruntime parses it; plain file names only; 300 MB cap; mismatch or missing means the TF-IDF fallback; ONNX is an operator graph, not pickled code | `scripts/fetch_models.py`, `ai/nlp/transformer.py` | `test_report_transformer.py` (tamper, size, names, fallback, parity), CI fetches and runs them with `SITESENSE_REQUIRE_MODELS=1` |
| Outbound calls (ML runtime) | onnxruntime's telemetry to Microsoft is switched off before it is imported, in code and in the image | `ai/nlp/transformer.py`, `backend/Dockerfile` | `test_onnxruntime_telemetry_is_off_before_onnxruntime_is_imported`; checked in the container: no connection |
| Personal data in free text | Names of site people, the author, titled names and common Sri Lankan names (any case) become `[PERSON]` before classification and storage; only the weather client may call out of the server | `ai/nlp/text.py: redact`, `ai/nlp/names_lk.txt`, `services/issue_service.py` | `test_names_are_redacted_before_storage`, `test_report_nlp.py`, `test_outbound_calls.py`, ML `test_the_name_list_holds_no_word_from_the_report_data` |
| Contract changes | The contract value and planned end change only through approved variations once a project is under way; claims are calculated (BR-08) and a database check keeps their figures consistent; one claim waits at a time (partial unique index and a project lock); variation approval locks the variation, project and budget line and applies everything in one transaction, audited before and after; each variation keeps the BR-09 limit it was routed with; only the Company Admin changes a limit (reason audited) | `rules/claims.py`, `rules/variations.py`, `services/claim_service.py`, `services/variation_service.py`, `services/project_service.py: contract_locked`, migration 0010 | `test_rules_cost.py`, `test_contract_api.py`, `test_the_contract_changes_only_through_variations_once_under_way` |
| Client view | Separate schema with no internal cost or comment; only variations sent to the client, on their sites (404 otherwise); the client never reaches budgets, claims or the cost overview (TC-07) | `schemas/contract.py: ClientVariationOut`, `services/variation_service.py: client_out` | `test_the_client_queries_and_a_revision_goes_back_to_the_client`, `test_the_client_sees_only_their_sites`, role matrix |
| Supply chain | Pinned deps, Dependabot (pip, npm, actions, docker), pip-audit, npm audit, dependency review, CodeQL `security-extended`, actions pinned to SHAs, `permissions: contents: read`, `persist-credentials: false` | `.github/` | CI |

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
- Committed cost covers materials only, so the forecast is a materials-led trend. Labour and plant
  costs are not tracked yet.
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
