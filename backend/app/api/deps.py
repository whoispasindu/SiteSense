"""Reusable request dependencies: authentication, permissions and site scoping.

Every protected endpoint declares what it needs, for example::

    @router.get("/admin/users")
    def list_users(user: Annotated[User, Depends(require_permission(Permission.USERS_MANAGE))]): ...

so the access rule sits next to the route and cannot be forgotten in the body.
"""

import uuid
from collections.abc import Callable
from typing import Annotated, Any

import structlog
from fastapi import Depends, Request
from sqlalchemy import Select, SQLColumnExpression
from sqlalchemy.orm import Session

from app.core.config import Settings, app_settings
from app.core.database import get_db
from app.core.errors import ForbiddenError, NotFoundError, UnauthorizedError
from app.core.permissions import SITE_SCOPED_ROLES, Permission, Role, has_permission
from app.core.rate_limit import RateLimiter
from app.core.security import TokenError, decode_access_token
from app.models import User
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


def get_current_user(user: Annotated[User, Depends(get_authenticated_user)]) -> User:
    """The default for protected endpoints: also blocks accounts with a temporary password."""
    if user.must_change_password:
        raise PasswordChangeRequiredError()
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


# --- Site scoping (groundwork for BR-03) --------------------------------------------------


def accessible_site_ids(user: User) -> set[uuid.UUID] | None:
    """Sites this user may see, or ``None`` when the role works across every site."""
    if Role(user.role) not in SITE_SCOPED_ROLES:
        return None
    return {site.id for site in user.sites}


def ensure_site_access(user: User, site_id: uuid.UUID) -> None:
    """Raise 404 (not 403) so that users cannot probe which sites exist."""
    allowed = accessible_site_ids(user)
    if allowed is not None and site_id not in allowed:
        raise NotFoundError("Site not found.")


def scope_to_user_sites[S: Select[Any]](
    stmt: S, site_column: SQLColumnExpression[uuid.UUID], user: User
) -> S:
    """Filter any query by the user's sites. Every list endpoint for site data uses this."""
    allowed = accessible_site_ids(user)
    if allowed is None:
        return stmt
    return stmt.where(site_column.in_(allowed))


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
