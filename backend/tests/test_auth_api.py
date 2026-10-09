from collections.abc import Callable
from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.permissions import Role
from app.models import AuditLog, RefreshToken, User
from app.services.auth_service import REFRESH_GRACE_SECONDS
from tests.conftest import PASSWORD, bearer, login

LOGIN = "/api/v1/auth/login"
REFRESH = "/api/v1/auth/refresh"
LOGOUT = "/api/v1/auth/logout"
ME = "/api/v1/me"
COOKIE = "sitesense_refresh"


def use_cookie(api: TestClient, value: str) -> None:
    """Present a specific refresh token, as a browser (or an attacker) holding it would."""
    domain = next((c.domain for c in api.cookies.jar if c.name == COOKIE), "testserver.local")
    api.cookies.clear()
    api.cookies.set(COOKIE, value, domain=domain, path="/api/v1/auth")


def refresh_with(api: TestClient, value: str):  # type: ignore[no-untyped-def]
    use_cookie(api, value)
    return api.post(REFRESH)


def audit_actions(db: Session, user: User | None = None) -> list[str]:
    stmt = select(AuditLog.action).order_by(AuditLog.occurred_at, AuditLog.id)
    if user is not None:
        stmt = stmt.where(AuditLog.actor_id == user.id)
    db.expire_all()
    return list(db.scalars(stmt).all())


# --- Sign-in --------------------------------------------------------------------------------


def test_login_returns_access_token_profile_and_secure_cookie(
    api: TestClient, make_user: Callable[..., User], make_site: Callable[..., object], db: Session
) -> None:
    site = make_site("COL-07")
    user = make_user(Role.SITE_ENGINEER, email="kasun@site.lk", sites=[site])

    response = api.post(LOGIN, json={"email": "  Kasun@Site.LK ", "password": PASSWORD})

    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert 800 < body["expires_in"] <= 900
    assert body["user"]["email"] == "kasun@site.lk"
    assert body["user"]["role"] == "site_engineer"
    assert body["user"]["role_label"] == "Site Engineer"
    assert body["user"]["site_scoped"] is True
    assert [s["code"] for s in body["user"]["sites"]] == ["COL-07"]
    assert "reports:create" in body["user"]["permissions"]
    assert "users:manage" not in body["user"]["permissions"]
    assert "password_hash" not in response.text

    cookie = response.headers["set-cookie"]
    assert cookie.startswith(f"{COOKIE}=")
    for attribute in ("HttpOnly", "Secure", "SameSite=strict", "Path=/api/v1/auth"):
        assert attribute.lower() in cookie.lower()
    # The refresh token never appears in the JSON body (it would then be readable by scripts).
    assert response.cookies[COOKIE] not in response.text
    assert audit_actions(db, user) == ["auth.login_succeeded"]


def test_wrong_password_and_unknown_email_get_the_same_answer(
    api: TestClient, make_user: Callable[..., User], db: Session
) -> None:
    make_user(email="real@site.lk")

    wrong_password = api.post(LOGIN, json={"email": "real@site.lk", "password": "Not-The-Password-1"})
    unknown_email = api.post(LOGIN, json={"email": "ghost@site.lk", "password": "Not-The-Password-1"})

    assert wrong_password.status_code == unknown_email.status_code == 401
    assert (
        wrong_password.json()["error"]["code"]
        == unknown_email.json()["error"]["code"]
        == "invalid_credentials"
    )
    assert wrong_password.json()["error"]["message"] == unknown_email.json()["error"]["message"]
    assert "set-cookie" not in wrong_password.headers
    db.expire_all()
    reasons = [log.details["reason"] for log in db.scalars(select(AuditLog)).all()]
    assert sorted(reasons) == ["bad_password", "unknown_email"]


def test_inactive_user_cannot_sign_in(api: TestClient, make_user: Callable[..., User]) -> None:
    make_user(email="gone@site.lk", active=False)

    response = api.post(LOGIN, json={"email": "gone@site.lk", "password": PASSWORD})

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_credentials"


def test_tc09_six_wrong_passwords_lock_the_account_for_15_minutes(
    api: TestClient, make_user: Callable[..., User], db: Session, frozen_clock: Callable[[timedelta], None]
) -> None:
    user = make_user(email="target@site.lk")
    bad = {"email": "target@site.lk", "password": "Wrong-Password-000"}

    statuses = [api.post(LOGIN, json=bad).status_code for _ in range(6)]

    assert statuses == [401, 401, 401, 401, 423, 423]
    locked = api.post(LOGIN, json={"email": "target@site.lk", "password": PASSWORD})
    assert locked.status_code == 423  # even the right password is refused while locked
    assert locked.json()["error"]["code"] == "account_locked"
    assert "15 minutes" in locked.json()["error"]["message"]
    assert "auth.account_locked" in audit_actions(db, user)

    frozen_clock(timedelta(minutes=15, seconds=1))
    assert api.post(LOGIN, json={"email": "target@site.lk", "password": PASSWORD}).status_code == 200
    db.refresh(user)
    assert user.failed_login_count == 0
    assert user.locked_until is None


def test_successful_login_resets_the_failure_counter(api: TestClient, make_user: Callable[..., User]) -> None:
    make_user(email="typo@site.lk")
    for _ in range(4):
        api.post(LOGIN, json={"email": "typo@site.lk", "password": "Wrong-Password-000"})
    login(api, "typo@site.lk")

    for _ in range(4):
        assert (
            api.post(LOGIN, json={"email": "typo@site.lk", "password": "Wrong-Password-000"}).status_code
            == 401
        )


def test_login_is_rate_limited_per_client(api: TestClient) -> None:
    body = {"email": "spray@site.lk", "password": "Wrong-Password-000"}
    statuses = [api.post(LOGIN, json=body).status_code for _ in range(11)]

    assert statuses[:10] == [401] * 10
    assert statuses[10] == 429
    limited = api.post(LOGIN, json=body)
    assert limited.json()["error"]["code"] == "rate_limited"
    assert int(limited.headers["Retry-After"]) > 0


def test_cross_site_login_is_blocked(api: TestClient, make_user: Callable[..., User]) -> None:
    make_user(email="csrf@site.lk")
    body = {"email": "csrf@site.lk", "password": PASSWORD}

    evil_origin = api.post(LOGIN, json=body, headers={"Origin": "https://evil.example"})
    cross_site = api.post(LOGIN, json=body, headers={"Sec-Fetch-Site": "cross-site"})
    allowed = api.post(LOGIN, json=body, headers={"Origin": "http://localhost:5173"})

    assert evil_origin.status_code == cross_site.status_code == 403
    assert allowed.status_code == 200


def test_login_rejects_malformed_input(api: TestClient) -> None:
    assert api.post(LOGIN, json={"email": "not-an-email", "password": "x"}).status_code == 422
    assert api.post(LOGIN, json={"email": "a@b.lk", "password": "x" * 129}).status_code == 422
    assert api.post(LOGIN, json={"email": "a@b.lk", "password": "x", "role": "admin"}).status_code == 422


# --- Access tokens --------------------------------------------------------------------------


def test_me_requires_a_valid_bearer_token(api: TestClient, make_user: Callable[..., User]) -> None:
    user = make_user(email="me@site.lk")
    token = login(api, "me@site.lk")

    assert api.get(ME).status_code == 401
    assert api.get(ME).headers["WWW-Authenticate"] == "Bearer"
    assert api.get(ME, headers={"Authorization": "Basic abc"}).status_code == 401
    assert api.get(ME, headers=bearer("garbage")).json()["error"]["code"] == "invalid_token"
    response = api.get(ME, headers=bearer(token))
    assert response.status_code == 200
    assert response.json()["id"] == str(user.id)


def test_expired_access_token_is_rejected(
    api: TestClient, make_user: Callable[..., User], frozen_clock: Callable[[timedelta], None]
) -> None:
    make_user(email="expiry@site.lk")
    token = login(api, "expiry@site.lk")

    frozen_clock(timedelta(minutes=16))
    response = api.get(ME, headers=bearer(token))

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "token_expired"


def test_deactivation_kills_live_access_tokens(
    api: TestClient, make_user: Callable[..., User], db: Session
) -> None:
    user = make_user(email="leaver@site.lk")
    token = login(api, "leaver@site.lk")
    user.is_active = False
    user.session_version += 1
    db.commit()

    response = api.get(ME, headers=bearer(token))

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "session_expired"


# --- Refresh rotation -------------------------------------------------------------------------


def test_refresh_rotates_the_token(api: TestClient, make_user: Callable[..., User], db: Session) -> None:
    make_user(email="rotate@site.lk")
    login(api, "rotate@site.lk")
    first_cookie = api.cookies[COOKIE]

    response = api.post(REFRESH)

    assert response.status_code == 200
    assert api.get(ME, headers=bearer(response.json()["access_token"])).status_code == 200
    assert api.cookies[COOKIE] != first_cookie
    db.expire_all()
    tokens = db.scalars(select(RefreshToken)).all()
    assert len(tokens) == 2
    assert len({t.family_id for t in tokens}) == 1
    assert sum(t.revoked_at is None for t in tokens) == 1


def test_refresh_without_cookie_is_rejected(api: TestClient) -> None:
    response = api.post(REFRESH)

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "session_expired"


def test_reused_refresh_token_revokes_the_whole_family(
    api: TestClient, make_user: Callable[..., User], db: Session, frozen_clock: Callable[[timedelta], None]
) -> None:
    user = make_user(email="stolen@site.lk")
    login(api, "stolen@site.lk")
    stolen = api.cookies[COOKIE]
    assert api.post(REFRESH).status_code == 200  # legitimate user rotates
    current = api.cookies[COOKIE]

    frozen_clock(timedelta(seconds=REFRESH_GRACE_SECONDS + 1))
    replay = refresh_with(api, stolen)

    assert replay.status_code == 401
    assert "auth.refresh_reuse_detected" in audit_actions(db, user)
    # The attacker's replay also logged out the legitimate session (the family is burned).
    legit = refresh_with(api, current)
    assert legit.status_code == 401


def test_parallel_refresh_within_grace_is_retryable_not_fatal(
    api: TestClient, make_user: Callable[..., User]
) -> None:
    make_user(email="tabs@site.lk")
    login(api, "tabs@site.lk")
    original = api.cookies[COOKIE]
    assert api.post(REFRESH).status_code == 200
    rotated = api.cookies[COOKIE]

    second_tab = refresh_with(api, original)

    assert second_tab.status_code == 401
    assert second_tab.json()["error"]["code"] == "refresh_superseded"
    assert refresh_with(api, rotated).status_code == 200


def test_refresh_expires_after_its_lifetime(
    api: TestClient, make_user: Callable[..., User], frozen_clock: Callable[[timedelta], None]
) -> None:
    make_user(email="stale@site.lk")
    login(api, "stale@site.lk")

    frozen_clock(timedelta(days=8))

    assert api.post(REFRESH).status_code == 401


def test_sessions_end_after_the_absolute_maximum(
    api: TestClient, make_user: Callable[..., User], frozen_clock: Callable[[timedelta], None]
) -> None:
    make_user(email="forever@site.lk")
    login(api, "forever@site.lk")
    for _ in range(5):  # keep refreshing every 6 days: 30 days total
        frozen_clock(timedelta(days=6))
        response = api.post(REFRESH)
        if response.status_code != 200:
            break
    assert response.status_code == 401


def test_refresh_fails_for_deactivated_user(
    api: TestClient, make_user: Callable[..., User], db: Session
) -> None:
    user = make_user(email="refresh-gone@site.lk")
    login(api, "refresh-gone@site.lk")
    user.is_active = False
    db.commit()

    assert api.post(REFRESH).status_code == 401


# --- Logout -----------------------------------------------------------------------------------


def test_logout_revokes_the_session_and_clears_the_cookie(
    api: TestClient, make_user: Callable[..., User], db: Session
) -> None:
    user = make_user(email="bye@site.lk")
    login(api, "bye@site.lk")
    cookie = api.cookies[COOKIE]

    response = api.post(LOGOUT)

    assert response.status_code == 204
    assert (
        'sitesense_refresh=""' in response.headers["set-cookie"]
        or "Max-Age=0" in response.headers["set-cookie"]
    )
    assert refresh_with(api, cookie).status_code == 401
    assert "auth.logout" in audit_actions(db, user)


def test_logout_without_session_is_harmless(api: TestClient) -> None:
    assert api.post(LOGOUT).status_code == 204
    use_cookie(api, "made-up")
    assert api.post(LOGOUT).status_code == 204


# --- Temporary passwords and password change -----------------------------------------------


def test_temporary_password_must_be_changed_before_anything_else(
    api: TestClient, make_user: Callable[..., User], db: Session
) -> None:
    user = make_user(Role.ADMIN, email="new-admin@site.lk", must_change_password=True)
    token = login(api, "new-admin@site.lk")

    me = api.get(ME, headers=bearer(token))
    assert me.status_code == 200
    assert me.json()["must_change_password"] is True
    blocked = api.get("/api/v1/admin/users", headers=bearer(token))
    assert blocked.status_code == 403
    assert blocked.json()["error"]["code"] == "password_change_required"

    changed = api.post(
        "/api/v1/auth/change-password",
        json={"current_password": PASSWORD, "new_password": "Brand-New-Secret-77"},
        headers=bearer(token),
    )
    assert changed.status_code == 200
    new_token = changed.json()["access_token"]
    assert changed.json()["user"]["must_change_password"] is False
    assert api.get("/api/v1/admin/users", headers=bearer(new_token)).status_code == 200
    # The old token belongs to the previous session version.
    assert api.get(ME, headers=bearer(token)).status_code == 401
    assert "auth.password_changed" in audit_actions(db, user)


def test_password_change_signs_out_other_devices(api: TestClient, make_user: Callable[..., User]) -> None:
    make_user(email="two-devices@site.lk")
    login(api, "two-devices@site.lk")
    other_device_cookie = api.cookies[COOKIE]
    token = login(api, "two-devices@site.lk")

    api.post(
        "/api/v1/auth/change-password",
        json={"current_password": PASSWORD, "new_password": "Brand-New-Secret-77"},
        headers=bearer(token),
    )

    assert refresh_with(api, other_device_cookie).status_code == 401
    assert api.post(LOGIN, json={"email": "two-devices@site.lk", "password": PASSWORD}).status_code == 401
    login(api, "two-devices@site.lk", "Brand-New-Secret-77")


def test_password_change_validates_input(api: TestClient, make_user: Callable[..., User]) -> None:
    make_user(email="policy@site.lk")
    token = login(api, "policy@site.lk")
    url = "/api/v1/auth/change-password"

    wrong_current = api.post(
        url,
        json={"current_password": "Nope-Nope-Nope-1", "new_password": "Brand-New-Secret-77"},
        headers=bearer(token),
    )
    weak = api.post(url, json={"current_password": PASSWORD, "new_password": "short"}, headers=bearer(token))
    same = api.post(url, json={"current_password": PASSWORD, "new_password": PASSWORD}, headers=bearer(token))

    assert wrong_current.status_code == 422
    assert wrong_current.json()["error"]["code"] == "invalid_current_password"
    assert weak.status_code == 422
    assert "at least 12" in weak.json()["error"]["message"]
    assert same.status_code == 422


def test_password_change_is_rate_limited(api: TestClient, make_user: Callable[..., User]) -> None:
    make_user(email="guesser@site.lk")
    token = login(api, "guesser@site.lk")
    body = {"current_password": "Guess-Number-0001", "new_password": "Brand-New-Secret-77"}

    statuses = [
        api.post("/api/v1/auth/change-password", json=body, headers=bearer(token)).status_code
        for _ in range(11)
    ]

    assert statuses[:10] == [422] * 10
    assert statuses[10] == 429
