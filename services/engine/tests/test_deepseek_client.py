"""The DeepSeek client against a fake HTTP transport: no network, no cost."""

import json
from decimal import Decimal
from typing import Any

import httpx2
import pytest
from pydantic import BaseModel

from brimline_engine.ai.config import ModelPrice, TaskConfig, load_models_config
from brimline_engine.ai.deepseek import DeepSeekClient
from brimline_engine.ai.gateway import run_structured

# Peak DeepSeek-flash prices, as in config/models.toml, written out by hand.
PRICE = ModelPrice(
    provider="deepseek",
    input_usd_per_mtok=Decimal("0.30"),
    output_usd_per_mtok=Decimal("1.20"),
    cache_read_usd_per_mtok=Decimal("0.006"),
    cache_write_usd_per_mtok=Decimal("0"),
)
TASK = TaskConfig(model="deepseek-flash", effort="low", max_tokens=8000, prompt_version="test-v1")


class Part(BaseModel):
    name: str
    quantity: int


def completion(content: str | None, finish: str = "stop", **usage: int) -> dict[str, Any]:
    return {
        "choices": [
            {"message": {"role": "assistant", "content": content}, "finish_reason": finish}
        ],
        "usage": {
            "prompt_tokens": usage.get("hit", 0) + usage.get("miss", 1000),
            "prompt_cache_hit_tokens": usage.get("hit", 0),
            "prompt_cache_miss_tokens": usage.get("miss", 1000),
            "completion_tokens": usage.get("out", 500),
        },
    }


def client_with(
    *responses: httpx2.Response, key: str | None = "sk-test"
) -> tuple[DeepSeekClient, list[httpx2.Request]]:
    queue = list(responses)
    seen: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return queue.pop(0)

    http = httpx2.Client(transport=httpx2.MockTransport(handler))
    return DeepSeekClient(
        api_key=key, base_url="https://api.deepseek.example", http=http, sleep=lambda s: None
    ), seen


def run(client: DeepSeekClient) -> Any:
    return run_structured(
        client,
        purpose="test",
        mode="live",
        task=TASK,
        price=PRICE,
        schema=Part,
        json_schema={"type": "object", "properties": {"name": {"type": "string"}}},
        system="Extract the part.",
        user="Ten widgets",
    )


def test_the_request_uses_json_mode_effort_and_the_schema() -> None:
    client, seen = client_with(
        httpx2.Response(200, json=completion('{"name": "widget", "quantity": 10}'))
    )
    result = run(client)
    assert result.value == Part(name="widget", quantity=10)
    request = seen[0]
    assert str(request.url) == "https://api.deepseek.example/chat/completions"
    assert request.headers["Authorization"] == "Bearer sk-test"
    body = json.loads(request.content)
    assert (
        body["model"],
        body["response_format"],
        body["reasoning_effort"],
        body["max_tokens"],
    ) == (
        "deepseek-flash",
        {"type": "json_object"},
        "low",
        8000,
    )
    system = body["messages"][0]
    assert system["role"] == "system"
    assert "JSON" in system["content"] and '"properties"' in system["content"]
    assert body["messages"][1] == {"role": "user", "content": "Ten widgets"}


def test_usage_and_cost_by_hand() -> None:
    client, _ = client_with(
        httpx2.Response(
            200, json=completion('{"name": "w", "quantity": 1}', hit=2000, miss=1000, out=500)
        )
    )
    record = run(client).record
    assert (
        record.usage.input_tokens,
        record.usage.cache_read_tokens,
        record.usage.output_tokens,
    ) == (1000, 2000, 500)
    # 1000 x $0.30/M = 300; 2000 x $0.006/M = 12; 500 x $1.20/M = 600. Total 912 micro-USD.
    assert record.cost_micro_usd == 912


def test_an_empty_reply_is_repaired() -> None:
    client, seen = client_with(
        httpx2.Response(200, json=completion("")),
        httpx2.Response(200, json=completion('{"name": "w", "quantity": 2}')),
    )
    result = run(client)
    assert (result.value, result.record.outcome) == (Part(name="w", quantity=2), "repaired")
    assert len(seen) == 2


@pytest.mark.parametrize(
    ("finish", "outcome"), [("content_filter", "refused"), ("length", "invalid")]
)
def test_finish_reasons(finish: str, outcome: str) -> None:
    client, _ = client_with(
        *(httpx2.Response(200, json=completion('{"name"', finish=finish)) for _ in range(2))
    )
    assert run(client).record.outcome == outcome


def test_an_http_error_is_an_error_outcome_and_the_key_is_not_logged() -> None:
    client, _ = client_with(
        httpx2.Response(401, json={"error": {"message": "Authentication Fails"}})
    )
    record = run(client).record
    assert record.outcome == "error"
    assert "HTTP 401" in (record.error or "")
    assert "sk-test" not in (record.error or "")


def test_rate_limits_are_retried() -> None:
    client, seen = client_with(
        httpx2.Response(429, json={}),
        httpx2.Response(200, json=completion('{"name": "w", "quantity": 3}')),
    )
    assert run(client).value == Part(name="w", quantity=3)
    assert len(seen) == 2


def test_no_key_means_no_request_and_an_error_outcome() -> None:
    client, seen = client_with(key=None)
    record = run(client).record
    assert record.outcome == "error"
    assert "DEEPSEEK_API_KEY" in (record.error or "")
    assert seen == []


def test_every_configured_model_has_a_known_provider() -> None:
    cfg = load_models_config()
    for name, price in cfg.prices.items():
        assert price.provider in cfg.providers, name
    assert cfg.prices[cfg.task("quote_extract").model].provider == "deepseek"
