"""Site scoping (BR-03): which sites a user may reach, applied to queries and single records."""

import uuid
from typing import Any

from sqlalchemy import Select, SQLColumnExpression

from app.core.errors import NotFoundError
from app.core.permissions import SITE_SCOPED_ROLES, Role
from app.models import User


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
