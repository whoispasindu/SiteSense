"""Phase 13: two-step sign-in with an authenticator app (TOTP), recovery codes and the admin reset."""

import base64
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import clock, secretbox, totp
from app.core.config import Settings
from app.core.permissions import Role
from app.models import AuditLog, MfaRecoveryCode, User
from tests.conftest import PASSWORD, bearer, make_settings

RFC_SECRET = base64.b32encode(b"12345678901234567890").decode()


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return make_settings(media_root=str(tmp_path / "media"), mfa_enforced=True)


def sign_in(api: TestClient, email: str, password: str = PASSWORD) -> Any:
    return api.post("/api/v1/auth/login", json={"email": email, "password": password})


def token_of(api: TestClient, email: str) -> str:
    response = sign_in(api, email)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["mfa_required"] is False
    token: str = body["access_token"]
    return token


def enrol(api: TestClient, headers: dict[str, str]) -> tuple[str, list[str]]:
    """Set up two-step sign-in: returns the secret and the recovery codes."""
    setup = api.post("/api/v1/auth/mfa/setup", headers=headers)
    assert setup.status_code == 200, setup.text
    secret: str = setup.json()["secret"]
    code = totp.code_at(secret, totp.step_at(clock.utcnow()))
    enabled = api.post("/api/v1/auth/mfa/enable", json={"code": code}, headers=headers)
    assert enabled.status_code == 200, enabled.text
    codes: list[str] = enabled.json()["codes"]
    return secret, codes


def next_code(secret: str, steps_ahead: int = 1) -> str:
    """A code the server has not seen yet (the enrolment code's step is used up)."""
    return totp.code_at(secret, totp.step_at(clock.utcnow()) + steps_ahead)


def challenge(api: TestClient, email: str) -> str:
    response = sign_in(api, email)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["mfa_required"] is True
    assert "access_token" not in body
    assert "sitesense_refresh" not in response.cookies  # no session before the code
    token: str = body["mfa_token"]
    return token


def verify(api: TestClient, token: str, **body: str) -> Any:
    return api.post("/api/v1/auth/mfa/verify", json={"mfa_token": token, **body})


# --- The algorithm ----------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("unix", "expected"),
    [
        (59, "94287082"),
        (1111111109, "07081804"),
        (1111111111, "14050471"),
        (1234567890, "89005924"),
        (2000000000, "69279037"),
        (20000000000, "65353130"),
    ],
)
def test_totp_matches_the_rfc_6238_vectors(unix: int, expected: str) -> None:
    step = totp.step_at(datetime.fromtimestamp(unix, tz=UTC))
    assert totp.code_at(RFC_SECRET, step, digits=8) == expected


def test_codes_are_accepted_one_step_either_side_and_never_twice() -> None:
    now = datetime(2026, 10, 16, 8, 0, 15, tzinfo=UTC)
    step = totp.step_at(now)
    secret = totp.new_secret()
    assert totp.verify(secret, totp.code_at(secret, step), now, last_step=None) == step
    assert totp.verify(secret, totp.code_at(secret, step - 1), now, last_step=None) == step - 1
    assert totp.verify(secret, totp.code_at(secret, step + 1), now, last_step=None) == step + 1
    assert totp.verify(secret, totp.code_at(secret, step - 2), now, last_step=None) is None
    assert totp.verify(secret, totp.code_at(secret, step), now, last_step=step) is None  # replay
    assert totp.verify(secret, "12345", now, last_step=None) is None
    assert totp.verify(secret, "abcdef", now, last_step=None) is None


def test_the_provisioning_link() -> None:
    uri = totp.provisioning_uri("JBSWY3DPEHPK3PXP", "pm@site.lk")
    assert uri.startswith("otpauth://totp/SiteSense:pm@site.lk?")
    assert "secret=JBSWY3DPEHPK3PXP" in uri
    assert "issuer=SiteSense" in uri


def test_recovery_codes_are_readable_and_unique() -> None:
    codes = totp.new_recovery_codes()
    assert len(set(codes)) == 10
    assert all(len(c) == 11 and c[5] == "-" for c in codes)
    assert not any(ch in "".join(codes) for ch in "01ilo")


def test_secrets_are_sealed_and_bound_to_their_owner() -> None:
    settings = make_settings()
    sealed = secretbox.seal(settings, "JBSWY3DPEHPK3PXP", owner="user-a")
    assert "JBSWY3DPEHPK3PXP" not in sealed
    assert secretbox.open_sealed(settings, sealed, owner="user-a") == "JBSWY3DPEHPK3PXP"
    with pytest.raises(secretbox.SecretBoxError):
        secretbox.open_sealed(settings, sealed, owner="user-b")  # copied onto another account
    other_key = make_settings(mfa_key="another-mfa-key-that-is-long-enough-0123456789")
    with pytest.raises(secretbox.SecretBoxError):
        secretbox.open_sealed(other_key, sealed, owner="user-a")
    with pytest.raises(secretbox.SecretBoxError):
        secretbox.open_sealed(settings, sealed[:-4] + "AAAA", owner="user-a")  # tampered
    with pytest.raises(secretbox.SecretBoxError):
        secretbox.open_sealed(settings, "plain", owner="user-a")


# --- Who must use it --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "role", [Role.ADMIN, Role.PROJECT_MANAGER, Role.QUANTITY_SURVEYOR, Role.PROCUREMENT_OFFICER]
)
def test_required_roles_must_set_it_up_before_anything_else(
    api: TestClient, make_user: Callable[..., User], role: Role
) -> None:
    user = make_user(role)
    headers = bearer(token_of(api, user.email))

    me = api.get("/api/v1/me", headers=headers).json()
    assert (me["mfa_enabled"], me["mfa_setup_required"]) == (False, True)
    blocked = api.get("/api/v1/sites", headers=headers)
    assert blocked.status_code == 403
    assert blocked.json()["error"]["code"] == "mfa_setup_required"
    assert api.get("/api/v1/auth/mfa", headers=headers).json()["required"] is True

    enrol(api, headers)
    assert api.get("/api/v1/sites", headers=headers).status_code == 200
    assert api.get("/api/v1/me", headers=headers).json()["mfa_setup_required"] is False


@pytest.mark.parametrize("role", [Role.SITE_ENGINEER, Role.CLIENT])
def test_engineers_and_clients_may_choose(
    api: TestClient, make_user: Callable[..., User], role: Role
) -> None:
    user = make_user(role)
    headers = bearer(token_of(api, user.email))
    assert api.get("/api/v1/me", headers=headers).json()["mfa_setup_required"] is False
    assert api.get("/api/v1/sites", headers=headers).status_code == 200

    secret, _ = enrol(api, headers)
    response = api.post("/api/v1/auth/mfa/disable", json={"code": next_code(secret)}, headers=headers)
    assert response.status_code == 204
    assert api.get("/api/v1/auth/mfa", headers=headers).json()["enabled"] is False


def test_required_roles_cannot_turn_it_off(api: TestClient, make_user: Callable[..., User]) -> None:
    pm = make_user(Role.PROJECT_MANAGER)
    headers = bearer(token_of(api, pm.email))
    secret, _ = enrol(api, headers)
    response = api.post("/api/v1/auth/mfa/disable", json={"code": next_code(secret)}, headers=headers)
    assert response.status_code == 422
    assert "required for your role" in response.json()["error"]["message"]


def test_demo_accounts_skip_it_in_demo_mode_only(
    api: TestClient, db: Session, make_user: Callable[..., User], settings: Settings
) -> None:
    demo = make_user(Role.PROJECT_MANAGER)
    demo.is_demo = True
    real = make_user(Role.PROJECT_MANAGER)
    db.commit()
    settings.demo_mode = True
    try:
        assert api.get("/api/v1/sites", headers=bearer(token_of(api, demo.email))).status_code == 200
        assert api.get("/api/v1/sites", headers=bearer(token_of(api, real.email))).status_code == 403
        assert api.get("/api/v1/me", headers=bearer(token_of(api, demo.email))).json()["demo_mode"] is True
    finally:
        settings.demo_mode = False
    assert api.get("/api/v1/sites", headers=bearer(token_of(api, demo.email))).status_code == 403


# --- Enrolment --------------------------------------------------------------------------------------------


def test_enrolment_needs_a_working_code_and_stores_only_encrypted_secrets(
    api: TestClient, db: Session, make_user: Callable[..., User]
) -> None:
    pm = make_user(Role.PROJECT_MANAGER)
    headers = bearer(token_of(api, pm.email))
    assert api.post("/api/v1/auth/mfa/enable", json={"code": "123456"}, headers=headers).status_code == 422

    setup = api.post("/api/v1/auth/mfa/setup", headers=headers).json()
    assert setup["qr_png"].startswith("data:image/png;base64,")
    assert setup["otpauth_uri"].startswith("otpauth://totp/SiteSense:")
    wrong = api.post("/api/v1/auth/mfa/enable", json={"code": "000000"}, headers=headers)
    assert wrong.status_code == 401
    assert wrong.json()["error"]["code"] == "invalid_mfa_code"
    assert api.post("/api/v1/auth/mfa/enable", json={"code": "12ab56"}, headers=headers).status_code == 422

    code = totp.code_at(setup["secret"], totp.step_at(clock.utcnow()))
    codes = api.post("/api/v1/auth/mfa/enable", json={"code": code}, headers=headers).json()["codes"]
    assert len(codes) == 10
    db.refresh(pm)
    assert pm.mfa_enabled
    assert pm.mfa_secret is not None
    assert pm.mfa_secret.startswith("v1:")
    assert setup["secret"] not in pm.mfa_secret
    stored = db.scalars(select(MfaRecoveryCode.code_hash).where(MfaRecoveryCode.user_id == pm.id)).all()
    assert len(stored) == 10
    assert not set(codes) & set(stored)  # only keyed hashes
    assert api.post("/api/v1/auth/mfa/setup", headers=headers).status_code == 409  # already on
    assert db.scalar(select(AuditLog.id).where(AuditLog.action == "auth.mfa_enabled")) is not None


# --- Signing in -------------------------------------------------------------------------------------------


def test_sign_in_asks_for_a_code_and_only_then_starts_a_session(
    api: TestClient, db: Session, make_user: Callable[..., User]
) -> None:
    pm = make_user(Role.PROJECT_MANAGER)
    secret, _ = enrol(api, bearer(token_of(api, pm.email)))

    token = challenge(api, pm.email)
    # The challenge is not an access token.
    assert api.get("/api/v1/me", headers=bearer(token)).status_code == 401
    done = verify(api, token, code=next_code(secret))
    assert done.status_code == 200, done.text
    assert "sitesense_refresh" in done.cookies
    access = done.json()["access_token"]
    assert api.get("/api/v1/sites", headers=bearer(access)).status_code == 200
    # An access token is not a challenge either.
    assert verify(api, access, code=next_code(secret, 0)).json()["error"]["code"] == "mfa_challenge_expired"
    entry = db.scalars(select(AuditLog).where(AuditLog.action == "auth.login_succeeded")).all()[-1]
    assert entry.details == {"second_factor": "app"}


def test_a_code_works_once(api: TestClient, make_user: Callable[..., User]) -> None:
    pm = make_user(Role.PROJECT_MANAGER)
    secret, _ = enrol(api, bearer(token_of(api, pm.email)))
    code = next_code(secret)
    assert verify(api, challenge(api, pm.email), code=code).status_code == 200
    again = verify(api, challenge(api, pm.email), code=code)
    assert again.status_code == 401
    assert again.json()["error"]["code"] == "invalid_mfa_code"


def test_a_recovery_code_works_once_and_renewal_replaces_them(
    api: TestClient, db: Session, make_user: Callable[..., User]
) -> None:
    pm = make_user(Role.PROJECT_MANAGER)
    secret, codes = enrol(api, bearer(token_of(api, pm.email)))
    first = verify(api, challenge(api, pm.email), recovery_code=codes[0].upper())  # case does not matter
    assert first.status_code == 200
    assert verify(api, challenge(api, pm.email), recovery_code=codes[0]).status_code == 401
    headers = bearer(first.json()["access_token"])
    assert api.get("/api/v1/auth/mfa", headers=headers).json()["recovery_codes_left"] == 9

    renewed = api.post("/api/v1/auth/mfa/recovery-codes", json={"code": next_code(secret)}, headers=headers)
    assert renewed.status_code == 200
    assert verify(api, challenge(api, pm.email), recovery_code=codes[1]).status_code == 401  # old set gone
    assert verify(api, challenge(api, pm.email), recovery_code=renewed.json()["codes"][0]).status_code == 200


def test_wrong_codes_count_towards_the_lockout_even_across_new_passwords(
    api: TestClient, db: Session, make_user: Callable[..., User], settings: Settings
) -> None:
    pm = make_user(Role.PROJECT_MANAGER)
    secret, _ = enrol(api, bearer(token_of(api, pm.email)))
    token = challenge(api, pm.email)
    for _ in range(settings.login_max_failures - 2):
        assert verify(api, token, code="000000").status_code == 401
    # A right password again does not wipe the count while a code is still due.
    token = challenge(api, pm.email)
    assert verify(api, token, code="000000").status_code == 401
    locked = verify(api, token, code="000000")
    assert locked.status_code == 423
    # Locked: even the right code is refused now.
    assert verify(api, token, code=next_code(secret)).status_code == 423
    assert sign_in(api, pm.email).status_code == 423
    actions = db.scalars(select(AuditLog.action).where(AuditLog.target_id == str(pm.id))).all()
    assert "auth.account_locked" in actions


def test_an_old_challenge_or_a_changed_account_is_refused(
    api: TestClient, db: Session, make_user: Callable[..., User], frozen_clock: Callable[[timedelta], None]
) -> None:
    pm = make_user(Role.PROJECT_MANAGER)
    secret, _ = enrol(api, bearer(token_of(api, pm.email)))
    token = challenge(api, pm.email)
    pm.session_version += 1  # e.g. the password was changed meanwhile
    db.commit()
    assert verify(api, token, code=next_code(secret)).json()["error"]["code"] == "mfa_challenge_expired"
    token = challenge(api, pm.email)
    frozen_clock(timedelta(minutes=6))
    response = verify(api, token, code=totp.code_at(secret, totp.step_at(clock.utcnow())))
    assert response.json()["error"]["code"] == "mfa_challenge_expired"


def test_verify_takes_exactly_one_kind_of_code(api: TestClient) -> None:
    assert api.post("/api/v1/auth/mfa/verify", json={"mfa_token": "x" * 30, "extra": 1}).status_code == 422
    response = api.post("/api/v1/auth/mfa/verify", json={"mfa_token": "x" * 30, "code": "123456"})
    assert response.json()["error"]["code"] == "mfa_challenge_expired"


# --- The Company Admin's reset ----------------------------------------------------------------------------


def test_the_admin_resets_a_lost_phone_and_signs_the_user_out(
    api: TestClient, db: Session, make_user: Callable[..., User]
) -> None:
    admin = make_user(Role.ADMIN)
    admin_headers = bearer(token_of(api, admin.email))
    enrol(api, admin_headers)
    pm = make_user(Role.PROJECT_MANAGER)
    pm_headers = bearer(token_of(api, pm.email))
    enrol(api, pm_headers)

    response = api.post(f"/api/v1/admin/users/{pm.id}/mfa/reset", headers=admin_headers)
    assert response.status_code == 200, response.text
    assert response.json()["mfa_enabled"] is False
    assert api.get("/api/v1/me", headers=pm_headers).status_code == 401  # signed out everywhere
    entry = db.scalars(select(AuditLog).where(AuditLog.action == "user.mfa_reset")).one()
    assert (entry.actor_id, entry.target_id, entry.details) == (admin.id, str(pm.id), {"was_enabled": True})
    # Back to setting it up on the next sign-in.
    assert api.get("/api/v1/me", headers=bearer(token_of(api, pm.email))).json()["mfa_setup_required"] is True
    again = api.post(f"/api/v1/admin/users/{pm.id}/mfa/reset", headers=admin_headers)
    assert again.status_code == 409


def test_an_admin_cannot_reset_their_own(api: TestClient, make_user: Callable[..., User]) -> None:
    admin = make_user(Role.ADMIN)
    headers = bearer(token_of(api, admin.email))
    enrol(api, headers)
    response = api.post(f"/api/v1/admin/users/{admin.id}/mfa/reset", headers=headers)
    assert response.status_code == 422
    assert "recovery codes" in response.json()["error"]["message"]


def test_only_the_admin_resets(api: TestClient, make_user: Callable[..., User]) -> None:
    pm = make_user(Role.PROJECT_MANAGER)
    pm_headers = bearer(token_of(api, pm.email))
    enrol(api, pm_headers)
    engineer = make_user(Role.SITE_ENGINEER)
    assert api.post(f"/api/v1/admin/users/{engineer.id}/mfa/reset", headers=pm_headers).status_code == 403
