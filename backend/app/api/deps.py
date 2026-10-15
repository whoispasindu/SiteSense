"""Reusable request dependencies: authentication, permissions, CSRF and rate limits.

Site scoping helpers live in ``app.core.scoping`` (shared with the service layer).

Every protected endpoint declares what it needs, for example::

    @router.get("/admin/users")
    def list_users(user: Annotated[User, Depends(require_permission(Permission.USERS_MANAGE))]): ...

so the access rule sits next to the route and cannot be forgotten in the body.
"""

from collections.abc import Callable
from typing import Annotated

import structlog
from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.core.config import Settings, app_settings
from app.core.database import get_db
from app.core.errors import ForbiddenError, UnauthorizedError
from app.core.permissions import Permission, Role, has_permission
from app.core.rate_limit import RateLimiter
from app.core.security import TokenError, decode_access_token
from app.models import User
from app.services import mfa_service
from app.services.audit import RequestMeta

DbSession = Annotated[Session, Depends(get_db)]
AppSettings = Annotated[Settings, Depends(app_settings)]


def request_meta(request: Request) -> RequestMeta:
    return RequestMeta.build(
        request.client.host if request.client else None, request.headers.get("user-agent")
    )


Meta = Annotated[RequestMeta, Depends(request_meta)]


class PasswordChangeRequiredError(ForbiddenError):
    code = "password_change_required"
    message = "You must change your temporary password before continuing."


def _bearer_token(request: Request) -> str:
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise UnauthorizedError()
    return token.strip()


def get_authenticated_user(request: Request, db: DbSession, settings: AppSettings) -> User:
    """Valid token and active account. Allows users who still have to change their password."""
    try:
        claims = decode_access_token(_bearer_token(request), settings)
    except TokenError as exc:
        error = UnauthorizedError("Your session has expired." if exc.code == "token_expired" else None)
        error.code = exc.code
        raise error from exc

    user = db.get(User, claims.user_id)
    # session_version mismatch: password changed, account deactivated or role changed after
    # this token was issued. The token is dead even though it has not expired.
    if user is None or not user.is_active or user.session_version != claims.session_version:
        error = UnauthorizedError("Your session has ended. Please sign in again.")
        error.code = "session_expired"
        raise error
    structlog.contextvars.bind_contextvars(user_id=str(user.id))
    return user


class MfaSetupRequiredError(ForbiddenError):
    code = "mfa_setup_required"
    message = "Set up two-step sign-in before continuing."


def get_current_user(user: Annotated[User, Depends(get_authenticated_user)], settings: AppSettings) -> User:
    """The default for protected endpoints: also blocks accounts with a temporary password, and accounts
    whose role needs two-step sign-in until they set it up (Phase 13)."""
    if user.must_change_password:
        raise PasswordChangeRequiredError()
    if mfa_service.setup_required(user, settings):
        raise MfaSetupRequiredError()
    return user


AuthenticatedUser = Annotated[User, Depends(get_authenticated_user)]
CurrentUser = Annotated[User, Depends(get_current_user)]


def require_permission(*permissions: Permission) -> Callable[..., User]:
    """Dependency factory: the user must hold *all* listed permissions."""

    def dependency(user: CurrentUser) -> User:
        role = Role(user.role)
        if not all(has_permission(role, permission) for permission in permissions):
            raise ForbiddenError()
        return user

    return dependency


def require_role(*roles: Role) -> Callable[..., User]:
    """For the rare rule that is genuinely about a role rather than a capability."""

    def dependency(user: CurrentUser) -> User:
        if Role(user.role) not in roles:
            raise ForbiddenError()
        return user

    return dependency


# --- CSRF defence for cookie-authenticated endpoints --------------------------------------


def require_trusted_origin(request: Request, settings: AppSettings) -> None:
    """The refresh cookie is SameSite=Strict; this is a second, independent check.

    Browsers always send Origin on POST from scripts and Sec-Fetch-Site on modern versions.
    """
    origin = request.headers.get("origin")
    if origin is not None and origin not in settings.cors_origins:
        raise ForbiddenError("Cross-site request blocked.")
    if request.headers.get("sec-fetch-site") == "cross-site":
        raise ForbiddenError("Cross-site request blocked.")


# --- Rate limiting --------------------------------------------------------------------------


def rate_limit(bucket: str, setting_name: str) -> Callable[..., None]:
    def dependency(request: Request, settings: AppSettings, meta: Meta) -> None:
        limiter: RateLimiter = request.app.state.rate_limiter
        limiter.hit(f"{bucket}:{meta.ip_address}", limit=getattr(settings, setting_name))

    return dependency
