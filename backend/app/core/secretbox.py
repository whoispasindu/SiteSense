"""Encrypting small secrets at rest (Phase 13): the TOTP shared secrets.

AES-256-GCM with a key derived from ``SITESENSE_MFA_KEY`` (kept out of the database). Each value is
bound to its owner's ID as associated data, so a ciphertext copied onto another user's row does not
decrypt. A database dump alone gives an attacker no authenticator secrets.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.config import Settings

PREFIX = "v1:"
NONCE_BYTES = 12


class SecretBoxError(ValueError):
    """The value could not be decrypted (wrong key, tampered, or not ours)."""


def _key(settings: Settings, purpose: str) -> bytes:
    # One configured secret, separate keys per purpose.
    master = settings.mfa_key.get_secret_value().encode()
    return hmac.new(master, purpose.encode(), hashlib.sha256).digest()


def encryption_key(settings: Settings) -> bytes:
    return _key(settings, "sitesense/totp-secret/v1")


def recovery_key(settings: Settings) -> bytes:
    return _key(settings, "sitesense/recovery-code/v1")


def seal(settings: Settings, plaintext: str, *, owner: str) -> str:
    nonce = os.urandom(NONCE_BYTES)
    sealed = AESGCM(encryption_key(settings)).encrypt(nonce, plaintext.encode(), owner.encode())
    return PREFIX + base64.urlsafe_b64encode(nonce + sealed).decode()


def open_sealed(settings: Settings, value: str, *, owner: str) -> str:
    if not value.startswith(PREFIX):
        raise SecretBoxError("unknown format")
    try:
        raw = base64.urlsafe_b64decode(value[len(PREFIX) :].encode())
        plain = AESGCM(encryption_key(settings)).decrypt(raw[:NONCE_BYTES], raw[NONCE_BYTES:], owner.encode())
    except (InvalidTag, ValueError) as exc:
        raise SecretBoxError("cannot decrypt") from exc
    return plain.decode()
