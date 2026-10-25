"""Signed session tokens for the demo login.

Format: "v2.<payload>.<signature>", where payload is base64url JSON
{"uid": user id, "ver": the user's session version, "exp": unix seconds} and signature is
base64url HMAC-SHA256(secret, "v2.<payload>"). The engine never trusts a user id it did not sign,
and a token stops working when it expires or when the user signs out (which bumps their session
version). This is a demo mechanism, not a replacement for a real identity provider.
"""

import base64
import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import datetime, timedelta

VERSION = "v2"
# No token may claim to live longer than this, whatever its signature says.
MAX_LIFETIME = timedelta(days=7)


class InvalidSessionError(Exception):
    """Any problem with a token. The reason is for logs, never for the client."""


@dataclass(frozen=True)
class SessionClaims:
    user_id: int
    session_version: int


def _b64encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64decode(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _sign(secret: bytes, signed_part: str) -> str:
    return _b64encode(hmac.new(secret, signed_part.encode("ascii"), hashlib.sha256).digest())


def _positive_int(value: object) -> bool:
    # `type(...) is int`, not isinstance: JSON `true` is a bool, and bool is a subclass of int.
    return type(value) is int and value > 0


def issue_token(
    user_id: int, session_version: int, secret: bytes, ttl: timedelta, now: datetime
) -> tuple[str, datetime]:
    expires_at = (now + ttl).replace(microsecond=0)
    claims = {"uid": user_id, "ver": session_version, "exp": int(expires_at.timestamp())}
    payload = _b64encode(json.dumps(claims, separators=(",", ":")).encode())
    signed_part = f"{VERSION}.{payload}"
    return f"{signed_part}.{_sign(secret, signed_part)}", expires_at


def verify_token(token: str, secret: bytes, now: datetime) -> SessionClaims:
    """Return the claims of a valid, unexpired token, or raise InvalidSessionError."""
    # Valid tokens are pure ASCII; anything else must be a clean rejection, not an encode crash.
    if not token.isascii():
        raise InvalidSessionError("non-ASCII token")
    parts = token.split(".")
    if len(parts) != 3 or parts[0] != VERSION:
        raise InvalidSessionError("malformed token")
    version, payload, signature = parts
    expected = _sign(secret, f"{version}.{payload}")
    # Constant-time comparison, so response timing reveals nothing about the right signature.
    if not hmac.compare_digest(expected.encode("ascii"), signature.encode("ascii")):
        raise InvalidSessionError("bad signature")
    try:
        claims = json.loads(_b64decode(payload))
        user_id, session_version, expires = claims["uid"], claims["ver"], claims["exp"]
    except (ValueError, KeyError, TypeError) as exc:
        raise InvalidSessionError("unreadable payload") from exc
    if not (_positive_int(user_id) and _positive_int(session_version) and _positive_int(expires)):
        raise InvalidSessionError("wrong claim types")
    # Compare plain numbers: converting an absurd `exp` to a datetime would overflow (a 500).
    now_ts = now.timestamp()
    if now_ts >= expires:
        raise InvalidSessionError("expired")
    if expires > now_ts + MAX_LIFETIME.total_seconds():
        raise InvalidSessionError("expiry too far in the future")
    return SessionClaims(user_id=user_id, session_version=session_version)
