import hmac
from datetime import UTC, datetime, timedelta

import pytest

from brimline_engine.session import InvalidSessionError, issue_token, verify_token

SECRET = b"s" * 32
NOW = datetime(2026, 10, 25, 12, 0, tzinfo=UTC)
TTL = timedelta(minutes=480)


def test_a_fresh_token_returns_its_user() -> None:
    token, expires_at = issue_token(42, SECRET, TTL, NOW)
    assert verify_token(token, SECRET, NOW) == 42
    assert expires_at == datetime(2026, 10, 25, 20, 0, tzinfo=UTC)  # 12:00 + 8 h


def test_token_is_valid_until_one_second_before_expiry() -> None:
    token, _ = issue_token(42, SECRET, TTL, NOW)
    assert verify_token(token, SECRET, datetime(2026, 10, 25, 19, 59, 59, tzinfo=UTC)) == 42
    with pytest.raises(InvalidSessionError, match="expired"):
        verify_token(token, SECRET, datetime(2026, 10, 25, 20, 0, 0, tzinfo=UTC))


def test_a_different_secret_is_rejected() -> None:
    token, _ = issue_token(42, SECRET, TTL, NOW)
    with pytest.raises(InvalidSessionError, match="bad signature"):
        verify_token(token, b"t" * 32, NOW)


def test_changing_the_user_id_breaks_the_signature() -> None:
    token, _ = issue_token(42, SECRET, TTL, NOW)
    forged_payload, _ = issue_token(1, b"attacker-secret-attacker-secret!", TTL, NOW)
    version, _, signature = token.split(".")
    forged = f"{version}.{forged_payload.split('.')[1]}.{signature}"
    with pytest.raises(InvalidSessionError, match="bad signature"):
        verify_token(forged, SECRET, NOW)


@pytest.mark.parametrize(
    "token", ["", "v1", "v1.a", "v2.a.b", "v1.a.b.c", "v1.not-base64!.x", "v1.é.é"]
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
    token, _ = issue_token(42, SECRET, TTL, NOW)
    verify_token(token, SECRET, NOW)
    assert len(calls) == 1
