"""Which projects a client may see (Phase 12): the ones the Company Admin linked them to. Nothing else.

Staff reach projects through their sites (BR-03). Clients do not: two clients can have projects on one
site, and neither may learn that the other's exists. Every path that gives a client data goes through
here: the portal, the variation decision, notifications (and the emails built from them), photos.

A project a client is not linked to answers exactly like one that does not exist.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import NotFoundError
from app.core.permissions import Role
from app.models import Project, ProjectStatus, User, project_clients

HIDDEN_STATUSES = (ProjectStatus.CANCELLED.value,)


def project_ids(user: User) -> set[uuid.UUID]:
    """The client's linked projects; empty for every other role."""
    if user.role != Role.CLIENT.value:
        return set()
    return {project.id for project in user.client_projects if project.status not in HIDDEN_STATUSES}


def can_see(user: User, project_id: uuid.UUID) -> bool:
    return project_id in project_ids(user)


def project_for(
    db: Session, user: User, project_id: uuid.UUID, message: str = "Project not found."
) -> Project:
    """The project, if this client is linked to it; otherwise the same 404 as for a missing one."""
    project = db.get(Project, project_id) if can_see(user, project_id) else None
    if project is None:
        raise NotFoundError(message)
    return project


def clients_of(db: Session, project_id: uuid.UUID) -> list[User]:
    """Active client accounts linked to the project: the only clients told about it."""
    return list(
        db.scalars(
            select(User)
            .join(project_clients, project_clients.c.user_id == User.id)
            .where(
                project_clients.c.project_id == project_id,
                User.is_active.is_(True),
                User.role == Role.CLIENT.value,
            )
            .order_by(User.email)
        )
    )
