"""Uploaded model files (M7): check, store, and fill the planning fields they can.

A file belongs to a quote line (the customer's or staff's upload) or to a job (attached on the
board when a part size is missing). Code checks it and computes the planning values; this
module writes them, checking permissions itself (hard rule 4), idempotent and audit-logged
(hard rule 6). A value a person entered is never overwritten by a file."""

import hashlib
from datetime import date, datetime
from typing import Any, Literal

import psycopg
from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field

from brimline_engine import audit, idempotency, quotes
from brimline_engine.ai.calls import record_call
from brimline_engine.ai.gateway import ModelClient
from brimline_engine.files import advice
from brimline_engine.files.checks import PlanningValues, Report, check_file, planning_values
from brimline_engine.files.config import FilesConfig, files_config
from brimline_engine.files.mesh import UNITS_MM, ParseError, read_mesh
from brimline_engine.files.preview import render_png
from brimline_engine.permissions import Action, Actor, OrderTarget, can, order_scope
from brimline_engine.shop_config import Process, load_shop_config
from brimline_engine.text import SafeText

UPLOAD_ENDPOINT = "POST /files"
OVERRIDE_ENDPOINT = "POST /files/override"
ADVICE_ENDPOINT = "POST /files/advice"


class NotFoundError(Exception):
    """Missing, or not visible to this actor. The two look the same on purpose."""


class ForbiddenError(Exception):
    pass


class InvalidError(Exception):
    pass


class ConflictError(Exception):
    pass


class OverrideIn(BaseModel):
    check: str = Field(min_length=1, max_length=40)
    reason: SafeText = Field(min_length=3, max_length=500)


class OverrideOut(BaseModel):
    check: str
    reason: str
    by: str
    at: datetime


class AdviceOut(BaseModel):
    advice: list[str]
    model: str | None
    at: datetime


class FileOut(BaseModel):
    file_number: str
    filename: str
    unit: str
    target: Literal["quote", "job"]
    quote_number: str | None
    order_number: str | None
    line: int
    material_code: str | None
    report: Report
    overall: Literal["pass", "warn", "fail"]  # after accepted warnings; a fail stays a fail
    planning: PlanningValues
    applied: list[str]  # what this request did (filled in, or why there is no advice)
    overrides: list[OverrideOut]
    advice: list[AdviceOut]  # AI advice: shown as advice, never read by any check
    uploaded_by: str
    uploaded_at: datetime
    can_override: bool
    can_ask_advice: bool


class Target(BaseModel):
    """Where an upload goes: a quote line, or an order line's job."""

    quote_number: str | None = None
    order_number: str | None = None
    line: int = Field(ge=1, le=50)


class _Resolved(BaseModel):
    kind: Literal["quote", "job"]
    customer_id: int
    quote_id: int | None
    job_id: int | None
    material_code: str | None
    process: Process | None
    part_name: str | None = None


def _material(
    conn: psycopg.Connection, material_id: int | None
) -> tuple[str | None, Process | None]:
    if material_id is None:
        return None, None
    row = conn.execute(
        "SELECT code, process FROM materials WHERE id = %s", (material_id,)
    ).fetchone()
    assert row is not None
    return row[0], row[1]


def _resolve(conn: psycopg.Connection, actor: Actor, target: Target) -> _Resolved:
    scope = order_scope(actor)
    if (target.quote_number is None) == (target.order_number is None):
        raise InvalidError("give either a quote number or an order number")
    if target.quote_number is not None:
        row = conn.execute(
            "SELECT q.id, q.customer_id, l.material_id, l.part_name FROM quotes q"
            " LEFT JOIN quote_lines l ON l.quote_id = q.id AND l.line_no = %(l)s"
            " WHERE q.quote_number = %(n)s AND (%(s)s::bigint IS NULL OR q.customer_id = %(s)s::bigint)",
            {"n": target.quote_number, "l": target.line, "s": scope},
        ).fetchone()
        if row is None or not can(actor, "quote.read", OrderTarget(int(row[1]))):
            raise NotFoundError(target.quote_number)
        code, process = _material(conn, row[2])
        exists = conn.execute(
            "SELECT 1 FROM quote_lines WHERE quote_id = %s AND line_no = %s", (row[0], target.line)
        ).fetchone()
        if exists is None:
            raise InvalidError(f"{target.quote_number} has no line {target.line}")
        return _Resolved(
            kind="quote",
            customer_id=int(row[1]),
            quote_id=int(row[0]),
            job_id=None,
            material_code=code,
            process=process,
            part_name=row[3],
        )
    row = conn.execute(
        "SELECT j.id, o.customer_id, j.material_id, j.part_name FROM jobs j"
        " JOIN orders o ON o.id = j.order_id"
        " WHERE o.order_number = %(n)s AND j.line_no = %(l)s"
        " AND (%(s)s::bigint IS NULL OR o.customer_id = %(s)s::bigint)",
        {"n": target.order_number, "l": target.line, "s": scope},
    ).fetchone()
    if row is None or not can(actor, "order.read", OrderTarget(int(row[1]))):
        raise NotFoundError(f"{target.order_number}-{target.line}")
    code, process = _material(conn, row[2])
    return _Resolved(
        kind="job",
        customer_id=int(row[1]),
        quote_id=None,
        job_id=int(row[0]),
        material_code=code,
        process=process,
        part_name=row[3],
    )


def _require(actor: Actor, action: Action, customer_id: int) -> None:
    if not can(actor, action, OrderTarget(customer_id)):
        raise ForbiddenError(action)


def upload(
    conn: psycopg.Connection,
    actor: Actor,
    target: Target,
    filename: str,
    unit: str,
    data: bytes,
    key: str,
    today: date,
    cfg: FilesConfig,
) -> tuple[idempotency.StoredResponse, bool]:
    if unit not in UNITS_MM:
        raise InvalidError(f"unit must be one of: {', '.join(UNITS_MM)}")
    name = filename.strip().replace("\\", "/").rsplit("/", 1)[-1][:200]
    if not name:
        raise InvalidError("the file needs a name")
    if not data:
        raise InvalidError("the file is empty")
    if len(data) > cfg.limits.max_upload_bytes:
        raise InvalidError(
            f"the file is larger than {cfg.limits.max_upload_bytes // 1_048_576} MiB"
        )
    digest = hashlib.sha256(data).hexdigest()
    req_hash = idempotency.request_hash(
        {"target": target.model_dump(), "filename": name, "unit": unit, "sha256": digest}
    )
    with conn.transaction():
        stored = idempotency.claim(
            conn, user_id=actor.user_id, endpoint=UPLOAD_ENDPOINT, key=key, req_hash=req_hash
        )
        if stored is not None:
            return idempotency.StoredResponse(
                stored.status,
                get_file(conn, actor, stored.body["file_number"]).model_dump(mode="json"),
            ), True
        where = _resolve(conn, actor, target)
        _require(actor, "file.upload", where.customer_id)
        if where.kind == "job":
            _require(actor, "file.attach_job", where.customer_id)
        if where.kind == "quote":
            status = conn.execute(
                "SELECT status FROM quotes WHERE id = %s", (where.quote_id,)
            ).fetchone()
            assert status is not None
            if status[0] != "draft":
                raise InvalidError(
                    f"{target.quote_number} is {status[0]}; files go with draft quotes"
                )

        report = check_file(data, name, where.process, load_shop_config().machines, cfg, unit)
        values = planning_values(report, where.material_code, where.process, cfg)
        row = conn.execute(
            "INSERT INTO files (customer_id, quote_id, quote_line, job_id, filename, unit, material_id,"
            " content, size_bytes, sha256, report, overall, planning, uploaded_by, part_name)"
            " VALUES (%s, %s, %s, %s, %s, %s, (SELECT id FROM materials WHERE code = %s),"
            " %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id, file_number",
            (
                where.customer_id,
                where.quote_id,
                target.line if where.kind == "quote" else None,
                where.job_id,
                name,
                report.measurements.unit if report.measurements else unit,
                where.material_code,
                data,
                len(data),
                digest,
                Jsonb(report.model_dump(mode="json")),
                report.overall,
                Jsonb(values.model_dump(mode="json")),
                actor.user_id,
                where.part_name,
            ),
        ).fetchone()
        assert row is not None
        file_id, number = int(row[0]), str(row[1])
        applied = _apply(conn, where, file_id, number, report, values, today)
        out = get_file(conn, actor, number).model_copy(update={"applied": applied})
        audit.record(
            conn,
            actor_user_id=actor.user_id,
            action="file.upload",
            entity_type="file",
            entity_id=number,
            before=None,
            after={
                "file_number": number,
                "target": target.model_dump(),
                "filename": name,
                "sha256": digest,
                "overall": report.overall,
                "planning": values.model_dump(mode="json"),
                "applied": applied,
            },
            idempotency_key=key,
        )
        idempotency.store(
            conn,
            user_id=actor.user_id,
            endpoint=UPLOAD_ENDPOINT,
            key=key,
            response=idempotency.StoredResponse(201, {"file_number": number}),
        )
        return idempotency.StoredResponse(201, out.model_dump(mode="json")), False


def _apply(
    conn: psycopg.Connection,
    where: _Resolved,
    file_id: int,
    number: str,
    report: Report,
    values: PlanningValues,
    today: date,
) -> list[str]:
    """Write the planning values the file gives into its quote line or job. Only the latest file
    of a line or job writes, and never one that failed its checks (review of M7: an older or a
    failed file could overwrite a newer file's values)."""
    if report.overall == "fail":
        return ["nothing filled in: the file failed its checks"]
    latest = conn.execute(
        "SELECT max(o.id) FROM files f JOIN files o"
        " ON o.quote_id IS NOT DISTINCT FROM f.quote_id"
        " AND o.quote_line IS NOT DISTINCT FROM f.quote_line"
        " AND o.job_id IS NOT DISTINCT FROM f.job_id"
        " WHERE f.id = %s",
        (file_id,),
    ).fetchone()
    if latest is None or latest[0] != file_id:
        return ["nothing filled in: a newer file has been uploaded for this line"]
    fields: dict[str, Any] = {
        "part_mm": values.part_mm,
        "grams_per_part": values.grams_per_part,
        "minutes_per_part": values.minutes_per_part,
    }
    if where.kind == "quote":
        assert where.quote_id is not None
        line = conn.execute("SELECT quote_line FROM files WHERE id = %s", (file_id,)).fetchone()
        assert line is not None
        try:
            return quotes.apply_file_values(conn, where.quote_id, int(line[0]), fields, today)
        except quotes.InvalidQuoteError as e:
            raise InvalidError(str(e)) from e
    assert where.job_id is not None
    job = conn.execute(
        "SELECT status, part_x_mm, part_y_mm, part_z_mm, part_size_file_id, minutes_per_part"
        " FROM jobs WHERE id = %s FOR UPDATE",
        (where.job_id,),
    ).fetchone()
    assert job is not None
    status, size, size_file, minutes = job[0], tuple(job[1:4]), job[4], job[5]
    notes: list[str] = []
    if status not in ("pending", "planned"):
        return [f"the job is {status}: nothing changed"]
    if values.part_mm is not None:
        shown = " x ".join(map(str, values.part_mm)) + " mm"
        if None in size or size_file is not None:
            conn.execute(
                "UPDATE jobs SET part_x_mm = %s, part_y_mm = %s, part_z_mm = %s,"
                " part_size_file_id = %s WHERE id = %s",
                (*values.part_mm, file_id, where.job_id),
            )
            notes.append(f"part size {shown} from {number}")
        elif list(size) != values.part_mm:
            notes.append(
                f"kept the part size {' x '.join(map(str, size))} mm (the file gives {shown})"
            )
    if values.minutes_per_part is not None and minutes is None:
        conn.execute(
            "UPDATE jobs SET minutes_per_part = %s WHERE id = %s",
            (values.minutes_per_part, where.job_id),
        )
        notes.append(f"minutes per part {values.minutes_per_part} (estimate from {number})")
    return notes or ["nothing to fill: the job already has what the file gives"]


def override(
    conn: psycopg.Connection,
    actor: Actor,
    file_number: str,
    body: OverrideIn,
    key: str,
    today: date,
    cfg: FilesConfig,
) -> tuple[idempotency.StoredResponse, bool]:
    """Accept a warning with a reason. Never a fail: a failed check needs a fixed file."""
    endpoint = f"{OVERRIDE_ENDPOINT}/{file_number}"
    req_hash = idempotency.request_hash(body.model_dump(mode="json"))
    with conn.transaction():
        stored = idempotency.claim(
            conn, user_id=actor.user_id, endpoint=endpoint, key=key, req_hash=req_hash
        )
        if stored is not None:
            return idempotency.StoredResponse(
                stored.status, get_file(conn, actor, file_number).model_dump(mode="json")
            ), True
        row = _file_row(conn, actor, file_number)
        file_id, customer_id = int(row["id"]), int(row["customer_id"])
        _require(actor, "file.override", customer_id)
        report = Report.model_validate(row["report"])
        check = next((c for c in report.checks if c.name == body.check), None)
        if check is None:
            raise InvalidError(f"there is no check called {body.check!r}")
        if check.status != "warn":
            raise InvalidError(
                f"only a warning can be accepted; {body.check} is {check.status}"
                + (" (a failed check needs a fixed file)" if check.status == "fail" else "")
            )
        inserted = conn.execute(
            "INSERT INTO file_overrides (file_id, check_name, reason, overridden_by)"
            " VALUES (%s, %s, %s, %s) ON CONFLICT (file_id, check_name) DO NOTHING RETURNING id",
            (file_id, body.check, body.reason, actor.user_id),
        ).fetchone()
        if inserted is None:
            raise ConflictError(f"{body.check} on {file_number} was already accepted")
        applied: list[str] = []
        if body.check == "units":
            # Staff confirmed the unit: the size can now be used.
            where = _Resolved(
                kind="quote" if row["quote_id"] else "job",
                customer_id=customer_id,
                quote_id=row["quote_id"],
                job_id=row["job_id"],
                material_code=row["material_code"],
                process=row["process"],
            )
            values = planning_values(
                report, row["material_code"], row["process"], cfg, units_confirmed=True
            )
            applied = _apply(conn, where, file_id, file_number, report, values, today)
        audit.record(
            conn,
            actor_user_id=actor.user_id,
            action="file.override",
            entity_type="file",
            entity_id=file_number,
            before={"check": body.check, "status": "warn"},
            after={
                "check": body.check,
                "accepted": True,
                "reason": body.reason,
                "applied": applied,
            },
            idempotency_key=key,
        )
        idempotency.store(
            conn,
            user_id=actor.user_id,
            endpoint=endpoint,
            key=key,
            response=idempotency.StoredResponse(200, {"file_number": file_number}),
        )
        out = get_file(conn, actor, file_number).model_copy(update={"applied": applied})
        return idempotency.StoredResponse(200, out.model_dump(mode="json")), False


_FILE_SQL = (
    "SELECT f.id, f.customer_id, f.file_number, f.filename, f.unit, f.quote_id, f.quote_line,"
    "       f.job_id, q.quote_number, o.order_number, j.line_no, m.code AS material_code,"
    "       m.process, f.report, f.planning, u.display_name, f.created_at, f.content"
    " FROM files f JOIN users u ON u.id = f.uploaded_by"
    " LEFT JOIN quotes q ON q.id = f.quote_id"
    " LEFT JOIN jobs j ON j.id = f.job_id LEFT JOIN orders o ON o.id = j.order_id"
    " LEFT JOIN materials m ON m.id = f.material_id"
)


def _file_row(conn: psycopg.Connection, actor: Actor, file_number: str) -> dict[str, Any]:
    scope = order_scope(actor)
    cur = conn.execute(
        (
            _FILE_SQL
            + " WHERE f.file_number = %(n)s AND (%(s)s::bigint IS NULL OR f.customer_id = %(s)s::bigint)"
        ).encode(),
        {"n": file_number, "s": scope},
    )
    row = cur.fetchone()
    if row is None:
        raise NotFoundError(file_number)
    names = [d.name for d in cur.description or []]
    record = dict(zip(names, row, strict=True))
    if not can(actor, "file.read", OrderTarget(int(record["customer_id"]))):
        raise NotFoundError(file_number)
    return record


def get_file(conn: psycopg.Connection, actor: Actor, file_number: str) -> FileOut:
    r = _file_row(conn, actor, file_number)
    overrides = conn.execute(
        "SELECT o.check_name, o.reason, u.display_name, o.created_at FROM file_overrides o"
        " JOIN users u ON u.id = o.overridden_by WHERE o.file_id = %s ORDER BY o.id",
        (r["id"],),
    ).fetchall()
    advice = conn.execute(
        "SELECT a.advice, c.model, a.created_at FROM file_advice a"
        " LEFT JOIN ai_calls c ON c.id = a.ai_call_id WHERE a.file_id = %s ORDER BY a.id",
        (r["id"],),
    ).fetchall()
    report = Report.model_validate(r["report"])
    target = OrderTarget(int(r["customer_id"]))
    may_override = can(actor, "file.override", target)
    return FileOut(
        file_number=r["file_number"],
        filename=r["filename"],
        unit=r["unit"],
        target="quote" if r["quote_id"] else "job",
        quote_number=r["quote_number"],
        order_number=r["order_number"],
        line=r["quote_line"] or r["line_no"],
        material_code=r["material_code"],
        report=report,
        overall=quotes.effective_overall(r["report"], [o[0] for o in overrides]),
        planning=PlanningValues.model_validate(r["planning"]),
        applied=[],
        overrides=[OverrideOut(check=o[0], reason=o[1], by=o[2], at=o[3]) for o in overrides],
        advice=[AdviceOut(advice=a[0]["advice"], model=a[1], at=a[2]) for a in advice],
        uploaded_by=r["display_name"],
        uploaded_at=r["created_at"],
        can_override=may_override,
        can_ask_advice=may_override and files_config().advice.enabled,
    )


def file_content(conn: psycopg.Connection, actor: Actor, file_number: str) -> tuple[str, bytes]:
    r = _file_row(conn, actor, file_number)
    return str(r["filename"]), bytes(r["content"])


def latest_job_files(conn: psycopg.Connection, actor: Actor) -> dict[str, dict[str, str]]:
    """The latest file per job ("BL-0008-2" -> number and overall), for the board."""
    if not can(actor, "schedule.read"):
        raise ForbiddenError("schedule.read")
    rows = conn.execute(
        "SELECT DISTINCT ON (f.job_id) o.order_number || '-' || j.line_no, f.file_number, f.report,"
        "       (SELECT array_agg(x.check_name) FROM file_overrides x WHERE x.file_id = f.id)"
        " FROM files f JOIN jobs j ON j.id = f.job_id JOIN orders o ON o.id = j.order_id"
        " ORDER BY f.job_id, f.id DESC"
    ).fetchall()
    return {
        r[0]: {"file_number": r[1], "overall": quotes.effective_overall(r[2], r[3] or [])}
        for r in rows
    }


def preview_png(
    conn: psycopg.Connection, actor: Actor, file_number: str, cfg: FilesConfig
) -> bytes:
    """Three shaded views of the file, or NotFound when it cannot be read."""
    r = _file_row(conn, actor, file_number)
    try:
        mesh = read_mesh(bytes(r["content"]), str(r["filename"]), cfg.limits, str(r["unit"]))
    except ParseError as e:
        raise NotFoundError(file_number) from e
    if len(mesh.faces) == 0:
        raise NotFoundError(file_number)
    return render_png(mesh)


def ask_advice(
    conn: psycopg.Connection,
    actor: Actor,
    file_number: str,
    key: str,
    cfg: FilesConfig,
    client: ModelClient | None,
    mode: str,
) -> tuple[idempotency.StoredResponse, bool]:
    """Ask a vision model for advice on the preview (staff or planner, on request). Advice is
    stored apart and shown as advice; it changes no check, no verdict and no planning field."""
    endpoint = f"{ADVICE_ENDPOINT}/{file_number}"
    with conn.transaction():
        stored = idempotency.claim(
            conn, user_id=actor.user_id, endpoint=endpoint, key=key, req_hash="advice"
        )
        if stored is not None:
            return idempotency.StoredResponse(
                stored.status, get_file(conn, actor, file_number).model_dump(mode="json")
            ), True
        r = _file_row(conn, actor, file_number)
        _require(actor, "file.override", int(r["customer_id"]))
        if not cfg.advice.enabled:
            raise ConflictError("vision advice is off (config/files.toml [advice])")
        if client is None:
            raise ConflictError("AI is off (AI_MODE)")
        png = preview_png(conn, actor, file_number, cfg)
        result = advice.ask(client, mode, Report.model_validate(r["report"]), png)
        call_id = record_call(conn, result.record, actor.user_id)
        notes: list[str] = []
        if result.value is None:
            notes.append(f"no advice: the model call ended {result.record.outcome!r}")
        else:
            conn.execute(
                "INSERT INTO file_advice (file_id, ai_call_id, advice) VALUES (%s, %s, %s)",
                (r["id"], call_id, Jsonb(result.value.model_dump(mode="json"))),
            )
        audit.record(
            conn,
            actor_user_id=actor.user_id,
            action="file.advice",
            entity_type="file",
            entity_id=file_number,
            before=None,
            after={"ai_call_id": call_id, "advice": result.value.advice if result.value else None},
            idempotency_key=key,
        )
        idempotency.store(
            conn,
            user_id=actor.user_id,
            endpoint=endpoint,
            key=key,
            response=idempotency.StoredResponse(200, {"file_number": file_number}),
        )
        out = get_file(conn, actor, file_number).model_copy(update={"applied": notes})
        return idempotency.StoredResponse(200, out.model_dump(mode="json")), False
