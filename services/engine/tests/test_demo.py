"""The hosted demo's limits (M11, config/demo.toml): model spend and per-visitor caps with a
recorded-reply fallback, the web key, storage caps, and the shorter solver run. Demo mode is
switched on only inside each test; the rest of the suite runs with it off."""

from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest
from fastapi.testclient import TestClient

from brimline_engine.ai.clients import fake_reply
from brimline_engine.ai.gateway import ModelUnavailableError, ScriptedClient, Turn
from brimline_engine.ai.guard import (
    Budget,
    GuardedClient,
    RecordingClient,
    ReplayClient,
    Spend,
    demo_config,
    over_limit,
    prompt_key,
)
from brimline_engine.settings import get_settings
from tests.conftest import login

TURNS = [Turn("user", "<question>\njobs due this week not printed yet\n</question>")]
CALL = {
    "model": "deepseek-flash",
    "system": "s",
    "json_schema": {},
    "max_tokens": 10,
    "effort": "low",
}


@pytest.fixture
def demo_on(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("DEMO_MODE", "true")
    get_settings.cache_clear()
    yield
    monkeypatch.delenv("DEMO_MODE")
    get_settings.cache_clear()


def test_the_limits_in_plain_words() -> None:
    budget = Budget(daily_usd=0.50, per_visitor_per_hour=12)
    assert over_limit(Spend(today_usd=0.49, visitor_calls_last_hour=11), budget) is None
    assert "budget for today" in str(
        over_limit(Spend(today_usd=0.50, visitor_calls_last_hour=0), budget)
    )
    assert "this hour" in str(over_limit(Spend(today_usd=0.0, visitor_calls_last_hour=12), budget))


def test_a_recorded_reply_replays_exactly_and_an_unknown_prompt_falls_back(tmp_path: Path) -> None:
    path = tmp_path / "rec.jsonl"
    live = RecordingClient(ScriptedClient(fake_reply), path)
    first = live.call(turns=TURNS, **CALL)  # type: ignore[arg-type]
    replay = ReplayClient(path)
    assert replay.call(turns=TURNS, **CALL).text == first.text  # type: ignore[arg-type]
    assert prompt_key("deepseek-flash", "s", TURNS) in path.read_text(encoding="utf-8")
    with pytest.raises(ModelUnavailableError, match="no recorded reply"):
        replay.call(turns=[Turn("user", "something never recorded")], **CALL)  # type: ignore[arg-type]


class CountingClient:
    def __init__(self) -> None:
        self.calls = 0

    def call(self, **kw: object) -> object:
        self.calls += 1
        return ScriptedClient(fake_reply).call(**kw)  # type: ignore[arg-type]


def test_over_the_daily_budget_no_live_call_is_made(app_url: str, tmp_path: Path) -> None:
    live = CountingClient()
    empty = ReplayClient(tmp_path / "none.jsonl")
    over = GuardedClient(live, empty, app_url, Budget(daily_usd=0.0, per_visitor_per_hour=12))  # type: ignore[arg-type]
    with pytest.raises(ModelUnavailableError):
        over.call(turns=TURNS, **CALL)  # type: ignore[arg-type]
    under = GuardedClient(live, empty, app_url, Budget(daily_usd=1000.0, per_visitor_per_hour=12))  # type: ignore[arg-type]
    under.call(turns=TURNS, **CALL)  # type: ignore[arg-type]
    assert live.calls == 1  # only the call under the limit reached the model


def test_every_call_records_a_hashed_visitor_never_an_address(
    client: TestClient, owner_url: str
) -> None:
    client.post(
        "/search",
        json={"question": "jobs due this week not printed yet"},
        headers=login(client, "U-STAFF"),
    )
    with psycopg.connect(owner_url) as conn:
        row = conn.execute("SELECT visitor FROM ai_calls ORDER BY id DESC LIMIT 1").fetchone()
    assert row is not None and row[0] is not None and len(row[0]) == 16 and "." not in row[0]


def test_only_the_web_may_call_the_engine_when_a_key_is_set(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ENGINE_WEB_KEY", "k" * 40)
    get_settings.cache_clear()
    try:
        assert client.get("/materials").status_code == 401
        assert client.get("/health").status_code == 200  # for the host's health check
        ok = client.post(
            "/auth/demo-login", json={"user_code": "U-STAFF"}, headers={"X-Engine-Key": "k" * 40}
        )
        assert ok.status_code == 200
    finally:
        monkeypatch.delenv("ENGINE_WEB_KEY")
        get_settings.cache_clear()


def test_demo_mode_plans_shorter_and_says_so(client: TestClient, demo_on: None) -> None:
    s = client.get("/demo-status").json()
    assert (
        s["demo_mode"] is True and s["solver_seconds"] == 1.5 and s["full_solver_seconds"] == 20.0
    )
    assert s["max_upload_bytes"] == 4_000_000


def test_demo_mode_refuses_writes_past_the_row_cap(
    client: TestClient, demo_on: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    from brimline_engine import demo

    cfg = demo_config()
    tiny = cfg.model_copy(
        update={"storage": cfg.storage.model_copy(update={"max_rows": {"orders": 1}})}
    )
    monkeypatch.setattr(demo, "demo_config", lambda: tiny)
    body = {
        "customer_code": "C-HARBOR", "due_date": "2026-11-06", "rush": False, "notes": "",
        "lines": [{"part_name": "Bracket", "quantity": 1, "material_code": "PLA-BLACK"}],
    }  # fmt: skip
    r = client.post(
        "/orders", json=body, headers=login(client, "U-STAFF") | {"Idempotency-Key": "demo-cap-1"}
    )
    assert r.status_code == 503 and "resets every night" in r.json()["detail"]


def test_the_demo_seed_moves_by_whole_weeks_to_this_week() -> None:
    from datetime import date, timedelta

    from brimline_engine.db.demo_seed import shifted
    from brimline_engine.shop_config import load_shop_config

    shop = load_shop_config()
    # The seed is Monday 19 October 2026 (config/shop.toml). On Wednesday 11 November the shop
    # moves three weeks: an order due Friday 30 October is due Friday 20 November.
    moved = shifted(shop, date(2026, 11, 11))
    assert moved.seed_time.date() == date(2026, 11, 9)
    assert [o.due_date for o in moved.orders] == [
        o.due_date + timedelta(weeks=3) for o in shop.orders
    ]
    assert date(2026, 11, 20) in {o.due_date for o in moved.orders}
    # Prices start on 25 October in the seed (after its Monday); moved, they start no later than
    # the moved Monday, so a quote can be priced on the first day of the demo.
    assert moved.price_rules.effective_from == date(2026, 11, 9)
