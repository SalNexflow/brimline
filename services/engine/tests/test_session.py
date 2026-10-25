import base64
import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta

import pytest

from brimline_engine.session import (
    InvalidSessionError,
    SessionClaims,
    issue_token,
    verify_token,
)

SECRET = b"s" * 32
NOW = datetime(2026, 10, 25, 12, 0, tzinfo=UTC)
TTL = timedelta(minutes=480)


def test_a_fresh_token_returns_its_user() -> None:
    token, expires_at = issue_token(42, 1, SECRET, TTL, NOW)
    assert verify_token(token, SECRET, NOW) == SessionClaims(user_id=42, session_version=1)
    assert expires_at == datetime(2026, 10, 25, 20, 0, tzinfo=UTC)  # 12:00 + 8 h


def test_token_is_valid_until_one_second_before_expiry() -> None:
    token, _ = issue_token(42, 1, SECRET, TTL, NOW)
    assert verify_token(token, SECRET, datetime(2026, 10, 25, 19, 59, 59, tzinfo=UTC)).user_id == 42
    with pytest.raises(InvalidSessionError, match="expired"):
        verify_token(token, SECRET, datetime(2026, 10, 25, 20, 0, 0, tzinfo=UTC))


def test_a_different_secret_is_rejected() -> None:
    token, _ = issue_token(42, 1, SECRET, TTL, NOW)
    with pytest.raises(InvalidSessionError, match="bad signature"):
        verify_token(token, b"t" * 32, NOW)


def test_changing_the_user_id_breaks_the_signature() -> None:
    token, _ = issue_token(42, 1, SECRET, TTL, NOW)
    forged_payload, _ = issue_token(1, 1, b"attacker-secret-attacker-secret!", TTL, NOW)
    version, _, signature = token.split(".")
    forged = f"{version}.{forged_payload.split('.')[1]}.{signature}"
    with pytest.raises(InvalidSessionError, match="bad signature"):
        verify_token(forged, SECRET, NOW)


@pytest.mark.parametrize(
    "token", ["", "v2", "v2.a", "v9.a.b", "v2.a.b.c", "v2.not-base64!.x", "v2.é.é"]
)
def test_malformed_tokens_are_rejected(token: str) -> None:
    with pytest.raises(InvalidSessionError):
        verify_token(token, SECRET, NOW)


def test_signature_check_uses_constant_time_compare(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[bytes, bytes]] = []
    real = hmac.compare_digest

    def spy(a: bytes, b: bytes) -> bool:
        calls.append((a, b))
        return real(a, b)

    monkeypatch.setattr(hmac, "compare_digest", spy)
    token, _ = issue_token(42, 1, SECRET, TTL, NOW)
    verify_token(token, SECRET, NOW)
    assert len(calls) == 1


def _signed(claims: object) -> str:
    """A correctly signed token with arbitrary claims, as only the secret holder could make."""
    payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).rstrip(b"=").decode()
    signed = f"v2.{payload}"
    sig = hmac.new(SECRET, signed.encode(), hashlib.sha256).digest()
    return f"{signed}.{base64.urlsafe_b64encode(sig).rstrip(b'=').decode()}"


GOOD_EXP = int(NOW.timestamp()) + 3600


# Found by the M1 adversarial review (DEFECT_LOG #11): these crashed or were accepted.
@pytest.mark.parametrize(
    "claims",
    [
        {"uid": True, "ver": 1, "exp": GOOD_EXP},  # bool passed isinstance(int)
        {"uid": 1, "ver": True, "exp": GOOD_EXP},
        {"uid": 1, "ver": 1, "exp": 10**20},  # overflowed datetime.fromtimestamp: a 500
        {"uid": 1, "ver": 1, "exp": -(10**20)},
        {"uid": 1, "ver": 1, "exp": GOOD_EXP + 8 * 24 * 3600},  # beyond the 7-day maximum
        {"uid": 0, "ver": 1, "exp": GOOD_EXP},
        {"uid": 1, "exp": GOOD_EXP},  # no session version
        [1, 2, 3],
    ],
)
def test_signed_tokens_with_bad_claims_are_rejected_cleanly(claims: object) -> None:
    with pytest.raises(InvalidSessionError):
        verify_token(_signed(claims), SECRET, NOW)


def test_a_signed_token_with_good_claims_is_accepted() -> None:
    # Control for the cases above: the hand-made signing helper itself is correct.
    claims = {"uid": 7, "ver": 3, "exp": GOOD_EXP}
    assert verify_token(_signed(claims), SECRET, NOW) == SessionClaims(user_id=7, session_version=3)
