"""Demo login and "who am I". Demo routes exist only while DEMO_LOGIN is true."""

from datetime import datetime, timedelta

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, Field

from brimline_engine import audit
from brimline_engine.api.deps import (
    Conn,
    CurrentSettings,
    CurrentUser,
    Now,
    SessionUser,
    current_user,
)
from brimline_engine.permissions import Role, capabilities
from brimline_engine.session import issue_token
from brimline_engine.text import SafeText

router = APIRouter(tags=["auth"])


class DemoUser(BaseModel):
    code: str
    display_name: str
    role: Role
    customer_name: str | None


class DemoLoginRequest(BaseModel):
    user_code: SafeText = Field(max_length=50)


class Me(BaseModel):
    code: str
    display_name: str
    role: Role
    customer_code: str | None
    customer_name: str | None
    capabilities: list[str]


class DemoLoginResponse(BaseModel):
    token: str
    expires_at: datetime
    user: Me


def _require_demo_login(settings: CurrentSettings) -> None:
    if not settings.demo_login:
        # 404, not 403: when demo login is off, these routes simply do not exist.
        raise HTTPException(404, "Not Found")


def _me(user: SessionUser) -> Me:
    return Me(
        code=user.code,
        display_name=user.display_name,
        role=user.actor.role,
        customer_code=user.customer_code,
        customer_name=user.customer_name,
        capabilities=capabilities(user.actor),
    )


@router.get("/auth/demo-users")
def demo_users(conn: Conn, settings: CurrentSettings) -> list[DemoUser]:
    _require_demo_login(settings)
    rows = conn.execute(
        "SELECT u.code, u.display_name, u.role, c.name FROM users u"
        " LEFT JOIN customers c ON c.id = u.customer_id ORDER BY u.id"
    ).fetchall()
    return [DemoUser(code=r[0], display_name=r[1], role=r[2], customer_name=r[3]) for r in rows]


@router.post("/auth/demo-login")
def demo_login(
    body: DemoLoginRequest, conn: Conn, settings: CurrentSettings, now: Now
) -> DemoLoginResponse:
    _require_demo_login(settings)
    row = conn.execute(
        "SELECT id, session_version FROM users WHERE code = %s", (body.user_code,)
    ).fetchone()
    if row is None:
        raise HTTPException(400, "unknown demo user")
    token, expires_at = issue_token(
        int(row[0]),
        int(row[1]),
        settings.session_secret.get_secret_value().encode(),
        timedelta(minutes=settings.session_ttl_minutes),
        now,
    )
    # Resolve the profile the same way every later request will.
    user = current_user(conn, settings, now, authorization=f"Bearer {token}")
    return DemoLoginResponse(token=token, expires_at=expires_at, user=_me(user))


@router.post("/auth/logout", status_code=204)
def logout(conn: Conn, user: CurrentUser) -> Response:
    """Sign out everywhere: bumping the session version invalidates every token issued so far.

    Naturally idempotent without a key: after the first call the token is invalid, so a retry
    gets 401 and changes nothing.
    """
    with conn.transaction():
        conn.execute(
            "UPDATE users SET session_version = session_version + 1 WHERE id = %s",
            (user.actor.user_id,),
        )
        audit.record(
            conn,
            actor_user_id=user.actor.user_id,
            action="session.logout",
            entity_type="user",
            entity_id=user.code,
            before={"session_version": user.session_version},
            after={"session_version": user.session_version + 1},
            idempotency_key=None,
        )
    return Response(status_code=204)


@router.get("/me")
def me(user: CurrentUser) -> Me:
    return _me(user)
