"""Two-step sign-in (Phase 13): an authenticator app's six-digit code after the password.

- **Who must:** Company Admin, project manager, quantity surveyor and procurement (``MFA_ROLES``).
  Site engineers and clients may turn it on. In demo mode the seeded demo accounts are exempt, so
  anyone can try the app locally.
- **Enrolment:** a new secret is kept encrypted as "pending" until the user proves their app works by
  entering a code; then it becomes the account's secret and ten one-use recovery codes are shown once.
- **Sign-in:** after the password, a code (or one recovery code). Wrong codes count towards the same
  lockout as wrong passwords. A code is never accepted twice.
- **Lost authenticator:** a recovery code, or the Company Admin resets two-step sign-in (audited,
  signs the user out everywhere). An admin cannot reset their own: they use a recovery code.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import segno
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.core import clock, secretbox, totp
from app.core.config import Settings
from app.core.errors import BusinessRuleError, ConflictError, UnauthorizedError
from app.core.permissions import MFA_ROLES, Role
from app.models import MfaRecoveryCode, User
from app.services import audit
from app.services.audit import AuditAction, RequestMeta

RECOVERY_CODES = 10


class InvalidCodeError(UnauthorizedError):
    code = "invalid_mfa_code"
    message = "That code is not right. Check the time on your phone and try the newest code."


@dataclass(frozen=True, slots=True)
class MfaStatus:
    enabled: bool
    required: bool
    enabled_at: datetime | None
    recovery_codes_left: int


@dataclass(frozen=True, slots=True)
class MfaSetup:
    secret: str  # for typing into the app by hand
    otpauth_uri: str
    qr_png: str  # a data: URL


def is_required(user: User, settings: Settings) -> bool:
    if not settings.mfa_enforced:  # never in production (Settings refuses it)
        return False
    if settings.demo_mode and user.is_demo:
        return False
    return Role(user.role) in MFA_ROLES


def setup_required(user: User, settings: Settings) -> bool:
    """Signed in with the password, but must enrol before using the app."""
    return is_required(user, settings) and not user.mfa_enabled


def _owner(user: User) -> str:
    return str(user.id)


def _codes_left(db: Session, user: User) -> int:
    return int(
        db.scalar(
            select(func.count(MfaRecoveryCode.id)).where(
                MfaRecoveryCode.user_id == user.id, MfaRecoveryCode.used_at.is_(None)
            )
        )
        or 0
    )


def status(db: Session, settings: Settings, user: User) -> MfaStatus:
    return MfaStatus(
        enabled=user.mfa_enabled,
        required=is_required(user, settings),
        enabled_at=user.mfa_enabled_at,
        recovery_codes_left=_codes_left(db, user) if user.mfa_enabled else 0,
    )


def start_setup(db: Session, settings: Settings, user: User) -> MfaSetup:
    """A fresh secret for the user's app. Nothing changes until ``enable`` confirms a code from it."""
    if user.mfa_enabled:
        raise ConflictError("Two-step sign-in is already on. Turn it off first to move it to another phone.")
    secret = totp.new_secret()
    user.mfa_pending_secret = secretbox.seal(settings, secret, owner=_owner(user))
    db.commit()
    uri = totp.provisioning_uri(secret, user.email)
    return MfaSetup(
        secret=secret, otpauth_uri=uri, qr_png=segno.make(uri, error="m").png_data_uri(scale=5, border=2)
    )


def _new_recovery_codes(db: Session, settings: Settings, user: User) -> list[str]:
    db.execute(delete(MfaRecoveryCode).where(MfaRecoveryCode.user_id == user.id))
    codes = totp.new_recovery_codes(RECOVERY_CODES)
    key = secretbox.recovery_key(settings)
    now = clock.utcnow()
    db.add_all(
        MfaRecoveryCode(user_id=user.id, code_hash=totp.hash_code(c, key), created_at=now) for c in codes
    )
    return codes


def enable(db: Session, settings: Settings, user: User, code: str, *, meta: RequestMeta) -> list[str]:
    """Confirm the pending secret with a code from the app. Returns the recovery codes (shown once)."""
    if user.mfa_enabled:
        raise ConflictError("Two-step sign-in is already on.")
    if user.mfa_pending_secret is None:
        raise BusinessRuleError("Start the set-up first: scan the QR code with your authenticator app.")
    secret = secretbox.open_sealed(settings, user.mfa_pending_secret, owner=_owner(user))
    step = totp.verify(secret, code, clock.utcnow(), last_step=None)
    if step is None:
        raise InvalidCodeError()
    user.mfa_secret = user.mfa_pending_secret
    user.mfa_pending_secret = None
    user.mfa_enabled = True
    user.mfa_enabled_at = clock.utcnow()
    user.mfa_last_step = step
    codes = _new_recovery_codes(db, settings, user)
    audit.record(
        db, AuditAction.MFA_ENABLED, meta=meta, actor_id=user.id, target_type="user", target_id=user.id
    )
    db.commit()
    return codes


def check(db: Session, settings: Settings, user: User, *, code: str | None, recovery_code: str | None) -> str:
    """The second factor: a fresh app code, or an unused recovery code. Returns which; raises if wrong.

    The caller commits (a used recovery code and the last code step are saved with the sign-in).
    """
    if not user.mfa_enabled or user.mfa_secret is None:
        raise InvalidCodeError()
    if code:
        secret = secretbox.open_sealed(settings, user.mfa_secret, owner=_owner(user))
        step = totp.verify(secret, code, clock.utcnow(), last_step=user.mfa_last_step)
        if step is None:
            raise InvalidCodeError()
        user.mfa_last_step = step
        return "app"
    if recovery_code:
        hashed = totp.hash_code(recovery_code, secretbox.recovery_key(settings))
        row = db.scalar(
            select(MfaRecoveryCode)
            .where(
                MfaRecoveryCode.user_id == user.id,
                MfaRecoveryCode.code_hash == hashed,
                MfaRecoveryCode.used_at.is_(None),
            )
            .with_for_update()
        )
        if row is None:
            raise InvalidCodeError()
        row.used_at = clock.utcnow()
        return "recovery_code"
    raise InvalidCodeError()


def regenerate_codes(
    db: Session, settings: Settings, user: User, code: str, *, meta: RequestMeta
) -> list[str]:
    """New recovery codes (the old ones stop working), confirmed with a current app code."""
    check(db, settings, user, code=code, recovery_code=None)
    codes = _new_recovery_codes(db, settings, user)
    audit.record(
        db, AuditAction.MFA_RECOVERY_CODES_RENEWED, meta=meta, actor_id=user.id, target_type="user",
        target_id=user.id,
    )  # fmt: skip
    db.commit()
    return codes


def _clear(db: Session, user: User) -> None:
    user.mfa_enabled = False
    user.mfa_secret = None
    user.mfa_pending_secret = None
    user.mfa_enabled_at = None
    user.mfa_last_step = None
    db.execute(delete(MfaRecoveryCode).where(MfaRecoveryCode.user_id == user.id))


def disable(db: Session, settings: Settings, user: User, code: str, *, meta: RequestMeta) -> None:
    """Turn it off, for the roles where it is optional, confirmed with a current app code."""
    if is_required(user, settings):
        raise BusinessRuleError("Two-step sign-in is required for your role and cannot be turned off.")
    check(db, settings, user, code=code, recovery_code=None)
    _clear(db, user)
    audit.record(
        db, AuditAction.MFA_DISABLED, meta=meta, actor_id=user.id, target_type="user", target_id=user.id
    )
    db.commit()


def admin_reset(db: Session, admin: User, target: User, *, meta: RequestMeta) -> None:
    """The Company Admin clears someone's two-step sign-in (a lost phone). Audited; signs them out.

    Never their own: an admin who lost their phone signs in with a recovery code instead, so one stolen
    admin password is never enough to take an admin account.
    """
    from app.services.auth_service import revoke_all_sessions  # avoid an import cycle

    if admin.id == target.id:
        raise BusinessRuleError(
            "You cannot reset your own two-step sign-in. Sign in with one of your recovery codes, then set "
            "it up again; or ask another Company Admin."
        )
    if not target.mfa_enabled and target.mfa_pending_secret is None:
        raise ConflictError("Two-step sign-in is not set up for this account.")
    was_enabled = target.mfa_enabled
    _clear(db, target)
    target.session_version += 1
    revoke_all_sessions(db, target.id)
    audit.record(
        db, AuditAction.MFA_RESET, meta=meta, actor_id=admin.id, target_type="user", target_id=target.id,
        details={"was_enabled": was_enabled},
    )  # fmt: skip
    db.commit()
