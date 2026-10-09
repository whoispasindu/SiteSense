# ADR 0005: Authentication and sessions

- Status: accepted
- Date: 2026-10-09

## Context

Site engineers use SiteSense in phone browsers on site; managers keep it open all day. Sessions
must survive page reloads without putting long-lived credentials where an injected script could
read them, and the company admin must be able to cut someone off immediately.

## Decision

- **Passwords:** argon2id, minimum 12 characters, maximum 128, a small common-password deny-list,
  and no email name in the password. Admins never choose passwords: the server generates a
  one-time temporary password (about 116 bits) that must be replaced at first sign-in.
- **Access token:** HS256 JWT, 15 minutes, kept **only in memory** in the web app and sent as a
  `Bearer` header. Claims are pinned (algorithm, issuer, audience, type) and checked against the
  app clock.
- **Refresh token:** 256-bit random value in an `httpOnly; Secure; SameSite=Strict` cookie scoped
  to `/api/v1/auth`. Only its SHA-256 hash is stored. Each refresh rotates it; tokens of one
  sign-in form a family. Presenting an already-rotated token (outside a 30-second grace window
  for parallel tabs) revokes the family and writes `auth.refresh_reuse_detected` to the audit log.
  Absolute session limit: 30 days.
- **Immediate revocation:** each user has a `session_version`. Password change, reset,
  deactivation and role change bump it, which invalidates every access token at once; every
  request loads the user, so deactivation is immediate.
- **Brute force:** account lockout for 15 minutes after 5 consecutive failures (TC-09), plus a
  per-IP rate limit on sign-in and refresh. Wrong password and unknown email give the same answer
  in the same time (a dummy hash is verified for unknown emails).
- **CSRF:** the cookie is `SameSite=Strict` and only the auth endpoints read it; those endpoints
  also reject requests whose `Origin` is not allowed or whose `Sec-Fetch-Site` is `cross-site`.
- **Audit:** logins (success and failure), lockouts, logouts, password changes and every admin
  action are written to `audit_logs`, which the application role can insert into but never
  update or delete.

## Consequences

- The rate limiter is in-process; scaling to several API instances (Phase 13) needs a shared
  store such as Redis.
- Showing "account locked" reveals that the account exists after 5 failed attempts. This is
  accepted: it needs repeated, rate-limited, audited attempts, and it lets real users understand
  why they cannot sign in.
- Two-step verification (TOTP) for managers and procurement is planned for Phase 13; the
  `mfa_enabled` column and `MFA_ROLES` are in place.
