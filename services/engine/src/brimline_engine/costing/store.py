"""Reading and writing job outcomes (job_outcomes). The arithmetic is in outcome.py and report.py.

When a job's last task is done, `record_outcome` reads every attempt the job took and freezes
one row. Attempts, from the tasks as recorded:

  - a machine run is a print or machining task that ended (done or failed). Approving a new plan
    copies done and running machine tasks into it (planning.schedules), so the same run can sit in
    two plans; it is counted once, by its start time, with the copy that has its grams;
  - every failed task ends an attempt (the job is then planned again from the start): it belongs
    to the latest machine run started before it, or, failing before any run, to an attempt with
    no machine time (its setup still counts).
"""

from dataclasses import dataclass
from datetime import datetime

import psycopg

from brimline_engine.costing.config import costing_config
from brimline_engine.costing.outcome import Attempt, Estimate, Rates, outcome
from brimline_engine.costing.report import CostReport, JobRow, build
from brimline_engine.shop_config import load_shop_config


@dataclass
class _Run:
    start: datetime
    seconds: int
    grams: int | None
    failed: bool


def _attempts(conn: psycopg.Connection, job_id: int) -> tuple[list[Attempt], list[str]]:
    runs = [
        _Run(s, int((e - s).total_seconds()), g, st == "failed")
        for s, e, g, st in conn.execute(
            "SELECT DISTINCT ON (actual_start) actual_start, actual_end, material_used_g, status"
            " FROM tasks WHERE job_id = %s AND kind = 'machine' AND status IN ('done', 'failed')"
            " ORDER BY actual_start, (material_used_g IS NULL), schedule_id DESC",
            (job_id,),
        )
    ]
    failures = conn.execute(
        "SELECT actual_start, failure_reason, kind FROM tasks"
        " WHERE job_id = %s AND status = 'failed' ORDER BY actual_start, id",
        (job_id,),
    ).fetchall()
    for at, _, kind in failures:
        if kind == "machine":
            continue  # the failed run is that attempt itself
        before = [r for r in runs if r.start <= at]
        if before and not before[-1].failed:
            before[-1].failed = True  # e.g. a print that failed its quality check
        else:  # failed before this attempt's machine run: setup only
            runs.append(_Run(at, 0, 0, True))
            runs.sort(key=lambda r: r.start)
    return (
        [Attempt(machine_seconds=r.seconds, grams_used=r.grams, failed=r.failed) for r in runs],
        [reason or "other" for _, reason, _ in failures],
    )


def record_outcome(conn: psycopg.Connection, job_id: int, finished_at: datetime) -> None:
    """Freeze the finished job's outcome. Called inside the transaction that finishes the job."""
    job = conn.execute(
        "SELECT o.order_number, j.line_no, j.part_name, j.quantity, j.minutes_per_part,"
        "       j.material_id, m.process, j.order_id"
        " FROM jobs j JOIN orders o ON o.id = j.order_id JOIN materials m ON m.id = j.material_id"
        " WHERE j.id = %s",
        (job_id,),
    ).fetchone()
    assert job is not None
    number, line_no, part, qty, minutes, material_id, process, order_id = job
    attempts, reasons = _attempts(conn, job_id)
    if not attempts:
        attempts = [Attempt(machine_seconds=0, grams_used=0, failed=False)]
    quoted = conn.execute(
        "SELECT q.price_rule_set_id, l.grams_per_part, l.minutes_per_part, r.setup_cents,"
        "       mr.cents_per_gram, pr.cents_per_minute"
        " FROM quotes q JOIN quote_lines l ON l.quote_id = q.id AND l.line_no = %s"
        " JOIN price_rule_sets r ON r.id = q.price_rule_set_id"
        " JOIN price_material_rates mr ON mr.rule_set_id = r.id AND mr.material_id = %s"
        " JOIN price_machine_rates pr ON pr.rule_set_id = r.id AND pr.process = %s"
        " WHERE q.order_id = %s AND q.status = 'approved'",
        (line_no, material_id, process, order_id),
    ).fetchone()
    label = f"{number} line {line_no} {part}"
    if quoted is None:
        # No quote: time only, against the minutes the plan used (the job always has them).
        o = outcome(Estimate(qty, 1, minutes or 1), Rates(0, 0, 0), attempts)
        recorded = sum(a.grams_used or 0 for a in attempts)  # no quoted grams to assume
        values: tuple[object, ...] = (None, None, None, None, recorded)
    else:
        rule_set, grams, q_minutes, setup, per_gram, per_minute = quoted
        o = outcome(Estimate(qty, grams, q_minutes), Rates(setup, per_gram, per_minute), attempts)
        values = (rule_set, o.estimated_cents, o.actual_cents, o.estimated_grams, o.actual_grams)
    conn.execute(
        "INSERT INTO job_outcomes (job_id, label, material_id, process, quantity,"
        " price_rule_set_id, estimated_cents, actual_cents, estimated_grams, actual_grams,"
        " estimated_minutes, actual_seconds, grams_assumed, attempts, failed_attempts,"
        " failure_reasons, finished_at)"
        " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (
            job_id,
            label,
            material_id,
            process,
            qty,
            *values,
            o.estimated_minutes,
            o.actual_seconds,
            o.grams_assumed if quoted else 0,
            o.attempts,
            o.failed_attempts,
            reasons,
            finished_at,
        ),
    )


def insert_synthetic(conn: psycopg.Connection, rows: list[JobRow]) -> None:
    """Seeded history, labelled synthetic on the Reports page (demo and dev seed only)."""
    ids: dict[str, int] = {c: i for c, i in conn.execute("SELECT code, id FROM materials")}
    for r in rows:
        conn.execute(
            "INSERT INTO job_outcomes (synthetic, label, material_id, process, quantity,"
            " estimated_cents, actual_cents, estimated_minutes, actual_seconds, grams_assumed,"
            " attempts, failed_attempts, failure_reasons, finished_at)"
            " VALUES (true, %s, %s, %s, 1, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (
                r.label,
                ids[r.material_code],
                r.process,
                r.estimated_cents,
                r.actual_cents,
                r.estimated_minutes,
                r.actual_seconds,
                r.grams_assumed,
                r.attempts,
                r.failed_attempts,
                list(r.failure_reasons),
                r.finished_at,
            ),
        )


def load_report(conn: psycopg.Connection) -> CostReport:
    rows = [
        JobRow(
            label=label,
            material_code=code,
            process=process,
            estimated_cents=est,
            actual_cents=act,
            estimated_minutes=est_min,
            actual_seconds=secs,
            attempts=attempts,
            failed_attempts=failed,
            failure_reasons=tuple(reasons),
            grams_assumed=assumed,
            synthetic=synthetic,
            finished_at=finished,
        )
        for (
            label,
            code,
            process,
            est,
            act,
            est_min,
            secs,
            attempts,
            failed,
            reasons,
            assumed,
            synthetic,
            finished,
        ) in conn.execute(
            "SELECT o.label, m.code, o.process, o.estimated_cents, o.actual_cents,"
            " o.estimated_minutes, o.actual_seconds, o.attempts, o.failed_attempts,"
            " o.failure_reasons, o.grams_assumed, o.synthetic, o.finished_at"
            " FROM job_outcomes o JOIN materials m ON m.id = o.material_id ORDER BY o.id"
        ).fetchall()
    ]
    return build(rows, costing_config().flag, load_shop_config().shop.currency)
