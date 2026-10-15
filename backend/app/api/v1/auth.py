from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, Response, status

from app.api.deps import (
    AppSettings,
    AuthenticatedUser,
    DbSession,
    Meta,
    rate_limit,
    require_trusted_origin,
)
from app.core import clock
from app.core.config import Settings
from app.core.permissions import ROLE_LABELS, SITE_SCOPED_ROLES, Role, permissions_for
from app.models import User
from app.schemas.auth import (
    ChangePasswordRequest,
    LoginRequest,
    MeResponse,
    MfaChallengeResponse,
    MfaCodeRequest,
    MfaSetupOut,
    MfaStatusOut,
    MfaVerifyRequest,
    RecoveryCodesOut,
    SiteSummary,
    TokenResponse,
)
from app.services import auth_service, mfa_service
from app.services.auth_service import IssuedSession, MfaChallenge

router = APIRouter(tags=["auth"])

REFRESH_COOKIE = "sitesense_refresh"
# The cookie is only ever sent to the auth endpoints, never to the rest of the API.
REFRESH_COOKIE_PATH = "/api/v1/auth"

RefreshCookie = Annotated[str | None, Cookie(alias=REFRESH_COOKIE)]


def me_response(user: User, settings: Settings) -> MeResponse:
    role = Role(user.role)
    return MeResponse(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        role=role,
        role_label=ROLE_LABELS[role],
        permissions=sorted(p.value for p in permissions_for(role)),
        site_scoped=role in SITE_SCOPED_ROLES,
        sites=[SiteSummary.model_validate(site) for site in user.sites],
        must_change_password=user.must_change_password,
        mfa_enabled=user.mfa_enabled,
        mfa_setup_required=mfa_service.setup_required(user, settings),
        demo_mode=settings.demo_mode,
    )


def _set_refresh_cookie(response: Response, session: IssuedSession, settings: Settings) -> None:
    response.set_cookie(
        REFRESH_COOKIE,
        session.refresh_token,
        max_age=int((session.refresh_expires_at - clock.utcnow()).total_seconds()),
        path=REFRESH_COOKIE_PATH,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="strict",
    )


def _clear_refresh_cookie(response: Response, settings: Settings) -> None:
    response.delete_cookie(
        REFRESH_COOKIE,
        path=REFRESH_COOKIE_PATH,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="strict",
    )


def _token_response(response: Response, session: IssuedSession, settings: Settings) -> TokenResponse:
    _set_refresh_cookie(response, session, settings)
    return TokenResponse(
        access_token=session.access_token,
        expires_in=int((session.access_expires_at - clock.utcnow()).total_seconds()),
        user=me_response(session.user, settings),
    )


@router.post(
    "/auth/login",
    response_model=TokenResponse | MfaChallengeResponse,
    dependencies=[Depends(require_trusted_origin), Depends(rate_limit("login", "login_rate_per_minute"))],
)
def login(
    body: LoginRequest, response: Response, db: DbSession, settings: AppSettings, meta: Meta
) -> TokenResponse | MfaChallengeResponse:
    """A session, or (with two-step sign-in on) a challenge for ``/auth/mfa/verify``: no session yet."""
    result = auth_service.login(db, settings, email=body.email, password=body.password, meta=meta)
    if isinstance(result, MfaChallenge):
        return MfaChallengeResponse(
            mfa_token=result.token, expires_in=int((result.expires_at - clock.utcnow()).total_seconds())
        )
    return _token_response(response, result, settings)


@router.post(
    "/auth/mfa/verify",
    response_model=TokenResponse,
    dependencies=[Depends(require_trusted_origin), Depends(rate_limit("mfa", "mfa_rate_per_minute"))],
)
def verify_second_factor(
    body: MfaVerifyRequest, response: Response, db: DbSession, settings: AppSettings, meta: Meta
) -> TokenResponse:
    """The code step of sign-in: an authenticator code, or one recovery code."""
    session = auth_service.verify_second_factor(
        db, settings, challenge=body.mfa_token, code=body.code, recovery_code=body.recovery_code, meta=meta
    )
    return _token_response(response, session, settings)


# --- Setting up two-step sign-in: allowed before it is set up (``AuthenticatedUser``) ----------------

MfaLimit = [Depends(require_trusted_origin), Depends(rate_limit("mfa", "mfa_rate_per_minute"))]


@router.get("/auth/mfa", response_model=MfaStatusOut)
def mfa_status(user: AuthenticatedUser, db: DbSession, settings: AppSettings) -> MfaStatusOut:
    s = mfa_service.status(db, settings, user)
    return MfaStatusOut(
        enabled=s.enabled,
        required=s.required,
        enabled_at=s.enabled_at,
        recovery_codes_left=s.recovery_codes_left,
    )


@router.post("/auth/mfa/setup", response_model=MfaSetupOut, dependencies=MfaLimit)
def mfa_setup(user: AuthenticatedUser, db: DbSession, settings: AppSettings) -> MfaSetupOut:
    """A new secret and its QR code. Nothing changes until a code from the app is confirmed."""
    setup = mfa_service.start_setup(db, settings, user)
    return MfaSetupOut(secret=setup.secret, otpauth_uri=setup.otpauth_uri, qr_png=setup.qr_png)


@router.post("/auth/mfa/enable", response_model=RecoveryCodesOut, dependencies=MfaLimit)
def mfa_enable(
    body: MfaCodeRequest, user: AuthenticatedUser, db: DbSession, settings: AppSettings, meta: Meta
) -> RecoveryCodesOut:
    """Confirm with a code from the app. Returns ten recovery codes, shown this once."""
    return RecoveryCodesOut(codes=mfa_service.enable(db, settings, user, body.code, meta=meta))


@router.post("/auth/mfa/recovery-codes", response_model=RecoveryCodesOut, dependencies=MfaLimit)
def mfa_recovery_codes(
    body: MfaCodeRequest, user: AuthenticatedUser, db: DbSession, settings: AppSettings, meta: Meta
) -> RecoveryCodesOut:
    """New recovery codes (the old ones stop working), confirmed with a current code."""
    return RecoveryCodesOut(codes=mfa_service.regenerate_codes(db, settings, user, body.code, meta=meta))


@router.post("/auth/mfa/disable", status_code=status.HTTP_204_NO_CONTENT, dependencies=MfaLimit)
def mfa_disable(
    body: MfaCodeRequest, user: AuthenticatedUser, db: DbSession, settings: AppSettings, meta: Meta
) -> None:
    """Turn it off, only where it is optional (site engineers, clients)."""
    mfa_service.disable(db, settings, user, body.code, meta=meta)


@router.post(
    "/auth/refresh",
    response_model=TokenResponse,
    dependencies=[Depends(require_trusted_origin), Depends(rate_limit("refresh", "refresh_rate_per_minute"))],
)
def refresh(
    response: Response, db: DbSession, settings: AppSettings, meta: Meta, refresh_cookie: RefreshCookie = None
) -> TokenResponse:
    session = auth_service.refresh(db, settings, raw_token=refresh_cookie, meta=meta)
    return _token_response(response, session, settings)


@router.post(
    "/auth/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_trusted_origin)],
)
def logout(
    response: Response, db: DbSession, settings: AppSettings, meta: Meta, refresh_cookie: RefreshCookie = None
) -> None:
    auth_service.logout(db, raw_token=refresh_cookie, meta=meta)
    _clear_refresh_cookie(response, settings)


@router.post(
    "/auth/change-password",
    response_model=TokenResponse,
    # Rate-limited too: a stolen access token must not allow guessing the current password.
    dependencies=[Depends(require_trusted_origin), Depends(rate_limit("password", "login_rate_per_minute"))],
)
def change_password(
    body: ChangePasswordRequest,
    response: Response,
    user: AuthenticatedUser,
    db: DbSession,
    settings: AppSettings,
    meta: Meta,
) -> TokenResponse:
    session = auth_service.change_password(
        db, settings, user, current_password=body.current_password, new_password=body.new_password, meta=meta
    )
    return _token_response(response, session, settings)


@router.get("/me", response_model=MeResponse)
def me(user: AuthenticatedUser, settings: AppSettings) -> MeResponse:
    return me_response(user, settings)
