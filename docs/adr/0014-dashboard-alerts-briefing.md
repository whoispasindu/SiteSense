# ADR 0014: The dashboard, email alerts and the AI daily briefing

- Status: accepted
- Date: 2026-10-12

## Context

Phase 11 builds "one screen that tells a manager what needs attention today". The build guide asks
for:

- portfolio analytics (`GET /analytics/portfolio`);
- email notifications;
- an AI daily briefing with a rule-based fallback (`GET /briefing/today`);
- a weekly PDF (`GET /reports/weekly.pdf`).

The project owner decided:

- **The language model sees structured facts only:** scores, ranges, counts, project codes and
  names, rule IDs. Never report text or people's names, with a test that fails if any reach the
  request. The rule-based fallback stays for when the model is unavailable.
- **Model:** Claude Haiku, named by a setting so it can change. The API key is optional: without
  one, everyone gets the rule-based briefing. Every briefing is labelled "AI-written" or
  "Rule-based".
- **Email:**
  - urgent kinds go out at once: high risk (BR-10), stop-work (BR-11), rain on a pour (BR-06),
    and items waiting for the reader's approval;
  - everything else goes in an evening digest;
  - each user can turn either off, except stop-work;
  - the digest is skipped when there is nothing new;
  - emails are short with a link, and follow role visibility;
  - without SMTP settings, emails are logged instead of sent.
- **Weekly PDF:** a download on the dashboard plus a Monday 07:00 (site time) email. On by default
  for PMs, opt-in for QSs, and anyone can opt out. Only cost roles (PM, QS) can receive it.
- **SMS:** not now. It goes on the roadmap, and alerts sit behind one channel interface so an SMS
  adapter needs no change to the rules.

## Decision

### Portfolio analytics

`analytics_service.portfolio` makes one scoped call (BR-03) for the whole dashboard:

- **KPIs:** active projects, average progress against plan, behind plan, reports filed today,
  issues this week, open stop-work flags, high risk, and items waiting for you.
- **Cost against plan:** budget, committed and the forecast at current rates per project, plus
  the risk model's likely final cost. That cost is the budget moved by the overrun range, so the
  forecast always carries its range.
- **The risk ranking.**
- **Issue trends:** confirmed issues per week for 8 weeks, every week and category present.
- **Weather:** the saved 5-day forecast for each site.
- **The approval queue:** material requests at the reader's stage (never their own), approved
  requests for procurement, claims for the PM, and variations to price or decide.

Sections a role may not see are `null`, not empty. The arithmetic lives in `app/rules/kpis.py`,
tested on its own.

Weather comes from the forecast saved at 05:30, so the dashboard never waits on Open-Meteo. The
issue chart is one series (the weekly total), with categories in the tooltip and a ranked list.
Eight categories in eight colours would not read.

### The briefing

`app/ai/briefing` defines `Facts`, an allow-listed model:

- every field is a number, an enumerated word, a project code or a project name;
- `extra="forbid"` throughout, so a new field cannot slip in unnoticed;
- facts follow the reader's permissions (no risk without `risk:read`, no cost without `cost:read`).

Two writers share it:

- **The rule writer.** Fixed templates, most urgent first, 3 to 5 bullets. Forecasts carry their
  likely range.
- **The model writer.** One `messages.create` call with the fixed instruction and the facts as
  JSON. It uses a JSON-schema output whose project codes are an enum of the reader's own, with
  thinking off and low effort. The answer is validated: 3 to 5 bullets, known codes and source
  kinds, at most 300 characters each. **The server counts the sources**: the model only names the
  kinds. Any failure falls back to the rules with a note. Failures include a network error, a
  timeout, a rate limit, a refusal, a cut-off answer or an invalid answer.

Calls are limited per reader:

- one answer is reused while the facts' hash is unchanged;
- a new one comes at most every 15 minutes;
- after a failure, the model is retried after 10 minutes.

Without a key, the rule-based text is written fresh on every request and nothing is stored. The
connection to the database is released while the model writes.

`tests/test_briefing_leaks.py` runs the real SDK client over a fake transport for every reading
role, captures the HTTP body, and fails if any seeded secret appears in it. The seeded secrets
cover report text, issue snippets, action summaries, notes, comments, variation descriptions, the
client's name, site, task and supplier names, user names and emails.

### Email

- **The alert rules** (`alerts`) decide what is emailed and when.
- **A channel** (`channels.EmailChannel`, behind a `Channel` protocol) only delivers.
- **The transactional outbox.** `notification_service.send` writes the email row in the same
  transaction as the notification. A job every minute sends pending rows, records failures and
  retries up to five times. A slow mail server never slows a request or loses an alert.

An email body is the notification's title, one fixed sentence for its kind, a link into the app
and a link to the settings. It never includes the notification's body, which can hold a comment,
a name, an amount or a line of a report. The subject is stripped of line breaks. TLS is required
in production, and so is an `https` app link.

### The weekly PDF

ReportLab draws the PDF from the dashboard's numbers and the rule-based bullets, never the model,
so the same data gives the same PDF. It holds:

- KPIs;
- this week's points;
- a project table with likely ranges;
- issues per week.

Everything printed from the database is escaped before it reaches ReportLab's markup. The download
needs `cost:read` and is audited as a cost export. The Monday job queues one copy per person per
week.

## Consequences

- With no key and no SMTP, the whole phase works offline: the rule-based briefing, and emails in
  the log. This is how local development and the public demo run.
- Model costs are bounded. Each reader is limited as above, and the guide's advice to set a
  spending limit on the key is in the README.
- Alert text is consistent in the app and in email, and the email is deliberately poorer. Readers
  open the app for detail, where role visibility is enforced.
- The digest window is "since the last digest", or one day for a user's first. Turning the digest
  back on never sends a backlog.
- SMS needs only a new channel class and a phone number per user; the rules stay as they are.
