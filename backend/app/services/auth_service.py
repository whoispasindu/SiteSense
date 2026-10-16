"""Sign-in, session refresh, sign-out and password changes.

Phase 13: accounts with two-step sign-in get a short-lived challenge after the password instead of a
session, and the session only after a code (``verify_second_factor``). A right password does not reset
the failure count while a code is still due, so wrong codes add up to the same lockout as passwords.

Sessions are a short-lived access token plus a rotating refresh token. Each sign-in starts a
refresh-token *family*; every refresh revokes the presented token and issues its successor.
If an already-rotated token is presented again (outside a short grace window for parallel
tabs), the token was copied: the whole family is revoked and the event is audited.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core import clock
from app.core.config import Settings
from app.core.errors import AppError, BusinessRuleError, UnauthorizedError
from app.core.permissions import Role
from app.core.security import (
    PasswordPolicyError,
    TokenError,
    create_access_token,
    create_mfa_token,
    decode_mfa_token,
    generate_refresh_token,
    hash_password,
    hash_refresh_token,
    password_needs_rehash,
    validate_password,
    verify_password,
)
from app.models import RefreshToken, User
from app.services import audit, mfa_service
from app.services.audit import AuditAction, RequestMeta

# Two tabs refreshing at the same moment both present the same token; the slower one gets a
# retryable answer instead of tripping reuse detection.
REFRESH_GRACE_SECONDS = 30


class InvalidCredentialsError(UnauthorizedError):
    code = "invalid_credentials"
    message = "Email or password is incorrect."


class AccountLockedError(AppError):
    status_code = 423
    code = "account_locked"

    def __init__(self, minutes: int) -> None:
        unit = "minute" if minutes == 1 else "minutes"
        super().__init__(f"Too many failed sign-in attempts. Try again in {minutes} {unit}.")


class SessionExpiredError(UnauthorizedError):
    code = "session_expired"
    message = "Your session has ended. Please sign in again."


class WrongCurrentPasswordError(BusinessRuleError):
    # 422, not 401: a wrong *current* password must not look like an expired session to the client.
    code = "invalid_current_password"
    message = "Your current password is incorrect."


class RefreshSupersededError(UnauthorizedError):
    code = "refresh_superseded"
    message = "This session was refreshed in another tab. Retry once."


@dataclass(frozen=True, slots=True)
class IssuedSession:
    user: User
    access_token: str
    access_expires_at: datetime
    refresh_token: str
    refresh_expires_at: datetime


@dataclass(frozen=True, slots=True)
class MfaChallenge:
    """The password was right; a second factor is due before any session is issued."""

    token: str
    expires_at: datetime


class ChallengeExpiredError(UnauthorizedError):
    code = "mfa_challenge_expired"
    message = "Too slow, or the sign-in changed. Enter your email and password again."


def normalize_email(email: str) -> str:
    return email.strip().lower()


def _issue_session(
    db: Session,
    settings: Settings,
    user: User,
    meta: RequestMeta,
    *,
    family_id: uuid.UUID,
    family_started_at: datetime,
) -> tuple[IssuedSession, RefreshToken]:
    now = clock.utcnow()
    raw_refresh = generate_refresh_token()
    refresh_expires = min(
        now + timedelta(days=settings.refresh_token_ttl_days),
        family_started_at + timedelta(days=settings.session_max_days),
    )
    record = RefreshToken(
        id=uuid.uuid4(),
        user_id=user.id,
        family_id=family_id,
        token_hash=hash_refresh_token(raw_refresh),
        issued_at=now,
        expires_at=refresh_expires,
        family_started_at=family_started_at,
        user_agent=meta.user_agent,
        ip_address=meta.ip_address,
    )
    db.add(record)
    access, access_expires = create_access_token(
        user_id=user.id, role=Role(user.role), session_version=user.session_version, settings=settings
    )
    return IssuedSession(user, access, access_expires, raw_refresh, refresh_expires), record


def _minutes_left(until: datetime, now: datetime) -> int:
    return max(1, int((until - now).total_seconds() + 59) // 60)


def _record_failure(
    db: Session, settings: Settings, user: User, now: datetime, meta: RequestMeta, reason: str
) -> bool:
    """Count a failed attempt (password or code); lock the account at the limit. Returns True if locked."""
    user.failed_login_count += 1
    locked = user.failed_login_count >= settings.login_max_failures
    if locked:
        user.locked_until = now + timedelta(minutes=settings.lockout_minutes)
        user.failed_login_count = 0
    audit.record(
        db, AuditAction.LOGIN_FAILED, meta=meta, actor_id=user.id, target_type="user", target_id=user.id,
        details={"reason": reason},
    )  # fmt: skip
    if locked:
        audit.record(
            db, AuditAction.ACCOUNT_LOCKED, meta=meta, actor_id=user.id, target_type="user",
            target_id=user.id, details={"minutes": settings.lockout_minutes},
        )  # fmt: skip
    return locked


def login(
    db: Session, settings: Settings, *, email: str, password: str, meta: RequestMeta
) -> IssuedSession | MfaChallenge:
    now = clock.utcnow()
    normalized = normalize_email(email)
    # Row lock: concurrent attempts cannot race past the failure counter.
    user = db.scalar(select(User).where(User.email == normalized).with_for_update())

    if user is not None and user.locked_until is not None and user.locked_until > now:
        audit.record(
            db, AuditAction.LOGIN_FAILED, meta=meta, actor_id=user.id, target_type="user",
            target_id=user.id, details={"reason": "locked"},
        )  # fmt: skip
        db.commit()
        raise AccountLockedError(_minutes_left(user.locked_until, now))

    password_ok = verify_password(password, user.password_hash if user else None)

    if user is None or not password_ok or not user.is_active:
        locked_now = False
        if user is None:
            reason, details = "unknown_email", {"email": normalized}
        else:
            reason, details = ("inactive" if password_ok else "bad_password"), {}
            user.failed_login_count += 1
            if user.failed_login_count >= settings.login_max_failures:
                user.locked_until = now + timedelta(minutes=settings.lockout_minutes)
                user.failed_login_count = 0
                locked_now = True
        audit.record(
            db, AuditAction.LOGIN_FAILED, meta=meta, actor_id=user.id if user else None,
            target_type="user" if user else None, target_id=user.id if user else None,
            details={"reason": reason, **details},
        )  # fmt: skip
        if locked_now and user is not None:
            audit.record(
                db, AuditAction.ACCOUNT_LOCKED, meta=meta, actor_id=user.id, target_type="user",
                target_id=user.id, details={"minutes": settings.lockout_minutes},
            )  # fmt: skip
        db.commit()
        if locked_now:
            raise AccountLockedError(settings.lockout_minutes)
        raise InvalidCredentialsError()

    if password_needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)
    if user.mfa_enabled:
        # Not signed in yet: no session, and the failure count stands until the code is right.
        token, expires = create_mfa_token(
            user_id=user.id, role=Role(user.role), session_version=user.session_version, settings=settings
        )
        audit.record(
            db, AuditAction.MFA_CHALLENGED, meta=meta, actor_id=user.id, target_type="user", target_id=user.id
        )
        db.commit()
        return MfaChallenge(token, expires)
    user.failed_login_count = 0
    user.locked_until = None
    user.last_login_at = now

    session, _ = _issue_session(db, settings, user, meta, family_id=uuid.uuid4(), family_started_at=now)
    audit.record(
        db, AuditAction.LOGIN_SUCCEEDED, meta=meta, actor_id=user.id, target_type="user", target_id=user.id
    )
    db.commit()
    return session


def verify_second_factor(
    db: Session,
    settings: Settings,
    *,
    challenge: str,
    code: str | None,
    recovery_code: str | None,
    meta: RequestMeta,
) -> IssuedSession:
    """The code step of sign-in: a valid challenge plus an app code or a recovery code."""
    try:
        claims = decode_mfa_token(challenge, settings)
    except TokenError as exc:
        raise ChallengeExpiredError() from exc
    now = clock.utcnow()
    user = db.scalar(select(User).where(User.id == claims.user_id).with_for_update())
    if user is None or not user.is_active or user.session_version != claims.session_version:
        raise ChallengeExpiredError()
    if user.locked_until is not None and user.locked_until > now:
        raise AccountLockedError(_minutes_left(user.locked_until, now))
    try:
        method = mfa_service.check(db, settings, user, code=code, recovery_code=recovery_code)
    except mfa_service.InvalidCodeError:
        locked = _record_failure(db, settings, user, now, meta, "bad_mfa_code")
        db.commit()
        if locked:
            raise AccountLockedError(settings.lockout_minutes) from None
        raise
    user.failed_login_count = 0
    user.locked_until = None
    user.last_login_at = now
    session, _ = _issue_session(db, settings, user, meta, family_id=uuid.uuid4(), family_started_at=now)
    audit.record(
        db, AuditAction.LOGIN_SUCCEEDED, meta=meta, actor_id=user.id, target_type="user", target_id=user.id,
        details={"second_factor": method},
    )  # fmt: skip
    db.commit()
    return session


def _revoke_family(db: Session, family_id: uuid.UUID, now: datetime) -> None:
    db.execute(
        update(RefreshToken)
        .where(RefreshToken.family_id == family_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=now)
    )


def revoke_all_sessions(db: Session, user_id: uuid.UUID) -> None:
    db.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=clock.utcnow())
    )


def refresh(db: Session, settings: Settings, *, raw_token: str | None, meta: RequestMeta) -> IssuedSession:
    if not raw_token:
        raise SessionExpiredError()
    now = clock.utcnow()
    token = db.scalar(
        select(RefreshToken).where(RefreshToken.token_hash == hash_refresh_token(raw_token)).with_for_update()
    )
    if token is None:
        raise SessionExpiredError()

    if token.revoked_at is not None:
        if token.replaced_by_id is not None:
            if now - token.revoked_at <= timedelta(seconds=REFRESH_GRACE_SECONDS):
                raise RefreshSupersededError()
            _revoke_family(db, token.family_id, now)
            audit.record(
                db, AuditAction.REFRESH_REUSE_DETECTED, meta=meta, actor_id=token.user_id,
                target_type="user", target_id=token.user_id, details={"family_id": str(token.family_id)},
            )  # fmt: skip
            db.commit()
        raise SessionExpiredError()

    user = db.get(User, token.user_id)
    expired = (
        token.expires_at <= now or token.family_started_at + timedelta(days=settings.session_max_days) <= now
    )
    if expired or user is None or not user.is_active:
        _revoke_family(db, token.family_id, now)
        db.commit()
        raise SessionExpiredError()

    session, successor = _issue_session(
        db, settings, user, meta, family_id=token.family_id, family_started_at=token.family_started_at
    )
    token.revoked_at = now
    token.replaced_by_id = successor.id
    db.commit()
    return session


def logout(db: Session, *, raw_token: str | None, meta: RequestMeta) -> None:
    if not raw_token:
        return
    token = db.scalar(select(RefreshToken).where(RefreshToken.token_hash == hash_refresh_token(raw_token)))
    if token is None:
        return
    _revoke_family(db, token.family_id, clock.utcnow())
    audit.record(
        db, AuditAction.LOGOUT, meta=meta, actor_id=token.user_id, target_type="user", target_id=token.user_id
    )
    db.commit()


def change_password(
    db: Session,
    settings: Settings,
    user: User,
    *,
    current_password: str,
    new_password: str,
    meta: RequestMeta,
) -> IssuedSession:
    if not verify_password(current_password, user.password_hash):
        raise WrongCurrentPasswordError()
    if new_password == current_password:
        raise BusinessRuleError("Choose a password you have not just used.")
    try:
        validate_password(new_password, email=user.email)
    except PasswordPolicyError as exc:
        raise BusinessRuleError(str(exc), details=[{"field": "new_password"}]) from exc

    now = clock.utcnow()
    user.password_hash = hash_password(new_password)
    user.must_change_password = False
    user.password_changed_at = now
    user.session_version += 1  # every other device is signed out
    revoke_all_sessions(db, user.id)
    session, _ = _issue_session(db, settings, user, meta, family_id=uuid.uuid4(), family_started_at=now)
    audit.record(
        db, AuditAction.PASSWORD_CHANGED, meta=meta, actor_id=user.id, target_type="user", target_id=user.id
    )
    db.commit()
    return session
