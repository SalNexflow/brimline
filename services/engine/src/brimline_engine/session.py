"""Signed session tokens for the demo login.

Format: "v1.<payload>.<signature>", where payload is base64url JSON {"uid": int, "exp": unix seconds}
and signature is base64url HMAC-SHA256(secret, "v1.<payload>"). The engine never trusts a user id
it did not sign. This is a demo mechanism, not a replacement for a real identity provider.
"""

import base64
import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta

VERSION = "v1"


class InvalidSessionError(Exception):
    """Any problem with a token. The reason is for logs, never for the client."""


def _b64encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64decode(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _sign(secret: bytes, signed_part: str) -> str:
    return _b64encode(hmac.new(secret, signed_part.encode("ascii"), hashlib.sha256).digest())


def issue_token(user_id: int, secret: bytes, ttl: timedelta, now: datetime) -> tuple[str, datetime]:
    expires_at = (now + ttl).replace(microsecond=0)
    payload = _b64encode(
        json.dumps(
            {"uid": user_id, "exp": int(expires_at.timestamp())}, separators=(",", ":")
        ).encode()
    )
    signed_part = f"{VERSION}.{payload}"
    return f"{signed_part}.{_sign(secret, signed_part)}", expires_at


def verify_token(token: str, secret: bytes, now: datetime) -> int:
    """Return the user id in a valid, unexpired token, or raise InvalidSessionError."""
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
        user_id, expires = claims["uid"], claims["exp"]
    except (ValueError, KeyError, TypeError) as exc:
        raise InvalidSessionError("unreadable payload") from exc
    if not isinstance(user_id, int) or not isinstance(expires, int):
        raise InvalidSessionError("wrong claim types")
    if now >= datetime.fromtimestamp(expires, tz=UTC):
        raise InvalidSessionError("expired")
    return user_id
