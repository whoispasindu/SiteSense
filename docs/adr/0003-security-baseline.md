# ADR 0003: Security baseline from Phase 0

- Status: accepted
- Date: 2026-10-09

## Context

SiteSense will hold commercial cost data and personal data of site staff (Sri Lanka Personal
Data Protection Act, No. 9 of 2022). Retro-fitting security late is expensive and error-prone.

## Decision

From the first commit:

- **Secrets** come only from environment variables, typed as `SecretStr`. `.env` files are
  ignored by git, and Gitleaks scans the full history in CI.
- **Unsafe production configuration fails startup**: debug, wildcard or plain-HTTP origins,
  example passwords.
- **Least-privilege database role** for the running API; migrations use a separate owner role.
- **One error envelope**: no stack traces, exception messages or submitted values in responses.
- **Strict security headers** on every response, including errors; HSTS in production.
- **Request body size limit**, trusted hosts and an explicit CORS allow-list.
- **Structured logs** with request IDs and automatic redaction of sensitive keys. Query strings
  are not logged.
- **Random UUID primary keys**, so identifiers cannot be enumerated.
- **Supply chain:** pinned dependencies, Dependabot, pip-audit, npm audit, dependency review,
  CodeQL, and GitHub Actions pinned to commit SHAs.
- **Frontend:** no raw HTML injection (lint-enforced), runtime validation of every API response,
  same-origin requests only, strict CSP in production.
- Each phase ends with a recorded security review in `docs/security.md`.

## Consequences

Slightly more setup per feature, and far fewer classes of vulnerability to hunt later.
