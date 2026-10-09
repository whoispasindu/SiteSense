import base64
import json
import uuid
from datetime import timedelta

import jwt
import pytest

from app.core.config import Settings
from app.core.permissions import Role
from app.core.security import (
    JWT_AUDIENCE,
    JWT_ISSUER,
    PasswordPolicyError,
    TokenError,
    create_access_token,
    decode_access_token,
    generate_refresh_token,
    generate_temporary_password,
    hash_password,
    hash_refresh_token,
    validate_password,
    verify_password,
)
from tests.conftest import make_settings


@pytest.fixture
def cfg() -> Settings:
    return make_settings()


# --- Passwords ------------------------------------------------------------------------------


def test_hash_is_argon2id_and_verifies() -> None:
    hashed = hash_password("Correct-Horse-Battery-9")

    assert hashed.startswith("$argon2id$")
    assert verify_password("Correct-Horse-Battery-9", hashed)
    assert not verify_password("correct-horse-battery-9", hashed)


def test_verify_handles_missing_and_corrupt_hashes() -> None:
    assert not verify_password("anything-at-all", None)
    assert not verify_password("anything-at-all", "not-a-hash")


@pytest.mark.parametrize(
    ("password", "message"),
    [
        ("short-1A", "at least 12"),
        ("x" * 129, "at most 128"),
        ("password1234", "too common"),
        ("aaaaaaaaaaaaaaab", "too simple"),
        ("kasun-perera-2026!", "email name"),
    ],
)
def test_password_policy_rejects_weak_passwords(password: str, message: str) -> None:
    with pytest.raises(PasswordPolicyError, match=message):
        validate_password(password, email="kasun-perera@site.lk")


def test_password_policy_accepts_a_strong_password() -> None:
    validate_password("Monsoon-Slab-Pour-42", email="kasun@site.lk")


def test_temporary_passwords_are_strong_and_unique() -> None:
    passwords = {generate_temporary_password() for _ in range(50)}

    assert len(passwords) == 50
    for password in passwords:
        assert len(password) == 23
        assert not set(password) & set("0Oo1lI")
        validate_password(password)


# --- Access tokens ----------------------------------------------------------------------------


def test_access_token_round_trip(cfg: Settings) -> None:
    user_id = uuid.uuid4()
    token, _ = create_access_token(
        user_id=user_id, role=Role.QUANTITY_SURVEYOR, session_version=3, settings=cfg
    )

    claims = decode_access_token(token, cfg)

    assert claims.user_id == user_id
    assert claims.role is Role.QUANTITY_SURVEYOR
    assert claims.session_version == 3


def test_expired_token_is_rejected(cfg: Settings, frozen_clock) -> None:  # type: ignore[no-untyped-def]
    token, _ = create_access_token(user_id=uuid.uuid4(), role=Role.ADMIN, session_version=1, settings=cfg)
    frozen_clock(timedelta(minutes=cfg.access_token_ttl_minutes, seconds=10))

    with pytest.raises(TokenError) as exc:
        decode_access_token(token, cfg)
    assert exc.value.code == "token_expired"


def test_token_signed_with_another_key_is_rejected(cfg: Settings) -> None:
    other = make_settings(jwt_secret="a-completely-different-secret-0123456789abcdef")
    token, _ = create_access_token(user_id=uuid.uuid4(), role=Role.ADMIN, session_version=1, settings=other)

    with pytest.raises(TokenError, match="invalid_token"):
        decode_access_token(token, cfg)


def _b64(data: dict[str, object]) -> str:
    return base64.urlsafe_b64encode(json.dumps(data).encode()).rstrip(b"=").decode()


def test_unsigned_alg_none_token_is_rejected(cfg: Settings) -> None:
    token, _ = create_access_token(user_id=uuid.uuid4(), role=Role.CLIENT, session_version=1, settings=cfg)
    payload = jwt.decode(token, options={"verify_signature": False})
    payload["role"] = "admin"
    forged = f"{_b64({'alg': 'none', 'typ': 'JWT'})}.{_b64(payload)}."

    with pytest.raises(TokenError, match="invalid_token"):
        decode_access_token(forged, cfg)


def test_tampered_payload_is_rejected(cfg: Settings) -> None:
    token, _ = create_access_token(user_id=uuid.uuid4(), role=Role.CLIENT, session_version=1, settings=cfg)
    header, _, signature = token.split(".")
    payload = jwt.decode(token, options={"verify_signature": False})
    payload["role"] = "admin"

    with pytest.raises(TokenError, match="invalid_token"):
        decode_access_token(f"{header}.{_b64(payload)}.{signature}", cfg)


@pytest.mark.parametrize(
    "override", [{"aud": "someone-else"}, {"iss": "evil"}, {"typ": "refresh"}, {"role": "superuser"}]
)
def test_tokens_with_wrong_claims_are_rejected(cfg: Settings, override: dict[str, str]) -> None:
    token, _ = create_access_token(user_id=uuid.uuid4(), role=Role.ADMIN, session_version=1, settings=cfg)
    payload = {**jwt.decode(token, options={"verify_signature": False}), **override}
    resigned = jwt.encode(payload, cfg.jwt_secret.get_secret_value(), algorithm="HS256")

    with pytest.raises(TokenError, match="invalid_token"):
        decode_access_token(resigned, cfg)


def test_token_constants() -> None:
    assert JWT_ISSUER == "sitesense"
    assert JWT_AUDIENCE == "sitesense-api"


# --- Refresh tokens ---------------------------------------------------------------------------


def test_refresh_tokens_are_random_and_stored_hashed() -> None:
    first, second = generate_refresh_token(), generate_refresh_token()

    assert first != second
    assert len(first) >= 43  # 32 random bytes, base64url
    assert hash_refresh_token(first) != first
    assert len(hash_refresh_token(first)) == 64
    assert hash_refresh_token(first) == hash_refresh_token(first)
