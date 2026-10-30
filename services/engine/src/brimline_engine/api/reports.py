"""Reports (M10): quoted versus actual, and the under-quote flag. Code only; no model is called."""

from fastapi import APIRouter, HTTPException

from brimline_engine.api.deps import Conn, CurrentUser
from brimline_engine.costing.report import CostReport
from brimline_engine.costing.store import load_report
from brimline_engine.permissions import can

router = APIRouter(tags=["reports"])


@router.get("/reports/quoted-vs-actual")
def quoted_vs_actual(conn: Conn, user: CurrentUser) -> CostReport:
    """Estimated against actual cost and time per finished job, and which job types look
    systematically under-quoted. It suggests a price rule to review; it never changes one."""
    if not can(user.actor, "report.read"):
        raise HTTPException(403, "not allowed")
    return load_report(conn)
