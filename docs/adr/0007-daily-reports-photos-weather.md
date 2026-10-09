# ADR 0007: Daily reports, photos, weather and reminders

- Status: accepted
- Date: 2026-10-10

## Context

Phase 4 makes site engineers file one structured report per day. Later phases use these
reports for NLP tagging (Phase 7), delay forecasting (Phases 6 and 10) and the client portal
(Phase 12). The reports carry photos from phones on site connections, pull weather from a third
party, and must keep working when that third party is down (TC-08). BR-11 needs a missing-report
reminder at 18:00 site time.

## Decisions

**One report per project per site day.** The rule is enforced by a unique constraint on
`(project_id, report_date)`. A second submit gets `409` with the existing report's id, so the
form can link to it (TC-03). Reports can be dated up to 7 days back, never in the future and
never before the project starts. They are accepted only for active and on-hold projects.

**Corrections on the same day only.** The author may correct the text, crew and weather, and add
or remove photos, until midnight (site time) of the day they submitted. After that the report is
part of the record. Task progress entered in a report updates the programme immediately; the
report keeps each task's before and after values (`report_progress`) even if the task is deleted
later.

**Photos are re-encoded, private and stored outside the database.**
- The server checks the magic bytes (JPEG, PNG, WebP), decodes under a 50-megapixel budget,
  applies the EXIF orientation and writes a fresh JPEG (at most 2560 px) plus a 480 px
  thumbnail. Re-encoding drops all metadata, including GPS position, and any appended payload.
- Storage keys are random and server-generated, and checked against a strict pattern on every
  use. The client's file name is never used.
- Photos are served only through an authenticated, site-scoped endpoint, never from a public
  URL.
- `LocalStorage` writes to `SITESENSE_MEDIA_ROOT`. An S3-compatible backend can implement the
  same three-method protocol later.
- The browser also downscales before upload to save site bandwidth. That is a convenience, not
  a control.

**Weather from Open-Meteo, cached per site.** It is free and needs no API key, and it covers
Sri Lankan locations.
- The adapter builds the URL from a fixed host and the site's stored coordinates only. It
  refuses redirects, caps the response at 64 KB and validates its shape before storing.
- Forecasts are cached in `weather_forecasts` for 3 hours and refreshed daily at 05:30.
- When the provider fails, the API returns the last cached forecast with `stale: true` and a
  message (TC-08). With no cache, it says so; it never errors.
- Omitted weather on a new report is filled from the cache (`weather_source = "forecast"`).

**Reminders from an in-process scheduler (APScheduler).**
- An 18:00 job notifies the site engineers and project managers of every active project on an
  active site that has no report for the day (BR-11).
- Notifications carry a `dedupe_key`, unique per user, so running the job twice (several API
  workers, a restart, the `send-reminders` command) never sends a reminder twice.
- Each job opens its own database session and logs instead of raising.
- A separate worker process is not needed at this scale. If one is added later, set
  `SITESENSE_SCHEDULER_ENABLED=false` on the API.

**Notifications are a shared table.** `notifications` holds per-user in-app alerts with an
internal link (a database constraint allows only `/path`, never `//host` or a URL). Phase 5
(approvals) and Phase 11 (alerts) reuse it.

## Consequences

- One report per project and day, rather than per site and day as worded in TC-03. In practice
  each project runs on one site; if a site ever hosts two projects, each files its own report.
- Photo processing is CPU-bound, so uploads have their own per-IP rate limit and a per-route
  body limit of `SITESENSE_MAX_PHOTO_BYTES` plus multipart overhead.
- Production must mount a persistent volume at the media root (`/data/media` in the
  production image) and back it up with the database.
