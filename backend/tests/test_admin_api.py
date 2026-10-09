from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.permissions import Role
from app.models import AuditLog, Site, User
from tests.conftest import PASSWORD, bearer, login

USERS = "/api/v1/admin/users"
SITES = "/api/v1/admin/sites"


@pytest.fixture
def admin(make_user: Callable[..., User]) -> User:
    return make_user(Role.ADMIN, email="admin@company.lk")


@pytest.fixture
def admin_headers(api: TestClient, admin: User) -> dict[str, str]:
    return bearer(login(api, admin.email))


def last_audit(db: Session) -> AuditLog:
    db.expire_all()
    entry = db.scalars(select(AuditLog).order_by(AuditLog.occurred_at.desc(), AuditLog.id.desc())).first()
    assert entry is not None
    return entry


# --- Creating users -------------------------------------------------------------------------


def test_admin_creates_user_with_one_time_temporary_password(
    api: TestClient, admin: User, admin_headers: dict[str, str], make_site: Callable[..., Site], db: Session
) -> None:
    site = make_site("KDY-02")

    response = api.post(
        USERS,
        json={"email": "New.Engineer@Site.lk", "full_name": "  Nuwan Silva ", "role": "site_engineer",
              "site_ids": [str(site.id)]},
        headers=admin_headers,
    )  # fmt: skip

    assert response.status_code == 201
    body = response.json()
    assert body["user"]["email"] == "new.engineer@site.lk"
    assert body["user"]["full_name"] == "Nuwan Silva"
    assert body["user"]["must_change_password"] is True
    assert [s["code"] for s in body["user"]["sites"]] == ["KDY-02"]
    temporary = body["temporary_password"]

    entry = last_audit(db)
    assert entry.action == "user.created"
    assert entry.actor_id == admin.id
    assert temporary not in str(entry.details)
    stored = db.scalar(select(User).where(User.email == "new.engineer@site.lk"))
    assert stored is not None
    assert temporary not in stored.password_hash

    # The new user can sign in once with it, and is then forced to change it.
    token = login(api, "new.engineer@site.lk", temporary)
    assert (
        api.get("/api/v1/sites", headers=bearer(token)).json()["error"]["code"] == "password_change_required"
    )


def test_duplicate_email_is_a_conflict(
    api: TestClient, admin_headers: dict[str, str], make_user: Callable[..., User]
) -> None:
    make_user(email="taken@site.lk")

    response = api.post(
        USERS,
        json={"email": "TAKEN@site.lk", "full_name": "Copy Cat", "role": "client"},
        headers=admin_headers,
    )

    assert response.status_code == 409


@pytest.mark.parametrize("role", ["admin", "procurement_officer"])
def test_company_wide_roles_cannot_be_assigned_sites(
    api: TestClient, admin_headers: dict[str, str], make_site: Callable[..., Site], role: str
) -> None:
    site = make_site()

    response = api.post(
        USERS,
        json={
            "email": f"{role}@site.lk",
            "full_name": "Whole Company",
            "role": role,
            "site_ids": [str(site.id)],
        },
        headers=admin_headers,
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "business_rule_violation"


def test_unknown_or_inactive_sites_are_rejected(
    api: TestClient, admin_headers: dict[str, str], make_site: Callable[..., Site]
) -> None:
    closed = make_site("OLD-01", active=False)
    base = {"email": "x@site.lk", "full_name": "Someone", "role": "site_engineer"}

    unknown = api.post(USERS, json={**base, "site_ids": ["00000000-0000-0000-0000-000000000000"]},
                       headers=admin_headers)  # fmt: skip
    inactive = api.post(USERS, json={**base, "site_ids": [str(closed.id)]}, headers=admin_headers)

    assert unknown.status_code == inactive.status_code == 422


def test_user_input_is_validated(api: TestClient, admin_headers: dict[str, str]) -> None:
    cases = [
        {"email": "bad", "full_name": "Ok Name", "role": "client"},
        {"email": "a@b.lk", "full_name": "A", "role": "client"},
        {"email": "a@b.lk", "full_name": "Ok Name", "role": "superuser"},
        {"email": "a@b.lk", "full_name": "Ok Name", "role": "client", "is_admin": True},
    ]
    for body in cases:
        assert api.post(USERS, json=body, headers=admin_headers).status_code == 422, body


# --- Listing and updating -------------------------------------------------------------------


def test_list_users_supports_filters_and_pagination(
    api: TestClient, admin_headers: dict[str, str], make_user: Callable[..., User]
) -> None:
    for _ in range(3):
        make_user(Role.CLIENT)
    make_user(Role.SITE_ENGINEER, active=False)

    clients = api.get(USERS, params={"role": "client"}, headers=admin_headers).json()
    inactive = api.get(USERS, params={"active": "false"}, headers=admin_headers).json()
    page = api.get(USERS, params={"limit": 2, "offset": 0}, headers=admin_headers).json()

    assert clients["total"] == 3
    assert inactive["total"] == 1
    assert len(page["items"]) == 2
    assert page["total"] == 5  # 3 clients + 1 engineer + the admin
    assert api.get(USERS, params={"limit": 1000}, headers=admin_headers).status_code == 422


def test_deactivation_revokes_access_immediately(
    api: TestClient, admin_headers: dict[str, str], make_user: Callable[..., User], db: Session
) -> None:
    worker = make_user(Role.SITE_ENGINEER, email="leaving@site.lk")
    worker_token = login(api, "leaving@site.lk")

    response = api.patch(f"{USERS}/{worker.id}", json={"is_active": False}, headers=admin_headers)

    assert response.status_code == 200
    assert response.json()["is_active"] is False
    assert last_audit(db).action == "user.deactivated"
    assert api.get("/api/v1/me", headers=bearer(worker_token)).status_code == 401
    assert (
        api.post("/api/v1/auth/login", json={"email": "leaving@site.lk", "password": PASSWORD}).status_code
        == 401
    )

    api.patch(f"{USERS}/{worker.id}", json={"is_active": True}, headers=admin_headers)
    assert last_audit(db).action == "user.reactivated"
    login(api, "leaving@site.lk")


def test_role_change_invalidates_tokens_and_clears_sites_for_company_wide_roles(
    api: TestClient,
    admin_headers: dict[str, str],
    make_user: Callable[..., User],
    make_site: Callable[..., Site],
) -> None:
    user = make_user(Role.SITE_ENGINEER, email="promoted@site.lk", sites=[make_site()])
    token = login(api, "promoted@site.lk")

    response = api.patch(f"{USERS}/{user.id}", json={"role": "procurement_officer"}, headers=admin_headers)

    assert response.status_code == 200
    assert response.json()["role"] == "procurement_officer"
    assert response.json()["sites"] == []
    assert api.get("/api/v1/me", headers=bearer(token)).status_code == 401


def test_admin_cannot_lock_themselves_out(
    api: TestClient, admin: User, admin_headers: dict[str, str]
) -> None:
    deactivate_self = api.patch(f"{USERS}/{admin.id}", json={"is_active": False}, headers=admin_headers)
    demote_self = api.patch(f"{USERS}/{admin.id}", json={"role": "client"}, headers=admin_headers)
    reset_self = api.post(f"{USERS}/{admin.id}/reset-password", headers=admin_headers)

    assert deactivate_self.status_code == demote_self.status_code == reset_self.status_code == 422


def test_company_keeps_at_least_one_active_admin(
    api: TestClient, admin: User, make_user: Callable[..., User]
) -> None:
    other_admin = make_user(Role.ADMIN, email="second-admin@company.lk")
    headers = bearer(login(api, other_admin.email))

    # Two admins: the second may deactivate the first.
    assert api.patch(f"{USERS}/{admin.id}", json={"is_active": False}, headers=headers).status_code == 200
    # Now one admin is left; nobody may remove them (self-removal is blocked separately).
    assert api.patch(f"{USERS}/{other_admin.id}", json={"role": "client"}, headers=headers).status_code == 422


def test_update_of_missing_user_is_404(api: TestClient, admin_headers: dict[str, str]) -> None:
    response = api.patch(f"{USERS}/00000000-0000-0000-0000-000000000000", json={"full_name": "Nobody"},
                         headers=admin_headers)  # fmt: skip
    assert response.status_code == 404


# --- Sites and assignments ------------------------------------------------------------------


def test_assign_sites_replaces_the_set_and_is_audited(
    api: TestClient, admin_headers: dict[str, str], make_user: Callable[..., User],
    make_site: Callable[..., Site], db: Session,
) -> None:  # fmt: skip
    first, second, third = make_site("A-01"), make_site("B-02"), make_site("C-03")
    user = make_user(Role.QUANTITY_SURVEYOR, sites=[first])

    response = api.post(f"{USERS}/{user.id}/sites", json={"site_ids": [str(second.id), str(third.id)]},
                        headers=admin_headers)  # fmt: skip

    assert response.status_code == 200
    assert [s["code"] for s in response.json()["sites"]] == ["B-02", "C-03"]
    entry = last_audit(db)
    assert entry.action == "user.sites_assigned"
    assert entry.details == {"from": ["A-01"], "to": ["B-02", "C-03"]}


def test_reset_password_issues_new_temporary_password_and_ends_sessions(
    api: TestClient, admin_headers: dict[str, str], make_user: Callable[..., User]
) -> None:
    user = make_user(email="forgot@site.lk")
    old_token = login(api, "forgot@site.lk")

    response = api.post(f"{USERS}/{user.id}/reset-password", headers=admin_headers)

    assert response.status_code == 200
    temporary = response.json()["temporary_password"]
    assert api.get("/api/v1/me", headers=bearer(old_token)).status_code == 401
    me = api.get("/api/v1/me", headers=bearer(login(api, "forgot@site.lk", temporary))).json()
    assert me["must_change_password"] is True


def test_site_crud_and_validation(api: TestClient, admin_headers: dict[str, str], db: Session) -> None:
    created = api.post(SITES, json={"code": "col-12", "name": "Marine Drive Tower", "location": "Colombo 03",
                                    "latitude": 6.9, "longitude": 79.85}, headers=admin_headers)  # fmt: skip
    assert created.status_code == 201
    assert created.json()["code"] == "COL-12"
    assert last_audit(db).action == "site.created"

    duplicate = api.post(SITES, json={"code": "COL-12", "name": "Again", "location": "Colombo"},
                         headers=admin_headers)  # fmt: skip
    assert duplicate.status_code == 409
    for bad in ({"code": "bad code!", "name": "X Site", "location": "Galle"},
                {"code": "OK-1", "name": "X Site", "location": "Galle", "latitude": 120}):  # fmt: skip
        assert api.post(SITES, json=bad, headers=admin_headers).status_code == 422

    site_id = created.json()["id"]
    updated = api.patch(f"{SITES}/{site_id}", json={"is_active": False}, headers=admin_headers)
    assert updated.status_code == 200
    assert updated.json()["is_active"] is False
    assert any(s["code"] == "COL-12" for s in api.get(SITES, headers=admin_headers).json())
    missing = api.patch(f"{SITES}/00000000-0000-0000-0000-000000000000", json={"name": "Nope Site"},
                        headers=admin_headers)  # fmt: skip
    assert missing.status_code == 404


def test_audit_log_lists_recent_events_with_actor_names(
    api: TestClient, admin: User, admin_headers: dict[str, str]
) -> None:
    api.post(SITES, json={"code": "AUD-1", "name": "Audit Site", "location": "Kandy"}, headers=admin_headers)

    page = api.get("/api/v1/admin/audit-logs", headers=admin_headers).json()
    only_sites = api.get("/api/v1/admin/audit-logs", params={"action": "site.created"}, headers=admin_headers)

    assert page["items"][0]["action"] == "site.created"
    assert page["items"][0]["actor_name"] == admin.full_name
    assert {item["action"] for item in only_sites.json()["items"]} == {"site.created"}
    injection = api.get("/api/v1/admin/audit-logs", params={"action": "x'; drop table users;--"},
                        headers=admin_headers)  # fmt: skip
    assert injection.status_code == 422
