"""Reference data for forms: materials and customers."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from brimline_engine.api.deps import Conn, CurrentUser
from brimline_engine.permissions import can

router = APIRouter(tags=["reference"])


class MaterialOut(BaseModel):
    code: str
    name: str
    process: str


class CustomerOut(BaseModel):
    code: str
    name: str


@router.get("/materials")
def list_materials(conn: Conn, user: CurrentUser) -> list[MaterialOut]:
    if not can(user.actor, "material.list"):
        raise HTTPException(403, "not allowed")
    rows = conn.execute("SELECT code, name, process FROM materials ORDER BY id").fetchall()
    return [MaterialOut(code=r[0], name=r[1], process=r[2]) for r in rows]


@router.get("/customers")
def list_customers(conn: Conn, user: CurrentUser) -> list[CustomerOut]:
    if not can(user.actor, "customer.list"):
        raise HTTPException(403, "not allowed")
    rows = conn.execute("SELECT code, name FROM customers ORDER BY name").fetchall()
    return [CustomerOut(code=r[0], name=r[1]) for r in rows]
