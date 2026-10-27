"""Model files over HTTP (M7): a checked file fills the planning fields it can, on a quote line or
a job; staff values are never overwritten; a failed file blocks approval; warnings are accepted
only with a reason. Expected numbers come from geometry (a 40 mm cube is 64 cm³) and the
config's stated formulas, worked out by hand in the comments."""

import uuid
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient

from brimline_engine.files import samples as s
from tests.conftest import login
from tests.test_quotes_api import COMPLETE_EDIT, decide, edit, submit

CUBE = s.binary_stl(s.box(40, 40, 40))
OPEN_CUBE = s.binary_stl(s.box(40, 40, 40)[1:])
METRES = s.binary_stl(s.box(0.04, 0.04, 0.04))  # a 40 mm cube saved in metres


def key() -> dict[str, str]:
    return {"Idempotency-Key": f"test-{uuid.uuid4()}"}


def upload(
    client: TestClient,
    user: str,
    data: bytes,
    *,
    quote: str | None = None,
    order: str | None = None,
    line: int = 1,
    filename: str = "part.stl",
    unit: str = "millimeter",
    headers: dict[str, str] | None = None,
) -> Any:
    params: dict[str, Any] = {"line": line, "filename": filename, "unit": unit}
    if quote:
        params["quote"] = quote
    if order:
        params["order"] = order
    return client.post(
        "/files",
        params=params,
        content=data,
        headers={**login(client, user), "Content-Type": "application/octet-stream"}
        | (headers or key()),
    )


def new_quote(client: TestClient, user: str = "U-STAFF") -> str:
    # The fake model drafts one line: 20 phone stands in PETG-BLACK, grams and minutes missing.
    return str(submit(client, user).json()["quote_number"])


def new_order(client: TestClient, material: str = "PLA-BLACK") -> str:
    body = {
        "customer_code": "C-HARBOR",
        "due_date": "2026-11-06",
        "rush": False,
        "notes": "",
        "lines": [{"part_name": "Bracket", "quantity": 4, "material_code": material}],
    }
    r = client.post("/orders", json=body, headers=login(client, "U-STAFF") | key())
    assert r.status_code == 201, r.text
    return str(r.json()["order_number"])


def job_row(owner_url: str, order: str) -> tuple[Any, ...]:
    with psycopg.connect(owner_url) as conn:
        row = conn.execute(
            "SELECT j.part_x_mm, j.part_y_mm, j.part_z_mm, j.minutes_per_part, j.part_size_file_id"
            " FROM jobs j JOIN orders o ON o.id = j.order_id WHERE o.order_number = %s AND j.line_no = 1",
            (order,),
        ).fetchone()
    assert row is not None
    return tuple(row)


# --- Quote lines --------------------------------------------------------------------------------


def test_a_customer_file_fills_size_grams_and_minutes_on_their_quote(client: TestClient) -> None:
    number = new_quote(client, "U-HARBOR")
    r = upload(client, "U-HARBOR", CUBE, quote=number)
    assert r.status_code == 201, r.text
    f = r.json()
    assert f["overall"] == "pass" and f["file_number"].startswith("F-")
    # PETG 1.27 g/cm³: 64 x 1.27 x 0.5 = 40.6 -> 41 g; 32,000 mm³ / 300 per min = 106.7 -> 107.
    assert f["planning"]["part_mm"] == [40, 40, 40]
    assert (f["planning"]["grams_per_part"], f["planning"]["minutes_per_part"]) == (41, 107)
    assert any("part size: 40 x 40 x 40 mm from the file" in a for a in f["applied"])
    staff = client.get(f"/quotes/{number}", headers=login(client, "U-STAFF")).json()
    line = staff["lines"][0]
    assert (line["part_mm"], line["grams_per_part"], line["minutes_per_part"]) == (
        [40, 40, 40],
        41,
        107,
    )
    assert line["sources"]["part_mm"] == line["sources"]["grams_per_part"] == "file"
    assert staff["files"] == [
        {"line_no": 1, "file_number": f["file_number"], "filename": "part.stl", "overall": "pass"}
    ]
    assert staff["price_pending"] == []  # code priced it from the file's numbers
    # The customer sees the size, not the shop's working numbers.
    own = client.get(f"/quotes/{number}", headers=login(client, "U-HARBOR")).json()
    assert own["lines"][0]["grams_per_part"] is None and own["lines"][0]["part_mm"] == [40, 40, 40]


def test_a_retried_upload_is_one_file(client: TestClient) -> None:
    number = new_quote(client)
    k = key()
    first = upload(client, "U-STAFF", CUBE, quote=number, headers=k)
    again = upload(client, "U-STAFF", CUBE, quote=number, headers=k)
    assert again.status_code == 201 and again.headers["Idempotent-Replayed"] == "true"
    assert again.json()["file_number"] == first.json()["file_number"]
    other = upload(client, "U-STAFF", OPEN_CUBE, quote=number, headers=k)
    assert other.status_code == 409


def test_a_file_never_overwrites_what_staff_entered(client: TestClient) -> None:
    number = new_quote(client)
    assert edit(client, "U-STAFF", number, COMPLETE_EDIT).status_code == 200  # 35 g, 90 min
    f = upload(client, "U-STAFF", CUBE, quote=number).json()
    line = client.get(f"/quotes/{number}", headers=login(client, "U-STAFF")).json()["lines"][0]
    assert (line["grams_per_part"], line["minutes_per_part"]) == (35, 90)
    assert line["part_mm"] == [40, 40, 40]  # the size was missing, so the file fills it
    assert any("kept 35 entered by staff (the file gives 41)" in a for a in f["applied"])


def test_staff_editing_a_line_keeps_the_files_values_and_their_source(client: TestClient) -> None:
    number = new_quote(client)
    upload(client, "U-STAFF", CUBE, quote=number)
    body = COMPLETE_EDIT | {
        "lines": [
            COMPLETE_EDIT["lines"][0]
            | {"grams_per_part": 41, "minutes_per_part": 107, "part_mm": [40, 40, 40]}
        ]
    }
    assert edit(client, "U-STAFF", number, body).status_code == 200
    line = client.get(f"/quotes/{number}", headers=login(client, "U-STAFF")).json()["lines"][0]
    assert line["sources"]["part_mm"] == "file" and line["sources"]["grams_per_part"] == "file"


def test_a_new_file_replaces_values_an_earlier_file_gave(client: TestClient) -> None:
    number = new_quote(client)
    upload(client, "U-STAFF", CUBE, quote=number)
    f = upload(client, "U-STAFF", OPEN_CUBE, quote=number).json()  # size yes, volume no
    line = client.get(f"/quotes/{number}", headers=login(client, "U-STAFF")).json()["lines"][0]
    assert line["part_mm"] == [40, 40, 40] and line["grams_per_part"] is None
    assert line["sources"]["grams_per_part"] == "missing"
    assert any("grams per part: cleared" in a for a in f["applied"])


def test_a_failed_file_blocks_approval_and_a_fixed_one_gives_the_job_its_size(
    client: TestClient, owner_url: str
) -> None:
    number = new_quote(client)
    assert edit(client, "U-STAFF", number, COMPLETE_EDIT).status_code == 200
    bad = upload(client, "U-STAFF", OPEN_CUBE, quote=number).json()
    assert bad["overall"] == "fail"
    r = decide(client, "U-STAFF", number, "approve")
    assert r.status_code == 422 and bad["file_number"] in r.json()["detail"]
    upload(client, "U-STAFF", CUBE, quote=number)
    r = decide(client, "U-STAFF", number, "approve")
    assert r.status_code == 200, r.text
    # The gap M7 closes: an order made from a quote now has a part size, so it can be planned.
    assert job_row(owner_url, r.json()["order_number"])[:3] == (40, 40, 40)


def test_files_go_only_with_draft_quotes_and_the_right_customer(client: TestClient) -> None:
    number = new_quote(client, "U-HARBOR")
    assert upload(client, "U-WILLOW", CUBE, quote=number).status_code == 404  # another customer
    assert upload(client, "U-OPERATOR", CUBE, quote=number).status_code == 404  # cannot see quotes
    assert upload(client, "U-STAFF", CUBE, quote=number, line=7).status_code == 422
    decide(client, "U-STAFF", number, "reject")
    assert upload(client, "U-STAFF", CUBE, quote=number).status_code == 422


# --- Jobs on the board ---------------------------------------------------------------------------


def test_a_file_gives_a_job_without_a_size_its_size_and_a_later_file_replaces_it(
    client: TestClient, owner_url: str
) -> None:
    order = new_order(client)
    assert job_row(owner_url, order)[:4] == (None, None, None, None)
    first = upload(client, "U-PLANNER", CUBE, order=order)
    assert first.status_code == 201, first.text
    # PLA: 32,000 mm³ / 300 per min -> 107 minutes, filled because the job had none.
    x, y, z, minutes, file_id = job_row(owner_url, order)
    assert (x, y, z, minutes) == (40, 40, 40, 107) and file_id is not None
    upload(client, "U-PLANNER", s.binary_stl(s.box(50, 40, 30)), order=order)
    assert job_row(owner_url, order)[:4] == (50, 40, 30, 107)  # size replaced; minutes kept
    board = client.get("/files/jobs", headers=login(client, "U-PLANNER")).json()
    assert board[f"{order}-1"]["overall"] == "pass"


def test_a_size_from_the_seed_or_a_person_is_kept(client: TestClient, owner_url: str) -> None:
    before = job_row(owner_url, "BL-0001")
    f = upload(client, "U-PLANNER", CUBE, order="BL-0001").json()
    assert job_row(owner_url, "BL-0001") == before
    assert any("kept the part size 180 x 120 x 6 mm" in a for a in f["applied"])


def test_only_shop_staff_attach_files_to_jobs(client: TestClient) -> None:
    order = new_order(client)  # a C-HARBOR order
    assert upload(client, "U-HARBOR", CUBE, order=order).status_code == 403
    assert upload(client, "U-OPERATOR", CUBE, order=order).status_code == 403
    assert upload(client, "U-WILLOW", CUBE, order=order).status_code == 404
    assert upload(client, "U-STAFF", CUBE, order=order).status_code == 201


# --- Warnings, overrides, reading ----------------------------------------------------------------


def test_a_unit_warning_holds_the_size_back_until_staff_confirm_it(
    client: TestClient, owner_url: str
) -> None:
    order = new_order(client)
    f = upload(client, "U-PLANNER", METRES, order=order).json()
    assert f["overall"] == "warn" and f["planning"]["part_mm"] is None
    assert job_row(owner_url, order)[:3] == (None, None, None)
    path = f"/files/{f['file_number']}/overrides"
    planner = login(client, "U-PLANNER")
    r = client.post(
        path,
        json={"check": "units", "reason": "customer confirmed: a 1 mm bead"},
        headers=planner | key(),
    )
    assert r.status_code == 200, r.text
    assert r.json()["overall"] == "pass" and r.json()["overrides"][0]["reason"].startswith(
        "customer"
    )
    assert job_row(owner_url, order)[:3] == (1, 1, 1)  # 0.04 mm rounded up to whole mm
    again = client.post(path, json={"check": "units", "reason": "again"}, headers=planner | key())
    assert again.status_code == 409
    with psycopg.connect(owner_url) as conn:
        row = conn.execute(
            "SELECT count(*) FROM audit_log WHERE action = 'file.override' AND entity_id = %s",
            (f["file_number"],),
        ).fetchone()
    assert row is not None and row[0] == 1


def test_a_failed_check_cannot_be_accepted(client: TestClient) -> None:
    order = new_order(client)
    f = upload(client, "U-PLANNER", OPEN_CUBE, order=order).json()
    path = f"/files/{f['file_number']}/overrides"
    planner = login(client, "U-PLANNER")
    r = client.post(
        path, json={"check": "watertight", "reason": "looks fine to me"}, headers=planner | key()
    )
    assert r.status_code == 422 and "needs a fixed file" in r.json()["detail"]
    r = client.post(
        path, json={"check": "fits", "reason": "it passed anyway"}, headers=planner | key()
    )
    assert r.status_code == 422
    op = login(client, "U-OPERATOR")
    r = client.post(path, json={"check": "units", "reason": "operator"}, headers=op | key())
    assert r.status_code == 403
    assert client.get(f"/files/{f['file_number']}", headers=op).status_code == 200


def test_customers_read_only_their_own_files(client: TestClient) -> None:
    number = new_quote(client, "U-HARBOR")
    f = upload(client, "U-HARBOR", CUBE, quote=number).json()
    assert (
        client.get(f"/files/{f['file_number']}", headers=login(client, "U-HARBOR")).status_code
        == 200
    )
    assert (
        client.get(f"/files/{f['file_number']}", headers=login(client, "U-WILLOW")).status_code
        == 404
    )
    assert (
        client.get(f"/files/{f['file_number']}", headers=login(client, "U-HARBOR")).json()[
            "can_override"
        ]
        is False
    )


@pytest.mark.parametrize(
    "query", ["UPDATE files SET overall = 'pass'", "DELETE FROM file_overrides"]
)
def test_file_rows_cannot_be_rewritten(app_url: str, query: str) -> None:
    with psycopg.connect(app_url) as conn, pytest.raises(psycopg.errors.Error):
        conn.execute(query.encode())
