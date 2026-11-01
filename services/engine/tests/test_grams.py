"""Where a job's grams per part come from (M9): entered, else the file checker's estimate, else the
approved quote's line, else "cannot plan: grams per part". Each source is labelled on the board."""

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from brimline_engine.materials.grams import Grams, resolve
from tests.conftest import login
from tests.test_costing_api import quoted_job  # noqa: F401 (fixture used by name)
from tests.test_files_api import leave_no_plannable_jobs, upload  # noqa: F401 (fixture)
from tests.test_planning_api import (  # noqa: F401 (fixtures used by name)
    draft,
    fresh_planning_state,
    key,
    plan_day,
)

CUBE = (
    Path(__file__).resolve().parents[3]
    / "eval"
    / "datasets"
    / "files"
    / "blind"
    / "models"
    / "b01.stl"
)


@pytest.mark.parametrize(
    ("entered", "from_file", "from_quote", "expected"),
    [
        (12, 30, 40, Grams(12, "entered")),
        (None, 30, 40, Grams(30, "file estimate")),
        (None, None, 40, Grams(40, "quote")),
        (None, None, None, Grams(None, None)),
        (12, None, None, Grams(12, "entered")),
        (None, 30, None, Grams(30, "file estimate")),
    ],
)
def test_the_fallback_order(
    entered: int | None, from_file: int | None, from_quote: int | None, expected: Grams
) -> None:
    assert resolve(entered, from_file, from_quote) == expected


def order(client: TestClient, grams: int | None) -> str:
    line: dict[str, Any] = {"part_name": "Bracket", "quantity": 2, "material_code": "PLA-BLACK"}
    if grams is not None:
        line["grams_per_part"] = grams
    body = {"customer_code": "C-HARBOR", "due_date": "2026-11-06", "rush": False, "notes": "",
            "lines": [line]}  # fmt: skip
    r = client.post("/orders", json=body, headers=login(client, "U-STAFF") | key())
    assert r.status_code == 201, r.text
    return str(r.json()["order_number"])


def board_job(client: TestClient, job: str) -> tuple[dict[str, Any] | None, list[str] | None]:
    planner = login(client, "U-PLANNER")
    plan_day(client, planner)
    d = draft(client, planner)
    found = next((j for j in d["jobs"] if j["key"] == job), None)
    missing = next((u["missing"] for u in d["unplannable"] if u["job"] == job), None)
    return found, missing


def test_a_hand_made_order_without_grams_says_so(client: TestClient) -> None:
    number = order(client, None)
    _, missing = board_job(client, f"{number}-1")
    # It also misses minutes and size (the order form has none); grams are named plainly.
    assert missing is not None
    assert "grams per part (enter them, or upload the part's file)" in missing


def test_entered_grams_are_used_and_labelled(client: TestClient) -> None:
    number = order(client, 15)
    # Give it what else it needs from a file, which also estimates grams: the entry still wins.
    r = upload(client, "U-STAFF", CUBE.read_bytes(), order=number, filename="cube.stl")
    assert r.status_code == 201, r.text
    job, missing = board_job(client, f"{number}-1")
    assert missing is None, missing
    assert job is not None and (job["grams_per_part"], job["grams_source"]) == (15, "entered")


def test_the_file_estimate_fills_in_when_nothing_was_entered(client: TestClient) -> None:
    number = order(client, None)
    r = upload(client, "U-STAFF", CUBE.read_bytes(), order=number, filename="cube.stl")
    assert r.status_code == 201, r.text
    estimate = r.json()["planning"]["grams_per_part"]
    assert estimate is not None
    job, missing = board_job(client, f"{number}-1")
    assert missing is None, missing
    assert job is not None and (job["grams_per_part"], job["grams_source"]) == (
        estimate,
        "file estimate",
    )


def test_an_approved_quote_gives_its_grams(client: TestClient, quoted_job: str) -> None:  # noqa: F811
    # The phone stands' quote says 35 g per part (tests/test_costing_api.py).
    job, missing = board_job(client, quoted_job)
    assert missing is None
    assert job is not None and (job["grams_per_part"], job["grams_source"]) == (35, "quote")
