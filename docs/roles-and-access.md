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
| Client | Assigned sites | Read progress, approve or query variations | See any internal cost |

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
| `PATCH /api/v1/projects/{id}` | Project Manager | Code and site are fixed |
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
| `POST /api/v1/material-requests/{id}/decision` | QS at the QS check, PM at PM approval, never the requester (BR-04); requester may cancel | Wrong stage or role: 403 (TC-01); invalid transition: 409. The QS may set `unit_price` when approving |
| `GET /api/v1/projects/{id}/boq-items` | PM, QS, Site Engineer | BOQ item picker with quantity already requested |
| `GET /api/v1/projects/{id}/budget` | PM, QS | Budget, approved, committed, spent per section (TC-07: never clients) |
| `GET /api/v1/suppliers` | PM, QS, Site Engineer, Procurement | Inactive suppliers only for procurement |
| `POST /api/v1/suppliers`, `PATCH /api/v1/suppliers/{id}` | Procurement | |
| `GET /api/v1/purchase-orders/ready` | Procurement | Approved requests not yet ordered (BR-05) |
| `GET /api/v1/purchase-orders`, `GET /api/v1/purchase-orders/{id}` | PM, QS, Site Engineer, Procurement | Site-scoped |
| `POST /api/v1/purchase-orders` | Procurement | Approved requests only; price never above the approved price |
| `POST /api/v1/purchase-orders/{id}/deliveries` | Procurement | Never more than ordered |

`backend/tests/test_role_matrix.py` calls every endpoint as every role. New endpoints must be added there.

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
- **Engineers do not set prices either.** Their requests start at the budgeted rate and the QS
  prices them at the QS check. A price sent by an engineer is refused (`422 price_not_allowed`).
- **Tested by** `backend/tests/test_cost_visibility.py`. It walks every endpoint an engineer can
  call after a full request-to-delivery flow and fails if any cost field appears at any depth. It
  also checks that PM, QS and procurement do receive them, and that clients reach none of these
  endpoints.

## The menu

The web app builds the sidebar from `GET /me` permissions
([`navigation.ts`](../frontend/src/components/layout/navigation.ts)), so each role sees only its
own menu. This is a convenience: the API enforces the same permission on every call.
