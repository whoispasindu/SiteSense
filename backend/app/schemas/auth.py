import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, StringConstraints

from app.core.permissions import Role

# Login does not apply the password policy (old passwords must still work), only a size cap.
LoginPassword = Annotated[str, Field(min_length=1, max_length=128)]
NewPassword = Annotated[str, Field(min_length=1, max_length=128)]


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr = Field(max_length=254)
    password: LoginPassword


class ChangePasswordRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    current_password: LoginPassword
    new_password: NewPassword


class SiteSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    code: str
    name: str


class CompanyLocaleOut(BaseModel):
    """How the web app writes dates, times and amounts (server settings, the same for everyone)."""

    time_zone: str
    country: str
    currency: str
    currency_decimals: int
    number_locale: str


class MeResponse(BaseModel):
    id: uuid.UUID
    email: str
    full_name: str
    role: Role
    role_label: str
    permissions: list[str]
    site_scoped: bool
    sites: list[SiteSummary]
    must_change_password: bool
    # Phase 13: two-step sign-in
    mfa_enabled: bool = False
    mfa_setup_required: bool = False  # signed in with the password; must set up two-step sign-in first
    demo_mode: bool = False  # the server runs the demo: show the "Demo data" banner
    company: CompanyLocaleOut


class TokenResponse(BaseModel):
    mfa_required: Literal[False] = False
    access_token: str
    token_type: str = "bearer"  # noqa: S105 - OAuth token type, not a secret
    expires_in: int
    user: MeResponse


# --- Two-step sign-in (Phase 13) ----------------------------------------------------------------------

OtpCode = Annotated[str, StringConstraints(strip_whitespace=True, pattern=r"^\d{6}$")]
RecoveryCode = Annotated[str, StringConstraints(strip_whitespace=True, min_length=10, max_length=20)]


class MfaChallengeResponse(BaseModel):
    """The password was right; send a code to ``/auth/mfa/verify`` with this token."""

    mfa_required: Literal[True] = True
    mfa_token: str
    expires_in: int


class MfaVerifyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mfa_token: Annotated[str, Field(min_length=20, max_length=2000)]
    code: OtpCode | None = None
    recovery_code: RecoveryCode | None = None


class MfaCodeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: OtpCode


class MfaStatusOut(BaseModel):
    enabled: bool
    required: bool
    enabled_at: datetime | None
    recovery_codes_left: int


class MfaSetupOut(BaseModel):
    secret: str
    otpauth_uri: str
    qr_png: str


class RecoveryCodesOut(BaseModel):
    codes: list[str]  # shown once; only keyed hashes are stored


NonBlank = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
