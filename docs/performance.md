# Performance and scalability

Phase 13. How SiteSense stays fast as data and users grow, and the load test that checks it.

## Load test result (16 October 2026)

**50 concurrent users, 5 minutes, 17,309 requests, 0 errors. Every target met.**

| Class | Target (95th percentile) | Requests | Errors | Median | 95th percentile | 99th percentile | Slowest |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Reads | under 500 ms | 14,762 | 0 | 63 ms | **280 ms** | 482 ms | 1,026 ms |
| Writes | under 1 s | 1,800 | 0 | 73 ms | **359 ms** | 561 ms | 895 ms |
| Heavy: what-if, weekly PDF, report analysis | under 2 s | 602 | 0 | 278 ms | **974 ms** | 1,559 ms | 1,978 ms |

The heavy endpoints on their own (95th percentile): weekly PDF 1,100 ms, report analysis 660 ms,
what-if 550 ms. Raw results: [`loadtest/results/`](../loadtest/results/) (per endpoint in
`*_stats.csv`, the classes above in `*_classes.json`, computed from every response time).

**Signing in** is measured separately, because password hashing (Argon2id) is slow on purpose. One
sign-in takes 0.30 s. Twelve sign-ins spread over the run, while the 50 users were working, took
0.30 to 0.44 s. The test's start-up burst, all 50 people signing in within 10 seconds, took 2.5 s
each (median): that many hashes at once compete for the CPU. A real company does not sign everyone
in within the same ten seconds, and the hashing cost is not lowered to make a benchmark look better.

### The machine

| | |
| --- | --- |
| Computer | Laptop, Intel Core i5-13420H (8 cores, 12 threads, 2.1 GHz base), 23.6 GB RAM, Samsung NVMe SSD |
| Operating system | Windows 11 Pro 10.0.26200 |
| Docker | Docker Desktop 29.8.2, WSL 2 (kernel 6.18), VM limit 12 CPUs and 11.5 GB |
| Stack | `docker-compose.prod.yml`: PostgreSQL 18.6, Python 3.13.16, Uvicorn with 4 workers, Caddy 2.10 (HTTPS), scheduler in its own container |
| Load generator | Locust 2.46.5 on the same laptop (it shares the CPU with the app, so the figures are conservative) |
| Data | The demo company (`seed-dev`): 3 open projects, a finished one with a year of deliveries, 6 users |

Mid-run, the API used about 2.4 CPU cores and 2.1 GB of memory, PostgreSQL about 0.6 cores.

### How it was run

```bash
cp .env.prod.example .env.prod          # fill in the secrets
docker compose -f docker-compose.prod.yml -f docker-compose.build.yml --env-file .env.prod up -d --build
docker compose -f docker-compose.prod.yml --env-file .env.prod run --rm backend python -m app.cli seed-dev
pip install -r loadtest/requirements.txt
locust -f loadtest/locustfile.py --host https://localhost --headless -u 50 -r 5 -t 5m \
    --csv loadtest/results/2026-10-16-50-users --only-summary
```

The run exits with an error if any class misses its target or any request fails.

The 50 people are 15 project managers, 10 quantity surveyors, 15 site engineers, 5 procurement
officers and 5 clients, each pausing 1 to 3 seconds between actions (about 58 requests a second in
all). Each works like their role:

- **Project managers:** the dashboard, the Havelock project page, approvals, the what-if planner and
  the weekly PDF.
- **Quantity surveyors:** costs, the BOQ, price checks and the weekly PDF.
- **Site engineers:** today's report and tasks, material requests (real ones, through the approval
  rules), and analysing today's report.
- **Procurement officers:** orders, suppliers and the supplier outlook.
- **Clients:** the portal.

Two settings differ from the defaults, only for the run, and only because of how the test is built:

- The 50 simulated people all come from one IP address and share the six demo accounts. So the
  sign-in budget per IP and the budgets per user were raised:
  `SITESENSE_LOGIN_RATE_PER_MINUTE=200`, `SITESENSE_WRITE_RATE_PER_MINUTE=2000`,
  `SITESENSE_HEAVY_RATE_PER_MINUTE=400` and `SITESENSE_ANALYZE_RATE_PER_MINUTE=400`.
- With the defaults, 15 people on one project manager account share that account's what-if and PDF
  budget, and get 429 (the first run showed exactly this). The budgets themselves are covered by
  `tests/test_write_limits.py`.

### What the load test found

The first full run met every target, but with little room: reads at 416 ms against 500. The
slowest read was the purchase-order list (95th percentile 1.1 s). Showing each order's total loaded
that order's lines in a separate query, and each line also pulled in its request, project, BOQ item
and requester. The lines now load in one batch, without the requests. A test fails if the number of
queries grows with the number of orders. After the fix, reads were at 280 ms and heavy requests at
974 ms (from 1,535 ms).

## Why it scales

### A stateless API

Sessions live in signed tokens and the database, never in the API process, so any number of API
processes can serve any request. The production stack runs 4 Uvicorn workers (`WEB_CONCURRENCY`).
More containers can run behind the proxy without code changes.

Two things are per process, and both are known:

- **Rate-limit counters.** With 4 workers, a budget of 10 sign-ins a minute is at most 40 in
  practice. Account lockout (5 wrong passwords) is kept in the database, so it holds across workers.
  A shared store (Redis) behind the same `RateLimiter` interface is the next step when several API
  machines are needed.
- **The risk and text models.** Each process loads them once and only reads them.

### Background jobs in their own process

Reminders, weather refresh, risk scoring, cost checks, the email outbox, digests, the weekly PDF,
and the demo reset in demo mode all run in the `scheduler` container (`python -m app.cli
run-scheduler`), one copy only. The API workers run with `SITESENSE_SCHEDULER_ENABLED=false`, so
adding workers never runs a job twice. Every job is also safe to run twice anyway (de-duplicated or
idempotent), so a restart in the middle does no harm.

### Indexes

Every column the app filters or joins on is indexed: `project_id` on every project table, the
dates that lists and features filter by (`daily_reports(project_id, report_date)`,
`risk_scores(project_id, score_date)`, `progress_snapshots(project_id, snapshot_date)`,
`weather_forecasts(site_id, forecast_date)`, `audit_logs(action, occurred_at)`), statuses, and the
lookups used in rules (`report_issues(project_id, status, confirmed_at)`).

Phase 13 audited every foreign key (`pg_constraint` against `pg_index`) and added the seven that
joins and filters use but had no index: `tasks.boq_section_id`, `report_progress.task_id`,
`notifications.project_id`, `progress_claim_lines.section_id`, `variation_orders.section_id` and
`.task_id`, `report_actions.request_id`, plus `notifications(user_id, created_at)` for the bell
(migration 0018). The 18 left without an index record who did something (`decided_by`,
`created_by` and similar). Nothing filters on them, and users are deactivated, never deleted, so
no delete ever has to scan them.

### Pagination

Lists that grow with time are paged (`limit` up to 100, `offset`), with a total where the screen
needs one: daily reports, material requests, purchase orders, users, the audit log and shared
photos. Notifications show the newest 30, and the evening digest the newest 25. The remaining lists
are bounded by the size of one project rather than by time: its BOQ, programme, claims (one a
month), variations, open follow-ups, and the orders waiting to be placed.

### Caching

- **Weather:** each site's 14-day forecast is fetched at 05:30 and kept in the database. Pages and
  rules read the copy, and keep working, with a "stale" note, if the weather service is down.
- **Risk scores:** worked out every morning, and again after each daily report, by the background
  job. Dashboards read the stored score, never run the model.
- **The AI briefing:** one answer per person per day, reused while the facts behind it are
  unchanged; a new one is asked for at most every 15 minutes.
- **The web app:** built files have content hashes in their names and are cached by browsers for a
  year (`immutable`). The HTML shell is never cached, so a release reaches everyone at once.
- **Not cached on purpose:** API responses (`Cache-Control: no-store`; they carry costs and
  personal data), and dashboard figures, which are computed live. A cached figure would hide your
  own approval for a while after you made it. The load test shows they are fast enough without
  caching.

### Limits that protect the server

Request bodies are capped (1 MB; 6 MB for a BOQ file, 10 MB for a photo), every database
statement has a timeout, the connection pool is bounded, and every write has a per-user budget,
with smaller ones for the heavy endpoints ([security.md](security.md)).
