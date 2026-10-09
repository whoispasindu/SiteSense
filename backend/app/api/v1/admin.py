import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import func, select

from app.api.deps import DbSession, Meta, require_permission
from app.core.permissions import Permission, Role
from app.models import AuditLog, User
from app.schemas.admin import (
    AuditLogOut,
    Page,
    PasswordReset,
    SiteAssignment,
    SiteCreate,
    SiteOut,
    SiteUpdate,
    UserCreate,
    UserCreated,
    UserOut,
    UserUpdate,
)
from app.services import user_service

router = APIRouter(prefix="/admin", tags=["admin"])

UserAdmin = Annotated[User, Depends(require_permission(Permission.USERS_MANAGE))]
SiteAdmin = Annotated[User, Depends(require_permission(Permission.SITES_MANAGE))]
AuditReader = Annotated[User, Depends(require_permission(Permission.AUDIT_READ))]
Limit = Annotated[int, Query(ge=1, le=100)]
Offset = Annotated[int, Query(ge=0, le=100_000)]


# --- Users --------------------------------------------------------------------------------


@router.get("/users", response_model=Page[UserOut])
def list_users(
    _admin: UserAdmin,
    db: DbSession,
    limit: Limit = 50,
    offset: Offset = 0,
    role: Role | None = None,
    active: bool | None = None,
) -> Page[UserOut]:
    users, total = user_service.list_users(db, limit=limit, offset=offset, role=role, active=active)
    return Page(items=[user_service.to_user_out(u) for u in users], total=total, limit=limit, offset=offset)


@router.post("/users", response_model=UserCreated, status_code=status.HTTP_201_CREATED)
def create_user(body: UserCreate, admin: UserAdmin, db: DbSession, meta: Meta) -> UserCreated:
    user, temporary_password = user_service.create_user(db, body, actor=admin, meta=meta)
    return UserCreated(user=user_service.to_user_out(user), temporary_password=temporary_password)


@router.get("/users/{user_id}", response_model=UserOut)
def get_user(user_id: uuid.UUID, _admin: UserAdmin, db: DbSession) -> UserOut:
    return user_service.to_user_out(user_service.get_user(db, user_id))


@router.patch("/users/{user_id}", response_model=UserOut)
def update_user(user_id: uuid.UUID, body: UserUpdate, admin: UserAdmin, db: DbSession, meta: Meta) -> UserOut:
    user = user_service.get_user(db, user_id)
    return user_service.to_user_out(user_service.update_user(db, user, body, actor=admin, meta=meta))


@router.post("/users/{user_id}/sites", response_model=UserOut)
def assign_sites(
    user_id: uuid.UUID, body: SiteAssignment, admin: UserAdmin, db: DbSession, meta: Meta
) -> UserOut:
    user = user_service.get_user(db, user_id)
    return user_service.to_user_out(
        user_service.assign_sites(db, user, body.site_ids, actor=admin, meta=meta)
    )


@router.post("/users/{user_id}/reset-password", response_model=PasswordReset)
def reset_password(user_id: uuid.UUID, admin: UserAdmin, db: DbSession, meta: Meta) -> PasswordReset:
    user = user_service.get_user(db, user_id)
    return PasswordReset(temporary_password=user_service.reset_password(db, user, actor=admin, meta=meta))


# --- Sites --------------------------------------------------------------------------------


@router.get("/sites", response_model=list[SiteOut])
def list_all_sites(_admin: SiteAdmin, db: DbSession) -> list[SiteOut]:
    return [user_service.to_site_out(s) for s in user_service.list_sites(db)]


@router.post("/sites", response_model=SiteOut, status_code=status.HTTP_201_CREATED)
def create_site(body: SiteCreate, admin: SiteAdmin, db: DbSession, meta: Meta) -> SiteOut:
    return user_service.to_site_out(user_service.create_site(db, body, actor=admin, meta=meta))


@router.patch("/sites/{site_id}", response_model=SiteOut)
def update_site(site_id: uuid.UUID, body: SiteUpdate, admin: SiteAdmin, db: DbSession, meta: Meta) -> SiteOut:
    return user_service.to_site_out(user_service.update_site(db, site_id, body, actor=admin, meta=meta))


# --- Audit log ----------------------------------------------------------------------------


@router.get("/audit-logs", response_model=Page[AuditLogOut])
def list_audit_logs(
    _reader: AuditReader,
    db: DbSession,
    limit: Limit = 50,
    offset: Offset = 0,
    action: Annotated[str | None, Query(max_length=64, pattern=r"^[a-z_.]+$")] = None,
) -> Page[AuditLogOut]:
    stmt = select(AuditLog, User.full_name).outerjoin(User, User.id == AuditLog.actor_id)
    if action:
        stmt = stmt.where(AuditLog.action == action)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.execute(
        stmt.order_by(AuditLog.occurred_at.desc(), AuditLog.id).limit(limit).offset(offset)
    ).all()
    items = [
        AuditLogOut(
            id=log.id,
            occurred_at=log.occurred_at,
            action=log.action,
            actor_id=log.actor_id,
            actor_name=actor_name,
            target_type=log.target_type,
            target_id=log.target_id,
            ip_address=log.ip_address,
            details=log.details,
        )
        for log, actor_name in rows
    ]
    return Page(items=items, total=total, limit=limit, offset=offset)
