import uuid
from datetime import datetime
from typing import Annotated, Any

from pydantic import BaseModel, BeforeValidator, ConfigDict, EmailStr, Field, StringConstraints

from app.core.permissions import Role
from app.schemas.auth import SiteSummary

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=120)]


def _upper(value: object) -> object:
    return value.strip().upper() if isinstance(value, str) else value


# Normalise first, then validate: "col-12" is accepted and stored as "COL-12".
SiteCode = Annotated[str, BeforeValidator(_upper), StringConstraints(pattern=r"^[A-Z0-9][A-Z0-9-]{1,15}$")]
Location = Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=120)]


class Page[T](BaseModel):
    items: list[T]
    total: int
    limit: int
    offset: int


# --- Users --------------------------------------------------------------------------------


class UserCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr = Field(max_length=254)
    full_name: Name
    role: Role
    site_ids: list[uuid.UUID] = Field(default_factory=list, max_length=200)


class UserUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    full_name: Name | None = None
    role: Role | None = None
    is_active: bool | None = None


class SiteAssignment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    site_ids: list[uuid.UUID] = Field(max_length=200)


class UserOut(BaseModel):
    id: uuid.UUID
    email: str
    full_name: str
    role: Role
    role_label: str
    is_active: bool
    is_locked: bool
    must_change_password: bool
    last_login_at: datetime | None
    created_at: datetime
    sites: list[SiteSummary]


class UserCreated(BaseModel):
    user: UserOut
    # Shown once to the admin; never stored in plain text and never logged.
    temporary_password: str


class PasswordReset(BaseModel):
    temporary_password: str


# --- Sites --------------------------------------------------------------------------------


class SiteCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: SiteCode
    name: Name
    location: Location
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)


class SiteUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Name | None = None
    location: Location | None = None
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    is_active: bool | None = None


class SiteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    code: str
    name: str
    location: str
    latitude: float | None
    longitude: float | None
    is_active: bool
    created_at: datetime


# --- Audit --------------------------------------------------------------------------------


class AuditLogOut(BaseModel):
    id: uuid.UUID
    occurred_at: datetime
    action: str
    actor_id: uuid.UUID | None
    actor_name: str | None
    target_type: str | None
    target_id: str | None
    ip_address: str | None
    details: dict[str, Any]
