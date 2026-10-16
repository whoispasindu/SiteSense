# ADR 0016: Hardening and deployment

- Status: accepted
- Date: 2026-10-16
- Changes: sign-in in [ADR 0005](0005-authentication-sessions.md) (adds a second step for some
  roles), rate limits in [ADR 0003](0003-security-baseline.md) (adds per-user budgets)

## Context

Phase 13 asks for SiteSense to be "secure, fast enough, accessible and publicly demoable":

- an OWASP Top 10 checklist;
- rate limiting;
- two-step verification;
- dependency and secret audits;
- indexes, pagination, caching and a load test;
- axe checks, a keyboard pass and contrast fixes;
- Docker images on hosted services with seeded demo accounts.

The project owner decided:

- **No public demo for now** (no budget for hosting). Everything is made ready for one: a
  production setup that runs locally with the demo accounts, a demo mode, and a step-by-step
  deployment guide.
- **Two-step codes** are required for Company Admins, project managers, quantity surveyors and
  procurement officers, and optional for site engineers and clients.
  - Admin resets are audited.
  - An admin cannot reset their own; they use a recovery code or ask another admin.
  - In demo mode, enforcement is skipped for the seeded demo accounts so anyone can sign in locally.
    The README says so.
- **Load test:** 50 concurrent users with 0 errors, with these 95th-percentile targets, and the
  machine's specs recorded with the results:
  - reads under 500 ms;
  - writes under 1 s;
  - the heavy endpoints (what-if, weekly PDF, report analysis), measured separately, under 2 s.

## Decision

### Two-step sign-in (TOTP)

- **Time-based codes (RFC 6238)** from any authenticator app: SHA-1, 6 digits, 30 seconds, one step
  of clock drift either way. Written in `core/totp.py` and checked against the RFC's test vectors,
  rather than adding a library for about 80 lines.
  - **A code works once.** The last step used is stored, and an older or equal step is refused.
  - **Wrong codes count towards the same lockout as wrong passwords.** A right password does not
    reset the count while a code is still due.
- **Sign-in in two steps.** A right password for an enrolled user returns a short challenge token
  (5 minutes, type "mfa"), not a session. The access-token and challenge-token types can never be
  swapped; the code step exchanges the challenge for a session.
- **Secrets at rest.**
  - The authenticator secret is encrypted with AES-GCM under a key derived from
    `SITESENSE_MFA_KEY`, and bound to the user's ID, so a copied row does not work for another
    user.
  - Ten recovery codes are stored only as keyed hashes (HMAC-SHA256) and work once each.
  - Production refuses to start with the development key, or with an MFA key equal to the JWT
    secret.
- **Enforcement.** A required role that has not enrolled can sign in but reaches only set-up and
  their own account details: every other endpoint answers 403 `mfa_setup_required`, and the app sends them to the set-up
  page. Production refuses to start with enforcement off. The setting exists only for the test suite.
- **Admin reset.** It signs the person out everywhere and removes the enrolment and recovery codes.
  It is audited, and refused for one's own account.
- **Demo mode** skips enforcement only for accounts the demo seed created (`is_demo`). An account
  anyone creates in a demo still has to enrol.

### Request budgets

- **Every write** (POST, PUT, PATCH, DELETE) shares one budget per signed-in user: 120 a minute.
  Before sign-in, or with a token that does not verify, the budget is per IP. Per user rather than
  per IP, so one office behind a shared address does not share one budget, and a forged token
  cannot borrow someone's.
- **The heavy endpoints** have smaller budgets: what-if and the weekly PDF 20 a minute, report
  analysis 30.
- **The sign-in steps** keep their own per-IP budgets and are not counted twice.
- A test calls every write endpoint in the API schema and checks that it is limited.

### Demo mode

`SITESENSE_DEMO_MODE=true` does four things:

- the demo accounts skip two-step codes (above);
- a "Demo data, not real projects" notice shows on every page;
- emails are written to the log, never sent, even with a mail server configured;
- the data resets to the seed at 03:00 Sri Lanka time.

The reset runs as the schema owner, because the app's own role can never delete audit rows, and
that stays true. It deletes child tables first, so the reference data loaded by migrations (roles
and holidays) survives. It refuses outside demo mode, and on a database without the seeded demo
accounts, so turning demo mode on by mistake over real data deletes nothing.

The demo company has one project at each risk level:

- **Havelock: high.** Its substructure concrete and steel were bought at the full BOQ rates after a
  price rise.
- **Fort View: medium.**
- **Peradeniya: low.**

### The production setup

`docker-compose.prod.yml` runs locally exactly as a server would:

- **Caddy** puts the web app and the API on one HTTPS origin, so the `SameSite=Strict` refresh
  cookie works. The hosted guide keeps the same shape with Vercel's rewrites.
- **Migrations** run once, as the owner.
- **The API** runs several workers, read-only.
- **The scheduled jobs** run in a process of their own (`run-scheduler`), so adding workers never
  runs a job twice.
- **Settings:** empty variables count as unset.

### Performance

- **Measure before caching.** The load test met every target on its first run, but with little
  room. The slowest read, the purchase-order list, loaded each order's lines in a separate query; it
  now loads them in one batch, and a test fails if the query count grows with the number of orders.
- **Dashboard figures are not cached.** A cached figure would hide a person's own approval for a
  while after they made it, and the measured times do not need it. What is cached:
  - weather forecasts;
  - risk scores (worked out each morning);
  - the AI briefing;
  - the built web app's files.
- **Indexes.** Seven foreign keys that joins and filters use got indexes, plus one for
  notifications by person and date. The 18 left without an index record who did something, and
  nothing filters on them.

### Accessibility

- **axe-core checks every screen** the frontend tests leave behind, and any finding fails the test.
  So new pages, dialogs and states are checked as they are written, not once a phase.
- **A test checks the contrast of every design-token pair** in both themes, because axe cannot
  measure contrast in jsdom.
- **Form fields have a border colour of their own** that meets 3:1. Dividers stay light.

## Consequences

- Required roles need a phone with an authenticator app. Losing it means a recovery code, or an
  admin reset (another admin, for an admin).
- `SITESENSE_MFA_KEY` must be kept safe and never changed casually: it decrypts every enrolment.
- Rate-limit counters are per API process (a known limit, documented in `docs/deployment.md`).
  Lockout lives in the database and is not affected. Several API machines would need a shared
  store such as Redis behind the same interface.
- A demo's nightly reset needs the owner's connection string in the scheduler. A real company's
  setup leaves it out.
- Every frontend test now also runs axe, which makes the suite somewhat slower.
