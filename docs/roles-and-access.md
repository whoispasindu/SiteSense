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

`backend/tests/test_role_matrix.py` calls every endpoint as every role. New endpoints must be added there.

## The menu

The web app builds the sidebar from `GET /me` permissions
([`navigation.ts`](../frontend/src/components/layout/navigation.ts)), so each role sees only its
own menu. This is a convenience: the API enforces the same permission on every call.
