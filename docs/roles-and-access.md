# Roles and access

SiteSense has six roles. Endpoints never check role names directly: they require a
**permission**, and [`backend/app/core/permissions.py`](../backend/app/core/permissions.py) maps
roles to permissions. That file is the single source of truth; this page explains it.

## Roles

| Role | Works on | Can | Cannot |
| --- | --- | --- | --- |
| Company Admin | All sites | Manage users, sites and roles; read the audit log | Approve anything on a project (segregation of duties) |
| Project Manager | Assigned sites | Approve requests above the QS limit, variations, schedule changes; use the what-if planner | Manage users |
| Quantity Surveyor | Assigned sites | Edit BOQ and budgets, approve requests within limit, prepare claims | Approve above limit |
| Site Engineer | Assigned sites | Submit daily reports and material requests, confirm AI tags | Approve requests (TC-01) |
| Procurement Officer | All sites | Manage suppliers, issue POs after approval, record deliveries | Approve requests |
| Client | **Linked projects only** (Phase 12) | Follow progress, the published handover date, milestones, shared photos and approved claims; approve or query variations | See any internal cost, or any project they are not linked to, even on the same site |

## Site scoping (groundwork for BR-03)

Project Managers, Quantity Surveyors, Site Engineers and Clients only reach sites they are
assigned to. Every site-data endpoint uses the helpers in
[`backend/app/api/deps.py`](../backend/app/api/deps.py):

- `accessible_site_ids(user)`: the user's site IDs, or `None` for company-wide roles
- `scope_to_user_sites(query, column, user)`: filters any list query
- `ensure_site_access(user, site_id)`: raises **404** (not 403) for an unassigned site, so users
  cannot probe which sites exist

## Phase 1 endpoints

| Method and path | Who | Notes |
| --- | --- | --- |
| `POST /api/v1/auth/login` | Anyone | Rate-limited per IP; locks the account for 15 min after 5 failures |
| `POST /api/v1/auth/refresh` | Holder of the refresh cookie | Rotates the token; a replayed token revokes the whole session family |
| `POST /api/v1/auth/logout` | Holder of the refresh cookie | Revokes the session family, clears the cookie |
| `POST /api/v1/auth/change-password` | Signed in (also with a temporary password) | Signs out every other device |
| `GET /api/v1/me` | Signed in | Profile, permissions and sites, used to build the menu |
| `GET /api/v1/sites` | Signed in | Active sites the user may work on |
| `GET/POST /api/v1/admin/users`, `GET/PATCH /admin/users/{id}` | Admin | Create returns a one-time temporary password |
| `POST /api/v1/admin/users/{id}/sites` | Admin | Replaces the site set; company-wide roles cannot be assigned sites |
| `POST /api/v1/admin/users/{id}/reset-password` | Admin | New temporary password; all sessions end |
| `GET/POST /api/v1/admin/sites`, `PATCH /admin/sites/{id}` | Admin | |
| `GET /api/v1/admin/audit-logs` | Admin | Paginated, filterable by event |

## Phase 2 endpoints

| Method and path | Who | Notes |
| --- | --- | --- |
| `GET /api/v1/projects` | PM, QS, Site Engineer, Procurement | Filtered to the user's sites; `status` and `q` filters |
| `POST /api/v1/projects` | Project Manager | Only on a site the PM is assigned to |
| `GET /api/v1/projects/{id}` | PM, QS, Site Engineer, Procurement | 404 for projects on other sites |
| `PATCH /api/v1/projects/{id}` | Project Manager | Code and site are fixed. Includes the planned crew (a risk model input) |
| `GET /api/v1/projects/{id}/boq` | PM, QS, Site Engineer, Procurement | Sections, items, totals |
| `POST /api/v1/projects/{id}/boq/import?dry_run=` | Quantity Surveyor | Multipart file; dry run by default |
| `PATCH /api/v1/projects/{id}/budget-lines/{line_id}` | Quantity Surveyor | Adjust a section's cost budget |

## Phase 3 endpoints

| Method and path | Who | Notes |
| --- | --- | --- |
| `GET /api/v1/schedule/summary` | PM, QS, Site Engineer | Planned vs actual for every visible project |
| `GET /api/v1/projects/{id}/tasks` | PM, QS, Site Engineer | Tasks with plan-today and state |
| `POST /api/v1/projects/{id}/tasks` | Project Manager | |
| `PATCH /api/v1/tasks/{id}` | PM (any field), Site Engineer (`percent_complete` only) | Records a progress snapshot |
| `DELETE /api/v1/tasks/{id}` | Project Manager | |
| `GET /api/v1/projects/{id}/progress` | PM, QS, Site Engineer | S-curve points, planned, actual, variance |

## Phase 4 endpoints

| Method and path | Who | Notes |
| --- | --- | --- |
| `GET /api/v1/reports/today` | PM, QS, Site Engineer | Today's report status for every visible active project (BR-07) |
| `GET /api/v1/projects/{id}/reports` | PM, QS, Site Engineer | Report history, newest first, paginated |
| `POST /api/v1/projects/{id}/reports` | Site Engineer | One per project per day (TC-03); progress updates the programme |
| `GET /api/v1/reports/{id}` | PM, QS, Site Engineer | |
| `PATCH /api/v1/reports/{id}` | Site Engineer, **author only**, on the day of submission | |
| `POST /api/v1/reports/{id}/photos` | Site Engineer, **author only**, on the day of submission | Re-encoded JPEG; rate limited |
| `GET /api/v1/photos/{id}` | PM, QS, Site Engineer | Authenticated and site-scoped; never a public URL |
| `DELETE /api/v1/photos/{id}` | Site Engineer, **author only**, on the day of submission | |
| `GET /api/v1/projects/{id}/weather` | Every role that reads projects | Cached five-day forecast; stale cache when the service is down (TC-08) |
| `GET /api/v1/notifications` | Everyone | Own notifications only |
| `POST /api/v1/notifications/{id}/read`, `POST /api/v1/notifications/read-all` | Everyone | Someone else's notification answers 404 |

Every report, photo and weather call goes through the project's site scope: out of scope
answers `404`, exactly like a missing record.

## Phase 5 endpoints

| Method and path | Who | Notes |
| --- | --- | --- |
| `GET /api/v1/material-requests` | PM, QS, Site Engineer, Procurement | Scoped to the caller's sites (procurement: company-wide); pipeline counts |
| `POST /api/v1/material-requests/check` | PM, QS, Site Engineer | Rule results for a draft, nothing saved |
| `POST /api/v1/material-requests` | PM, QS, Site Engineer | BR-02 blocks; BR-01 and BR-13 set the approval level. Only PM and QS may send a price |
| `GET /api/v1/material-requests/{id}` | PM, QS, Site Engineer, Procurement | Live rule results, history, order, allowed actions |
| `PATCH /api/v1/material-requests/{id}` | The requester, after "change requested" | Saving resubmits to the QS |
| `POST /api/v1/material-requests/{id}/decision` | QS at the QS check, PM at PM approval, never the requester (BR-04); requester may cancel | Wrong stage or role: 403 (TC-01); invalid transition: 409. The QS enters `unit_price` when approving; required while the price is pending (`422 price_required`) |
| `GET /api/v1/projects/{id}/boq-items` | PM, QS, Site Engineer | BOQ item picker with quantity already requested |
| `GET /api/v1/projects/{id}/budget` | PM, QS | Budget, approved, committed, spent per section (TC-07: never clients) |
| `GET /api/v1/suppliers` | PM, QS, Site Engineer, Procurement | Inactive suppliers only for procurement |
| `POST /api/v1/suppliers`, `PATCH /api/v1/suppliers/{id}` | Procurement | |
| `GET /api/v1/purchase-orders/ready` | Procurement | Approved requests not yet ordered (BR-05) |
| `GET /api/v1/purchase-orders`, `GET /api/v1/purchase-orders/{id}` | PM, QS, Site Engineer, Procurement | Site-scoped |
| `POST /api/v1/purchase-orders` | Procurement | Approved requests only (BR-05). Lines failing BR-14 or BR-13 at the order price go back to PM approval; `201` with the order, or `200` with `order: null` if every line went back |
| `POST /api/v1/purchase-orders/{id}/deliveries` | Procurement | Never more than ordered |

## Phase 6 endpoints

| Method and path | Who | Notes |
| --- | --- | --- |
| `GET /api/v1/projects/{id}/risk` | PM, QS | Latest forecast with drivers, missing-data notes and model version; 14-day history. 404 on other sites |
| `GET /api/v1/risk/projects` | PM, QS | Open projects on the caller's sites, highest risk first |

Scores are written only by the scheduler, after daily reports and by the CLI; no endpoint writes them.

## Phase 13 endpoints

**Two-step sign-in.** Required for the Company Admin, Project Manager, Quantity Surveyor and
Procurement Officer (`MFA_ROLES` in `permissions.py`); optional for Site Engineers and Clients.
Until a required role has set it up, every endpoint except the ones below and `GET /api/v1/me`
answers 403 `mfa_setup_required`. In demo mode, only the accounts the demo seed created skip it.

**Request budgets.** Every write has a budget per signed-in user (120 a minute; per IP before
sign-in). What-if and the weekly PDF have 20 a minute, report analysis 30.

| Method and path | Who | Notes |
| --- | --- | --- |
| `POST /api/v1/auth/login` | Anyone | With two-step sign-in on: a 5-minute challenge instead of a session |
| `POST /api/v1/auth/mfa/verify` | Holder of a challenge | A code from the app or a recovery code. Wrong codes count towards lockout |
| `GET /api/v1/auth/mfa` | Signed-in user, for themselves | On or off, required or optional, recovery codes left |
| `POST /api/v1/auth/mfa/setup`, `.../enable` | Signed-in user, for themselves | QR code and key; enabling needs a valid code and returns 10 recovery codes once. Audited |
| `POST /api/v1/auth/mfa/recovery-codes` | Signed-in user with two-step on | New codes (old ones stop working), needs a current code. Audited |
| `POST /api/v1/auth/mfa/disable` | Site Engineer or Client with two-step on | Needs a current code; refused for required roles. Audited |
| `POST /api/v1/admin/users/{id}/mfa/reset` | Company Admin | **Never their own account.** Clears the enrolment and signs the person out everywhere. Audited |

## Phase 12 endpoints

**Clients are linked to projects, not sites.** The Company Admin links each client account to the
projects it may see. A project the client is not linked to (and anything on it: its variations,
claims and photos) answers exactly like one that does not exist. Only linked clients are notified.
Tested with two clients on one site in `backend/tests/test_client_portal.py`.

| Method and path | Who | Notes |
| --- | --- | --- |
| `GET /api/v1/client/projects` | Client | Their linked projects, not cancelled |
| `GET /api/v1/client/projects/{id}` | Client, linked | Progress, the published handover date and history, milestones, shared photos. Client-only schema, no internal fields (TC-07) |
| `GET /api/v1/client/projects/{id}/claims` | Client, linked | Approved and paid claims, the contract value, the retention held |
| `GET /api/v1/client/photos/{id}` | Client, linked | Shared photos only, with no metadata |
| `GET /api/v1/client/variations`, `/client/variations/{id}`, `POST /variations/{id}/client-decision` | Client, linked | Phase 8, now per project |
| `GET /api/v1/projects/{id}/handover` | PM, QS, Site Engineer | The published date, history, suggestions and reminder |
| `POST /api/v1/projects/{id}/handover`, `.../handover/confirm` | **Project manager only** | Publish a date with a reason for the client, or confirm it unchanged. Audited; clients told of a new date |
| `GET /api/v1/projects/{id}/photos` | PM, QS, Site Engineer | Every report photo with whether the client sees it |
| `POST /api/v1/projects/{id}/photos/client-share` | **Project manager only** | Share or unshare up to 100 of the project's photos; all-or-nothing; audited |
| `PATCH /api/v1/tasks/{id}` (`client_milestone`, `milestone_name`) | **Project manager only** | Strict boolean; a name only on a milestone |
| `PATCH /api/v1/projects/{id}` (`defects_period_months`) | **Project manager only** | Whole months, 0 to 60 (strict); sets when the client's retention is due back |
| `GET /api/v1/admin/projects`, `POST /api/v1/admin/users/{id}/projects` | Company Admin | Link a client account to projects (replaces the set; clients only; audited). The list carries no figures |

## Phase 11 endpoints

| Method and path | Who | Notes |
| --- | --- | --- |
| `GET /api/v1/analytics/portfolio` | PM, QS, Site Engineer, Procurement | One call for the dashboard, scoped to the user's sites. `cost` only with `cost:read` (PM, QS), `risk` and the high-risk count only with `risk:read`; otherwise `null`. The approval queue holds only what this person acts on, never their own request or variation, and no amounts |
| `GET /api/v1/briefing/today` | PM, QS, Site Engineer, Procurement | Labelled AI-written or rule-based. Built from the reader's own allow-listed facts, which follow the same visibility; the model never receives report text, comments or names |
| `GET /api/v1/reports/weekly.pdf` | **PM, QS only** (`cost:read`) | Holds budgets and forecasts. Audited (`report.weekly_downloaded`); `Cache-Control: no-store` |
| `GET`, `PUT /api/v1/me/notification-preferences` | Everyone | Own choices only. Stop-work emails cannot be turned off; the weekly PDF only for PM and QS (`422` otherwise); strict booleans; changes audited |

**Emails follow role visibility.** An email carries the alert's title, a fixed sentence and links,
never the alert's body (comments, names, amounts, report text). The weekly PDF goes only to cost
roles. Tested by `backend/tests/test_alerts_email.py`.

## Phase 10 endpoints

| Method and path | Who | Notes |
| --- | --- | --- |
| `GET /api/v1/projects/{id}/risk`, `GET /api/v1/risk/projects` | PM, QS | Now with the likely range of every forecast (`ranges`), and the score's range in the 14-day history |
| `POST /api/v1/projects/{id}/risk/what-if` | **Project manager only** (`risk:what_if`) | Up to four recovery actions, each once, with an optional cost (LKR, 2 decimals). Calculates only: nothing is stored or changed. Site-scoped (404 otherwise) |
| `GET /api/v1/suppliers/{id}/on-time` | PM, QS, Site Engineer, Procurement | The supplier's chance with its range and deliveries; for a project and date if given (site-scoped) |
| `GET /api/v1/projects/{id}/supplier-outlook` | PM, QS, Site Engineer, Procurement | Active suppliers for an order on the project, best first, and its approved critical-path requests. Site-scoped |
| `GET /api/v1/material-requests/{id}/critical-path` | PM, QS, Site Engineer, Procurement | Whether it counts for BR-12, and why. Site-scoped |
| `PUT /api/v1/material-requests/{id}/critical-path` | **Project manager only** | `true`, `false` or `null` (back to the programme); strict booleans only; audited |

## Phase 9 endpoints

| Method and path | Who | Notes |
| --- | --- | --- |
| `GET /api/v1/projects/{id}/network` | PM, QS, Site Engineer | Critical path, forecast and slip per task, links, open stop-work flags, rain on pour days, warnings. 404 on other sites |
| `POST /api/v1/projects/{id}/dependencies` | PM | Finish-to-start, lag 0–365 working days; both tasks in the project; a loop is refused (`422 dependency_loop`); a duplicate is 409 |
| `DELETE /api/v1/dependencies/{id}` | PM | Site-scoped (404 otherwise) |
| `GET /api/v1/admin/holidays`, `POST /api/v1/admin/holidays`, `DELETE /api/v1/admin/holidays/{id}` | Company Admin | The company's holidays (2000 to 2100), audited; warns when next year has none |
| `PUT /api/v1/report-actions/{id}/stop-scope` | **Project manager only** (BR-11) | What an open stop-work flag stops: chosen tasks or the whole project. Others with report access get 403; a cleared flag 409. Re-scores the project's risk |

A stopped task refuses progress (`422 stop_work`) through `PATCH /api/v1/tasks/{id}` and daily
reports alike, until the project manager clears the flag. `POST /api/v1/reports/{id}/issues/confirm`
now takes `stop_work_scope` (`tasks` or `project`) and `stop_work_task_ids`. Projects carry a
`working_week` (ISO weekday digits, Monday to Saturday by default), set when the project is created or edited.

## Phase 8 endpoints

| Method and path | Who | Notes |
| --- | --- | --- |
| `GET /api/v1/cost/overview` | PM, QS | Projects on the caller's sites: contract, budget, forecast, claims; what waits for the caller |
| `GET /api/v1/projects/{id}/budget` | PM, QS | Now with forecast final cost, variance and trend per section |
| `GET /api/v1/projects/{id}/claims` | PM, QS | Claims, and the sections a new claim starts from |
| `POST /api/v1/projects/{id}/claims/check` | QS | BR-08 calculation for a draft, nothing saved |
| `POST /api/v1/projects/{id}/claims` | QS | One waits for the PM at a time (409) |
| `GET /api/v1/claims/{id}` | PM, QS | |
| `POST /api/v1/claims/{id}/decision` | PM | Approve, or return with a comment |
| `POST /api/v1/claims/{id}/payment` | QS | Approved claims; date between approval and today |
| `GET /api/v1/projects/{id}/variations`, `GET /api/v1/variations/{id}` | PM, QS | |
| `POST /api/v1/projects/{id}/variations` | PM, QS | Only the QS may include the price |
| `POST /api/v1/variations/{id}/price` | QS | Routes by BR-09 |
| `POST /api/v1/variations/{id}/revision` | The raiser, or a QS | Queried variations only; priced again |
| `POST /api/v1/variations/{id}/decision` | PM, never on their own variation | Approve, query or reject |
| `POST /api/v1/variations/{id}/withdraw` | The raiser | Open variations only |
| `GET /api/v1/client/variations`, `GET /api/v1/client/variations/{id}` | Client | Only those sent to them, on their sites; no internal costs or comments (404 otherwise) |
| `POST /api/v1/variations/{id}/client-decision` | Client | Approve or query (TC-10) |
| `GET /api/v1/admin/variation-limits`, `PUT /api/v1/admin/projects/{id}/variation-limit` | Company Admin | BR-09 limit; a reason is required and audited |

`PATCH /api/v1/projects/{id}` no longer changes the contract value or planned end once the project
is past planning (or has a claim or variation): those change through approved variations.

## Phase 7 endpoints

| Method and path | Who | Notes |
| --- | --- | --- |
| `GET /api/v1/reports/{id}/issues` | PM, QS, Site Engineer | Tags and follow-ups; `can_confirm` only for the author on the day |
| `POST /api/v1/reports/{id}/analyze` | Site Engineer, **author only**, on the day of the report | Stores suggestions only; again replaces them until confirmed (then 409). Rate limited per client |
| `POST /api/v1/reports/{id}/issues/confirm` | Site Engineer, **author only**, on the day of the report | Once. Follow-ups must match a confirmed issue (422). Re-scores the project's risk |
| `POST /api/v1/report-actions/{id}/close` | Stop-work: **project manager only** (BR-11). Other open follow-ups: the author or a PM | Already closed: 409 |
| `GET /api/v1/projects/{id}/report-actions` | PM, QS, Site Engineer | Open follow-ups on the project, stop-work first |

All of them go through the report's or project's site scope (404 elsewhere). A material request
raised with `report_action_id` must belong to the same project and an open material follow-up.

`backend/tests/test_role_matrix.py` calls every endpoint as every role. New endpoints must be added
there, and `test_every_api_route_is_in_the_matrix` fails if one is missing.

## Rates and amounts

Only the project manager, quantity surveyor and procurement officer (permission `rates:read`)
receive rates and amounts: contract values, BOQ rates and totals, budget lines, request prices and
values, purchase-order prices and totals. Site engineers and clients never do, not in the screen
and not in the JSON.

- **How it is enforced.** Every response that can carry money has two schemas: a base schema
  without cost fields, and a subclass that adds them. `app/services/visibility.py` hands the base
  version to everyone without `rates:read`. The base schemas do not declare cost fields, so they
  cannot be filled by mistake. This covers the project list and detail, BOQ, schedule summary,
  BOQ item picker, material requests (list, detail, rule check) and purchase orders.
- **What engineers see.** On the BOQ tab and in the item picker: item, unit, BOQ quantity,
  quantity requested so far and remaining. Rule results are limited to the quantity rule (BR-02);
  BR-01 and BR-13 compare prices, so engineers never receive them. They do see which rules sent a
  request to the PM, but not the figures.
- **Engineers do not set prices either.** Their requests start with the price pending, and the QS
  must enter the quoted price before approving. A price sent by an engineer is refused
  (`422 price_not_allowed`).
- **Free text too.** When a request goes back to the PM at ordering, its history step names the
  rule in words without amounts. The detector also fails on any string containing "LKR".
- **Tested by** `backend/tests/test_cost_visibility.py`. It walks every endpoint an engineer can
  call after a full request-to-delivery flow and fails if any cost field appears at any depth. It
  also checks that PM, QS and procurement do receive them, and that clients reach none of these
  endpoints.

## The menu

The web app builds the sidebar from `GET /me` permissions
([`navigation.ts`](../frontend/src/components/layout/navigation.ts)), so each role sees only its
own menu. This is a convenience: the API enforces the same permission on every call.
