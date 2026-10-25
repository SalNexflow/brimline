"""Request dependencies: a database connection, and the signed-in user."""

import re
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated

import psycopg
from fastapi import Depends, Header, HTTPException, Request
from psycopg_pool import ConnectionPool

from brimline_engine.permissions import Actor, Role
from brimline_engine.session import InvalidSessionError, verify_token
from brimline_engine.settings import Settings, get_settings
from brimline_engine.text import IDEMPOTENCY_KEY_PATTERN


def utc_now() -> datetime:
    return datetime.now(UTC)


def get_conn(request: Request) -> Iterator[psycopg.Connection]:
    pool: ConnectionPool = request.app.state.pool
    with pool.connection() as conn:
        yield conn


@dataclass(frozen=True)
class SessionUser:
    actor: Actor
    session_version: int
    code: str
    display_name: str
    customer_code: str | None
    customer_name: str | None


def _unauthorized() -> HTTPException:
    return HTTPException(401, "not signed in", headers={"WWW-Authenticate": "Bearer"})


def current_user(
    conn: Annotated[psycopg.Connection, Depends(get_conn)],
    settings: Annotated[Settings, Depends(get_settings)],
    now: Annotated[datetime, Depends(utc_now)],
    authorization: Annotated[str | None, Header()] = None,
) -> SessionUser:
    if not authorization or not authorization.startswith("Bearer "):
        raise _unauthorized()
    secret = settings.session_secret.get_secret_value().encode()
    try:
        claims = verify_token(authorization.removeprefix("Bearer "), secret, now)
    except InvalidSessionError:
        raise _unauthorized() from None
    row = conn.execute(
        "SELECT u.id, u.role, u.customer_id, u.code, u.display_name, c.code, c.name,"
        "       u.session_version"
        " FROM users u LEFT JOIN customers c ON c.id = u.customer_id WHERE u.id = %s",
        (claims.user_id,),
    ).fetchone()
    if row is None:
        raise _unauthorized()  # a valid token for a user that no longer exists
    uid, role, customer_id, code, display_name, customer_code, customer_name, version = row
    if version != claims.session_version:
        raise _unauthorized()  # the user signed out after this token was issued
    role_value: Role = role
    return SessionUser(
        actor=Actor(user_id=uid, role=role_value, customer_id=customer_id),
        session_version=version,
        code=code,
        display_name=display_name,
        customer_code=customer_code,
        customer_name=customer_name,
    )


def idempotency_key(idempotency_key: Annotated[str | None, Header()] = None) -> str:
    """Every write needs a client key; see brimline_engine.idempotency."""
    if idempotency_key is None or not re.fullmatch(IDEMPOTENCY_KEY_PATTERN, idempotency_key):
        raise HTTPException(
            400, "an Idempotency-Key header of 8 to 200 letters, digits, or . _ : - is required"
        )
    return idempotency_key


Conn = Annotated[psycopg.Connection, Depends(get_conn)]
IdempotencyKey = Annotated[str, Depends(idempotency_key)]
CurrentUser = Annotated[SessionUser, Depends(current_user)]
CurrentSettings = Annotated[Settings, Depends(get_settings)]
Now = Annotated[datetime, Depends(utc_now)]
