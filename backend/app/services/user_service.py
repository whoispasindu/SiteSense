"""User and site administration (Company Admin only)."""

import uuid
from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core import clock
from app.core.errors import BusinessRuleError, ConflictError, NotFoundError
from app.core.permissions import ROLE_LABELS, SITE_SCOPED_ROLES, Role
from app.core.security import generate_temporary_password, hash_password
from app.models import Project, Site, User, project_clients
from app.schemas.admin import (
    AdminProjectOut,
    ProjectRef,
    SiteCreate,
    SiteOut,
    SiteUpdate,
    UserCreate,
    UserOut,
    UserUpdate,
)
from app.schemas.auth import SiteSummary
from app.services import audit
from app.services.audit import AuditAction, RequestMeta
from app.services.auth_service import normalize_email, revoke_all_sessions


def to_user_out(user: User) -> UserOut:
    now = clock.utcnow()
    return UserOut(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        role=Role(user.role),
        role_label=ROLE_LABELS[Role(user.role)],
        is_active=user.is_active,
        is_locked=user.locked_until is not None and user.locked_until > now,
        must_change_password=user.must_change_password,
        last_login_at=user.last_login_at,
        created_at=user.created_at,
        sites=[SiteSummary.model_validate(site) for site in user.sites],
        projects=[ProjectRef(id=p.id, code=p.code, name=p.name) for p in user.client_projects],
        mfa_enabled=user.mfa_enabled,
    )


def get_user(db: Session, user_id: uuid.UUID) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise NotFoundError("User not found.")
    return user


def list_users(
    db: Session, *, limit: int, offset: int, role: Role | None = None, active: bool | None = None
) -> tuple[list[User], int]:
    stmt = select(User)
    if role is not None:
        stmt = stmt.where(User.role == role.value)
    if active is not None:
        stmt = stmt.where(User.is_active == active)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    users = db.scalars(stmt.order_by(User.full_name, User.id).limit(limit).offset(offset)).all()
    return list(users), total


def _load_sites(db: Session, site_ids: Sequence[uuid.UUID]) -> list[Site]:
    unique_ids = list(dict.fromkeys(site_ids))
    if not unique_ids:
        return []
    sites = list(db.scalars(select(Site).where(Site.id.in_(unique_ids))).all())
    found = {site.id for site in sites}
    missing = [str(site_id) for site_id in unique_ids if site_id not in found]
    if missing:
        raise BusinessRuleError("Some sites do not exist.", details=[{"site_ids": missing}])
    inactive = [site.code for site in sites if not site.is_active]
    if inactive:
        raise BusinessRuleError("Inactive sites cannot be assigned.", details=[{"sites": inactive}])
    return sites


def _check_assignable(role: Role, site_ids: Sequence[uuid.UUID]) -> None:
    if site_ids and role not in SITE_SCOPED_ROLES:
        raise BusinessRuleError(f"{ROLE_LABELS[role]}s work across all sites and are not assigned to sites.")


def create_user(db: Session, data: UserCreate, *, actor: User, meta: RequestMeta) -> tuple[User, str]:
    _check_assignable(data.role, data.site_ids)
    sites = _load_sites(db, data.site_ids)
    temporary_password = generate_temporary_password()
    user = User(
        email=normalize_email(data.email),
        full_name=data.full_name,
        role=data.role.value,
        password_hash=hash_password(temporary_password),
        must_change_password=True,
        sites=sites,
    )
    db.add(user)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise ConflictError("A user with this email already exists.") from exc
    audit.record(
        db, AuditAction.USER_CREATED, meta=meta, actor_id=actor.id, target_type="user", target_id=user.id,
        details={"role": data.role.value, "site_codes": [s.code for s in sites]},
    )  # fmt: skip
    db.commit()
    return user, temporary_password


def _active_admin_count(db: Session) -> int:
    return (
        db.scalar(
            select(func.count())
            .select_from(User)
            .where(User.role == Role.ADMIN.value, User.is_active.is_(True))
        )
        or 0
    )


def update_user(db: Session, user: User, data: UserUpdate, *, actor: User, meta: RequestMeta) -> User:
    changes: dict[str, object] = {}
    is_self = user.id == actor.id

    if data.role is not None and data.role.value != user.role:
        if is_self:
            raise BusinessRuleError("You cannot change your own role.")
        if user.role == Role.ADMIN.value and user.is_active and _active_admin_count(db) <= 1:
            raise BusinessRuleError("The company must keep at least one active admin.")
        if data.role not in SITE_SCOPED_ROLES:
            user.sites = []
        if data.role != Role.CLIENT:
            user.client_projects = []  # only clients are linked to projects (Phase 12)
        changes["role"] = {"from": user.role, "to": data.role.value}
        user.role = data.role.value
        user.session_version += 1

    if data.full_name is not None and data.full_name != user.full_name:
        changes["full_name"] = True  # value itself is personal data; the log records the fact
        user.full_name = data.full_name

    action = AuditAction.USER_UPDATED
    if data.is_active is not None and data.is_active != user.is_active:
        if not data.is_active:
            if is_self:
                raise BusinessRuleError("You cannot deactivate your own account.")
            if user.role == Role.ADMIN.value and _active_admin_count(db) <= 1:
                raise BusinessRuleError("The company must keep at least one active admin.")
            user.session_version += 1
            revoke_all_sessions(db, user.id)
            action = AuditAction.USER_DEACTIVATED
        else:
            user.locked_until = None
            user.failed_login_count = 0
            action = AuditAction.USER_REACTIVATED
        user.is_active = data.is_active
        changes["is_active"] = data.is_active

    if changes:
        audit.record(
            db, action, meta=meta, actor_id=actor.id, target_type="user", target_id=user.id, details=changes
        )
        db.commit()
    return user


def assign_sites(
    db: Session, user: User, site_ids: Sequence[uuid.UUID], *, actor: User, meta: RequestMeta
) -> User:
    role = Role(user.role)
    _check_assignable(role, site_ids)
    sites = _load_sites(db, site_ids)
    before = sorted(s.code for s in user.sites)
    user.sites = sites
    audit.record(
        db,
        AuditAction.USER_SITES_ASSIGNED,
        meta=meta,
        actor_id=actor.id,
        target_type="user",
        target_id=user.id,
        details={"from": before, "to": sorted(s.code for s in sites)},
    )
    db.commit()
    return user


def assign_projects(
    db: Session, user: User, project_ids: Sequence[uuid.UUID], *, actor: User, meta: RequestMeta
) -> User:
    """Phase 12: the projects a client may see. Only client accounts; every project must exist."""
    if user.role != Role.CLIENT.value:
        raise BusinessRuleError(
            "Only client accounts are linked to projects; staff reach projects through sites."
        )
    unique_ids = list(dict.fromkeys(project_ids))
    projects = list(db.scalars(select(Project).where(Project.id.in_(unique_ids)).order_by(Project.code)))
    missing = sorted(str(i) for i in set(unique_ids) - {p.id for p in projects})
    if missing:
        raise BusinessRuleError("Some projects do not exist.", details=[{"project_ids": missing}])
    before = sorted(p.code for p in user.client_projects)
    user.client_projects = projects
    audit.record(
        db,
        AuditAction.USER_PROJECTS_ASSIGNED,
        meta=meta,
        actor_id=actor.id,
        target_type="user",
        target_id=user.id,
        details={"from": before, "to": [p.code for p in projects]},
    )
    db.commit()
    return user


def list_projects(db: Session) -> list[AdminProjectOut]:
    """Every project, for linking clients. Codes, names, sites and statuses only: no figures."""
    counts: dict[uuid.UUID, int] = dict(
        db.execute(
            select(project_clients.c.project_id, func.count(project_clients.c.user_id)).group_by(
                project_clients.c.project_id
            )
        ).all()
    )
    return [
        AdminProjectOut(
            id=p.id,
            code=p.code,
            name=p.name,
            site_code=p.site.code,
            status=p.status,
            client_name=p.client_name,
            clients=int(counts.get(p.id, 0)),
        )
        for p in db.scalars(select(Project).order_by(Project.code))
    ]


def reset_password(db: Session, user: User, *, actor: User, meta: RequestMeta) -> str:
    if user.id == actor.id:
        raise BusinessRuleError("Use 'change password' for your own account.")
    temporary_password = generate_temporary_password()
    user.password_hash = hash_password(temporary_password)
    user.must_change_password = True
    user.locked_until = None
    user.failed_login_count = 0
    user.session_version += 1
    revoke_all_sessions(db, user.id)
    audit.record(
        db,
        AuditAction.USER_PASSWORD_RESET,
        meta=meta,
        actor_id=actor.id,
        target_type="user",
        target_id=user.id,
    )
    db.commit()
    return temporary_password


# --- Sites --------------------------------------------------------------------------------


def list_sites(
    db: Session, *, site_ids: set[uuid.UUID] | None = None, include_inactive: bool = True
) -> list[Site]:
    stmt = select(Site)
    if site_ids is not None:
        stmt = stmt.where(Site.id.in_(site_ids))
    if not include_inactive:
        stmt = stmt.where(Site.is_active.is_(True))
    return list(db.scalars(stmt.order_by(Site.code)).all())


def create_site(db: Session, data: SiteCreate, *, actor: User, meta: RequestMeta) -> Site:
    site = Site(**data.model_dump())
    db.add(site)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise ConflictError("A site with this code already exists.") from exc
    audit.record(
        db, AuditAction.SITE_CREATED, meta=meta, actor_id=actor.id, target_type="site", target_id=site.id,
        details={"code": site.code},
    )  # fmt: skip
    db.commit()
    return site


def update_site(db: Session, site_id: uuid.UUID, data: SiteUpdate, *, actor: User, meta: RequestMeta) -> Site:
    site = db.get(Site, site_id)
    if site is None:
        raise NotFoundError("Site not found.")
    changes = data.model_dump(exclude_unset=True)
    moved = any(f in changes and changes[f] != getattr(site, f) for f in ("latitude", "longitude"))
    for field, value in changes.items():
        setattr(site, field, value)
    if moved:
        # The rain history belongs to the old coordinates: fetched again by the next weather refresh.
        site.rain_climate = None
        site.rain_climate_at = None
    if changes:
        audit.record(
            db, AuditAction.SITE_UPDATED, meta=meta, actor_id=actor.id, target_type="site", target_id=site.id,
            details={"fields": sorted(changes)},
        )  # fmt: skip
        db.commit()
    return site


def to_site_out(site: Site) -> SiteOut:
    return SiteOut.model_validate(site)
