# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project
uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- **Phase 2: projects, BOQ and budget.**
  - Projects with client, contract value, type, status and contract period, scoped to the
    user's sites; project managers create and edit them.
  - BOQ import from Excel (.xlsx) or CSV with a row-by-row validation report, dry run first,
    all-or-nothing import, flexible header names, and protection against hostile files.
  - BOQ sections and items with exact decimal totals; a cost budget line per section, editable
    by the quantity surveyor (seeded from an optional "Budget rate" column).
  - Web: Projects register, project overview (title block, KPIs, cost by section, team), BOQ
    browser with inline budget editing, and a three-step import screen.
  - Realistic demo BOQ (72-apartment block in Colombo, LKR 1.11 bn) loaded by `seed-dev`.
- **Phase 1: authentication, roles and users.**
  - Sign-in with argon2id passwords, 15-minute access tokens kept in memory, and rotating
    refresh tokens in an httpOnly cookie with reuse detection.
  - Account lockout after 5 failed attempts (15 minutes), per-IP rate limiting on sign-in and
    refresh, uniform answers for wrong password and unknown email.
  - Six roles with a central permission table; `require_permission`, `require_role` and
    site-scoping helpers (groundwork for BR-03).
  - Admin: create users with one-time temporary passwords, change roles, assign sites, reset
    passwords, deactivate and reactivate; manage sites; read the audit log.
  - Append-only audit log for sign-ins, lockouts and admin actions (enforced by database grants).
  - Web: "site gate" sign-in, forced password change, role-based menu, user menu, Users, Sites
    and Audit log screens.
  - `python -m app.cli create-admin` and `seed-dev`.
- **Phase 0: setup and foundations.**
  - FastAPI backend with layered folders (`api`, `models`, `schemas`, `services`, `ai`,
    `integrations`, `core`), settings from environment, SQLAlchemy 2 and Alembic.
  - Liveness and readiness health endpoints.
  - One JSON error envelope for every failure; no stack traces or input echoed to clients.
  - Structured JSON logging with request IDs and automatic redaction of sensitive fields.
  - Security middleware: strict security headers, trusted hosts, CORS allow-list, request
    body size limit.
  - PostgreSQL with separate schema-owner and least-privilege application roles.
  - React + TypeScript + Vite + Tailwind web app with the "site office" layout shell,
    typed and runtime-validated API client, React Query, and a live system-status dashboard.
  - Docker Compose stack started with one command.
  - CI: Ruff, mypy, pytest, Alembic drift check, ESLint, TypeScript, Vitest, build,
    pip-audit, npm audit, Gitleaks, dependency review and CodeQL.
