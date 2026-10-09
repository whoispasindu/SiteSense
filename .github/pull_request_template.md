## What and why

<!-- What does this change do, and which issue does it close? -->
Closes #

## How it was tested

<!-- Commands run, new tests added, screens checked (desktop and phone width). -->

## Checklist

- [ ] Tests added or updated (including forbidden cases for each role on new endpoints)
- [ ] CI is green: lint, types, tests, build, audits
- [ ] Authorisation is enforced on the server for new endpoints
- [ ] Input validated (Pydantic / Zod); errors use the standard envelope
- [ ] No secrets, real personal data or internal details in code, fixtures or logs
- [ ] Docs, `.env.example` and `CHANGELOG.md` updated where needed
- [ ] I have read the whole diff and can explain every line
