"""Time-based one-time passwords (RFC 6238, Phase 13): the codes an authenticator app shows.

HMAC-SHA1, 6 digits, a new code every 30 seconds, as every common authenticator app expects. A code
is accepted for the step before and after the current one (clock drift), and never twice: the caller
stores the last step used and passes it back, so a code seen over someone's shoulder cannot be replayed.
Tested against the RFC's own vectors.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
from datetime import datetime
from urllib.parse import quote, urlencode

STEP_SECONDS = 30
DIGITS = 6
WINDOW = 1  # steps either side of now
SECRET_BYTES = 20  # 160 bits, as RFC 4226 recommends
ISSUER = "SiteSense"


def new_secret() -> str:
    """A random shared secret, base32 without padding (what authenticator apps take)."""
    return base64.b32encode(secrets.token_bytes(SECRET_BYTES)).decode().rstrip("=")


def _key(secret: str) -> bytes:
    padded = secret.upper() + "=" * (-len(secret) % 8)
    return base64.b32decode(padded)


def step_at(moment: datetime) -> int:
    return int(moment.timestamp()) // STEP_SECONDS


def code_at(secret: str, step: int, *, digits: int = DIGITS, digest: str = "sha1") -> str:
    """The code for one time step (RFC 4226's HOTP with the step as the counter)."""
    mac = hmac.new(_key(secret), struct.pack(">Q", step), digest).digest()
    offset = mac[-1] & 0x0F
    value = struct.unpack(">I", mac[offset : offset + 4])[0] & 0x7FFFFFFF
    return str(value % 10**digits).zfill(digits)


def verify(secret: str, code: str, moment: datetime, *, last_step: int | None) -> int | None:
    """The step the code matches (within the window and after ``last_step``), or None."""
    code = code.strip().replace(" ", "")
    if len(code) != DIGITS or not code.isdigit():
        return None
    now = step_at(moment)
    for step in range(now - WINDOW, now + WINDOW + 1):
        if last_step is not None and step <= last_step:
            continue
        if hmac.compare_digest(code_at(secret, step), code):
            return step
    return None


def provisioning_uri(secret: str, account: str) -> str:
    """The otpauth:// link an authenticator app reads from the QR code."""
    label = quote(f"{ISSUER}:{account}", safe="@:")
    query = urlencode({"secret": secret, "issuer": ISSUER, "digits": DIGITS, "period": STEP_SECONDS})
    return f"otpauth://totp/{label}?{query}"


def hash_code(code: str, key: bytes) -> str:
    """A recovery code's stored form: keyed (HMAC-SHA256), so a database copy alone cannot test guesses."""
    normalised = code.strip().lower().replace("-", "").replace(" ", "")
    return hmac.new(key, normalised.encode(), hashlib.sha256).hexdigest()


def new_recovery_codes(count: int = 10) -> list[str]:
    """One-use codes, ``xxxxx-xxxxx`` from a 32-letter alphabet (50 bits each)."""
    alphabet = "abcdefghjkmnpqrstuvwxyz23456789"  # no 0/o, 1/l/i: easy to copy by hand
    codes = []
    for _ in range(count):
        raw = "".join(secrets.choice(alphabet) for _ in range(10))
        codes.append(f"{raw[:5]}-{raw[5:]}")
    return codes
