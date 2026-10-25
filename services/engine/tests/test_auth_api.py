from datetime import timedelta

import psycopg
import pytest
from fastapi.testclient import TestClient

from brimline_engine.session import issue_token
from brimline_engine.settings import Settings, get_settings
from tests.conftest import FIXED_NOW, login


def test_requests_without_a_token_are_refused(client: TestClient) -> None:
    response = client.get("/orders")
    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"


@pytest.mark.parametrize("header", ["Bearer nonsense", "Basic abc", "Bearer v1.a.b", "bearer x"])
def test_bad_tokens_are_refused(client: TestClient, header: str) -> None:
    assert client.get("/me", headers={"Authorization": header}).status_code == 401


def test_an_expired_token_is_refused(client: TestClient) -> None:
    secret = get_settings().session_secret.get_secret_value().encode()
    token, _ = issue_token(1, 1, secret, timedelta(minutes=10), FIXED_NOW - timedelta(minutes=11))
    assert client.get("/me", headers={"Authorization": f"Bearer {token}"}).status_code == 401


def test_a_token_for_a_user_that_does_not_exist_is_refused(client: TestClient) -> None:
    secret = get_settings().session_secret.get_secret_value().encode()
    token, _ = issue_token(999_999, 1, secret, timedelta(minutes=10), FIXED_NOW)
    assert client.get("/me", headers={"Authorization": f"Bearer {token}"}).status_code == 401


@pytest.mark.parametrize(
    ("user_code", "role", "customer_code"),
    [
        ("U-STAFF", "staff", None),
        ("U-PLANNER", "planner", None),
        ("U-OPERATOR", "operator", None),
        ("U-HARBOR", "customer", "C-HARBOR"),
    ],
)
def test_each_role_can_sign_in(
    client: TestClient, user_code: str, role: str, customer_code: str | None
) -> None:
    me = client.get("/me", headers=login(client, user_code)).json()
    assert (me["code"], me["role"], me["customer_code"]) == (user_code, role, customer_code)


def test_login_token_expires_after_the_configured_ttl(client: TestClient) -> None:
    body = client.post("/auth/demo-login", json={"user_code": "U-STAFF"}).json()
    # FIXED_NOW 09:00 UTC + the default 480 minutes.
    assert body["expires_at"] == "2026-10-26T17:00:00Z"


def test_unknown_demo_user_is_rejected(client: TestClient) -> None:
    assert client.post("/auth/demo-login", json={"user_code": "U-NOBODY"}).status_code == 400


def test_demo_login_does_not_exist_when_switched_off(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DEMO_LOGIN", "false")
    get_settings.cache_clear()
    try:
        assert client.get("/auth/demo-users").status_code == 404
        assert client.post("/auth/demo-login", json={"user_code": "U-STAFF"}).status_code == 404
    finally:
        monkeypatch.setenv("DEMO_LOGIN", "true")
        get_settings.cache_clear()


def test_demo_login_is_off_unless_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DEMO_LOGIN", raising=False)
    settings = Settings(  # no .env file, no DEMO_LOGIN variable: the default decides
        _env_file=None,  # type: ignore[call-arg]
        database_url="postgresql://brimline_app@localhost/x",
        session_secret="x" * 32,  # type: ignore[arg-type]
    )
    assert settings.demo_login is False


# --- Sign-out revokes tokens (found by the M1 adversarial review, DEFECT_LOG #10) -----------------


def test_sign_out_revokes_the_token_and_is_audited(client: TestClient, owner_url: str) -> None:
    headers = login(client, "U-PLANNER")
    other_device = login(client, "U-PLANNER")
    assert client.get("/me", headers=headers).status_code == 200

    assert client.post("/auth/logout", headers=headers).status_code == 204
    assert client.get("/me", headers=headers).status_code == 401
    assert client.get("/me", headers=other_device).status_code == 401  # signs out everywhere
    assert client.post("/auth/logout", headers=headers).status_code == 401  # retry changes nothing
    assert client.get("/me", headers=login(client, "U-PLANNER")).status_code == 200

    with psycopg.connect(owner_url) as conn:
        row = conn.execute(
            "SELECT a.before, a.after FROM audit_log a JOIN users u ON u.id = a.actor_user_id"
            " WHERE u.code = 'U-PLANNER' AND a.action = 'session.logout'"
            " ORDER BY a.id DESC LIMIT 1"
        ).fetchone()
    assert row is not None
    before, after = row
    assert after["session_version"] == before["session_version"] + 1


def test_sign_out_requires_a_session(client: TestClient) -> None:
    assert client.post("/auth/logout").status_code == 401
