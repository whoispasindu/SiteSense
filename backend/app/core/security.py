"""Passwords, access tokens and refresh tokens.

- Passwords: argon2id (argon2-cffi defaults), with transparent re-hashing when parameters change.
- Access tokens: short-lived HS256 JWTs carried in the Authorization header, kept only in memory
  by the web app.
- Refresh tokens: 256-bit random opaque strings in an httpOnly cookie. Only their SHA-256 hash is
  stored, so a database leak does not leak usable sessions.
"""

import hashlib
import re
import secrets
import string
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from app.core import clock
from app.core.config import Settings
from app.core.permissions import Role

_hasher = PasswordHasher()

JWT_ALGORITHM = "HS256"
JWT_ISSUER = "sitesense"
JWT_AUDIENCE = "sitesense-api"
JWT_LEEWAY_SECONDS = 5

PASSWORD_MIN_LENGTH = 12
# argon2 cost is per byte of input only up to a point, but unbounded input is still a DoS lever.
PASSWORD_MAX_LENGTH = 128

# Small deny-list of passwords that meet the length rule but appear in every breach corpus.
_COMMON_PASSWORDS = frozenset(
    {
        "password1234",
        "password12345",
        "password123!",
        "passw0rd1234",
        "123456789012",
        "1234567890ab",
        "qwertyuiop12",
        "qwerty123456",
        "iloveyou1234",
        "welcome12345",
        "letmein12345",
        "administrator",
        "changeme1234",
        "sitesense123",
        "sitesense2026",
        "construction1",
        "abc123456789",
        "111111111111",
        "000000000000",
        "aaaaaaaaaaaa",
    }
)


class PasswordPolicyError(ValueError):
    """Raised with a user-facing explanation when a password is not acceptable."""


def validate_password(password: str, *, email: str | None = None) -> None:
    if len(password) < PASSWORD_MIN_LENGTH:
        raise PasswordPolicyError(f"Use at least {PASSWORD_MIN_LENGTH} characters.")
    if len(password) > PASSWORD_MAX_LENGTH:
        raise PasswordPolicyError(f"Use at most {PASSWORD_MAX_LENGTH} characters.")
    lowered = password.lower()
    if lowered in _COMMON_PASSWORDS or len(set(lowered)) < 4:
        raise PasswordPolicyError("This password is too common or too simple.")
    if email:
        local_part = email.split("@", 1)[0].lower()
        if len(local_part) >= 4 and local_part in lowered:
            raise PasswordPolicyError("The password must not contain your email name.")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


# Verifying against this when the user does not exist keeps response times uniform, so timing
# does not reveal which email addresses have accounts.
_DUMMY_HASH = _hasher.hash(secrets.token_urlsafe(16))


def verify_password(password: str, password_hash: str | None) -> bool:
    try:
        return _hasher.verify(password_hash or _DUMMY_HASH, password) and password_hash is not None
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def password_needs_rehash(password_hash: str) -> bool:
    return _hasher.check_needs_rehash(password_hash)


# No look-alike characters (0/O/o, 1/l/I): temporary passwords are often read out over the phone.
_TEMP_ALPHABET = "".join(c for c in string.ascii_letters + string.digits if c not in "0Oo1lI")
_TEMP_GROUPS = 4
_TEMP_GROUP_LEN = 5


def generate_temporary_password() -> str:
    """Readable one-time password, e.g. ``kQ7rd-2xPmA-9fT3c-Lw8nB``: 20 of 56 symbols, about 116 bits."""
    while True:
        groups = [
            "".join(secrets.choice(_TEMP_ALPHABET) for _ in range(_TEMP_GROUP_LEN))
            for _ in range(_TEMP_GROUPS)
        ]
        candidate = "-".join(groups)
        if re.search(r"\d", candidate) and re.search(r"[a-z]", candidate) and re.search(r"[A-Z]", candidate):
            return candidate


# --- Access tokens ------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AccessClaims:
    user_id: uuid.UUID
    role: Role
    session_version: int
    expires_at: datetime


class TokenError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def create_access_token(
    *, user_id: uuid.UUID, role: Role, session_version: int, settings: Settings
) -> tuple[str, datetime]:
    now = clock.utcnow()
    expires_at = now + timedelta(minutes=settings.access_token_ttl_minutes)
    payload = {
        "sub": str(user_id),
        "role": role.value,
        "sv": session_version,
        "typ": "access",
        "iss": JWT_ISSUER,
        "aud": JWT_AUDIENCE,
        "iat": int(now.timestamp()),
        "nbf": int(now.timestamp()),
        "exp": int(expires_at.timestamp()),
        "jti": uuid.uuid4().hex,
    }
    token = jwt.encode(payload, settings.jwt_secret.get_secret_value(), algorithm=JWT_ALGORITHM)
    return token, expires_at


def decode_access_token(token: str, settings: Settings) -> AccessClaims:
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret.get_secret_value(),
            algorithms=[JWT_ALGORITHM],  # pinned: rejects "none" and algorithm-confusion tokens
            audience=JWT_AUDIENCE,
            issuer=JWT_ISSUER,
            # Time claims are checked below against app.core.clock, the app's single notion of now.
            options={
                "require": ["exp", "iat", "nbf", "sub", "aud", "iss"],
                "verify_exp": False,
                "verify_nbf": False,
                "verify_iat": False,
            },
        )
    except jwt.PyJWTError as exc:
        raise TokenError("invalid_token") from exc

    try:
        now = clock.utcnow().timestamp()
        if int(payload["nbf"]) > now + JWT_LEEWAY_SECONDS:
            raise TokenError("invalid_token")
        if int(payload["exp"]) <= now - JWT_LEEWAY_SECONDS:
            raise TokenError("token_expired")
        if payload.get("typ") != "access":
            raise TokenError("invalid_token")
        return AccessClaims(
            user_id=uuid.UUID(payload["sub"]),
            role=Role(payload["role"]),
            session_version=int(payload["sv"]),
            expires_at=datetime.fromtimestamp(int(payload["exp"]), tz=UTC),
        )
    except (KeyError, ValueError, TypeError) as exc:
        raise TokenError("invalid_token") from exc


# --- Refresh tokens -----------------------------------------------------------------------


def generate_refresh_token() -> str:
    return secrets.token_urlsafe(32)


def hash_refresh_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
