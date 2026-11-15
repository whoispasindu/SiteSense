# ADR 0020: Backup and restore as one tested script

- Status: accepted
- Date: 2026-11-15
- Changes: the backup advice in [ADR 0016](0016-hardening-and-deployment.md) ("back up the pgdata and
  media volumes") and [docs/self-hosting.md](../self-hosting.md)

## Context

A company running SiteSense itself holds its own data: the database (projects, budgets, reports,
claims, users, the audit log) and the site photos, which live in a separate volume. Step 5 of the
[release plan](../plans/open-source-release.md) asks for backups that a site office can actually
run, and a restore that has been tested end to end, not only described.

Two shell commands per backup (pg_dump, then tar of a volume whose name depends on the compose
project) and five for a restore are easy to get wrong at 2 am after a disk failure, and nothing
checks that a copy is complete.

## Decision

`backup.py` (in the release bundle; standard-library Python 3.9 or later, like `setup.py`):

- **`create`** writes one file, `sitesense-backup-<UTC time>.tar`, mode `0600`:
  - `database.dump`: `pg_dump --format=custom` of the whole database, run in the database container
    while SiteSense keeps running (a consistent snapshot);
  - `media.tar.gz`: the photos volume, packed by a short-lived backend container;
  - `backup.json`: when, the release (`SITESENSE_VERSION`), the database schema revision, and the
    size and SHA-256 of both parts.
  It keeps the newest 14 by default (`--keep`), deleting only files named like its own backups.
- **`restore`** checks the file before touching anything: the three parts and nothing else, the
  format, each part's size and SHA-256. It refuses a backup whose schema is newer than the images'
  (`alembic heads`), since an older release cannot read a newer database; an older backup is fine,
  because migrations run when SiteSense starts. After a typed confirmation (or `--yes`), it stops
  the app but not the database, runs `pg_restore --clean --if-exists --single-transaction
  --exit-on-error`, replaces the photos, and starts everything with `up --wait`.
- **`.env.prod` is not in the backup.** It holds the secrets and is stored separately. A restore
  needs the same `SITESENSE_MFA_KEY`; without it, two-step enrolments cannot be decrypted, so the
  guide says how to recover (a new admin with `create-admin`, who resets everyone).

A single-transaction restore means a failure leaves the database as it was; the photos are replaced
only after the database restore succeeded.

Rejected: putting backups inside the stack (a cron container): it would hold the database
superuser's access permanently and still need the copy off the server, which is the part that
matters. Cron on the host plus any copy tool (rclone, scp, a NAS) is simpler and visible.

## Verification

- `backend/tests/test_backup_script.py`: the archive's contents and mode, a damaged or foreign file
  refused, the newer-schema check, pruning, reading `.env.prod`, the exact commands (the database is
  never stopped).
- End to end on a real installation: install with `setup.py`, add an admin, a holiday and a photo,
  back up, delete every container and volume, restore into the empty installation, then check the
  users, the holiday and the photo are back, readiness is OK, and the admin signs in with their
  original one-time password. A deliberately corrupted backup is refused and the running
  installation is untouched.
- The scripts run on Python 3.9.

## Consequences

- One command each way, and a guide section for a new server.
- Backup size is about the size of the photos; the guide says to plan disk for the kept copies.
- Off-server copies stay the operator's job; the guide gives a cron and rclone example.
