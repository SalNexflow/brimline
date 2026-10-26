"""The gateway validates every reply, repairs once, and records cost and outcome."""

from decimal import Decimal
from typing import Any

import anthropic
import httpx2
import pytest
from pydantic import BaseModel, ValidationInfo, field_validator

from brimline_engine.ai.config import ModelPrice, TaskConfig, load_models_config
from brimline_engine.ai.gateway import (
    AnthropicClient,
    ModelReply,
    ModelUnavailableError,
    ScriptedClient,
    TokenUsage,
    Turn,
    cost_micro_usd,
    run_structured,
)

# Prices like the Opus row in config/models.toml, written out by hand.
PRICE = ModelPrice(
    provider="anthropic",
    input_usd_per_mtok=Decimal("4.00"),
    output_usd_per_mtok=Decimal("20.00"),
    cache_read_usd_per_mtok=Decimal("0.20"),
    cache_write_usd_per_mtok=Decimal("5.00"),
)
TASK = TaskConfig(model="claude-opus-5-5", effort="low", max_tokens=8000, prompt_version="test-v1")
USAGE = TokenUsage(input_tokens=1000, output_tokens=500)


class Part(BaseModel):
    name: str
    quantity: int

    @field_validator("name")
    @classmethod
    def known(cls, value: str, info: ValidationInfo) -> str:
        allowed = (info.context or {}).get("allowed")
        if allowed is not None and value not in allowed:
            raise ValueError(f"unknown part {value}")
        return value


def scripted(*replies: ModelReply) -> ScriptedClient:
    queue = list(replies)
    return ScriptedClient(lambda turns: queue.pop(0))


def run(client: ScriptedClient, context: dict[str, Any] | None = None) -> Any:
    ticks = iter([10.0, 10.25])  # the call "takes" 250 ms
    return run_structured(
        client,
        purpose="test",
        mode="fake",
        task=TASK,
        price=PRICE,
        schema=Part,
        json_schema={},
        system="Extract the part.",
        user="Ten widgets please",
        context=context,
        clock=lambda: next(ticks),
    )


def reply(text: str | None, stop: str = "end_turn") -> ModelReply:
    return ModelReply(text=text, stop_reason=stop, usage=USAGE)


def test_a_valid_reply_is_parsed_and_costed() -> None:
    result = run(scripted(reply('{"name": "widget", "quantity": 10}')))
    assert result.value == Part(name="widget", quantity=10)
    r = result.record
    assert (r.outcome, r.attempts, r.model, r.prompt_version) == (
        "valid",
        1,
        "claude-opus-5-5",
        "test-v1",
    )
    # 1000 input x $4/M = 4000 micro-USD; 500 output x $20/M = 10000 micro-USD.
    assert r.cost_micro_usd == 14000
    assert r.latency_ms == 250


def test_an_invalid_reply_is_repaired_once_with_the_errors_shown() -> None:
    client = scripted(reply('{"name": "widget"}'), reply('{"name": "widget", "quantity": 10}'))
    result = run(client)
    assert result.value == Part(name="widget", quantity=10)
    assert (result.record.outcome, result.record.attempts) == ("repaired", 2)
    assert result.record.usage == TokenUsage(input_tokens=2000, output_tokens=1000)
    second_call = client.calls[1]
    assert [t.role for t in second_call] == ["user", "assistant", "user"]
    assert second_call[1] == Turn("assistant", '{"name": "widget"}')
    assert (
        "quantity" in second_call[2].content and "did not pass validation" in second_call[2].content
    )


def test_two_invalid_replies_are_rejected_not_trusted() -> None:
    result = run(scripted(reply("not json"), reply('{"quantity": "ten"}')))
    assert result.value is None
    assert (result.record.outcome, result.record.attempts) == ("invalid", 2)
    assert result.record.error


def test_validation_can_use_context_such_as_the_catalog() -> None:
    client = scripted(
        reply('{"name": "gizmo", "quantity": 1}'), reply('{"name": "widget", "quantity": 1}')
    )
    result = run(client, context={"allowed": {"widget"}})
    assert result.value == Part(name="widget", quantity=1)
    assert "unknown part gizmo" in client.calls[1][2].content


def test_a_refusal_is_recorded_and_not_retried() -> None:
    client = scripted(reply(None, stop="refusal"))
    result = run(client)
    assert result.value is None
    assert (result.record.outcome, result.record.attempts) == ("refused", 1)
    assert len(client.calls) == 1


def test_a_cut_off_reply_is_not_trusted() -> None:
    result = run(
        scripted(reply('{"name": "wid', stop="max_tokens"), reply('{"name": "w', stop="max_tokens"))
    )
    assert result.value is None
    assert result.record.outcome == "invalid"
    assert "max_tokens" in (result.record.error or "")


def test_an_api_error_is_recorded_as_an_error() -> None:
    def fail(turns: list[Turn]) -> ModelReply:
        raise anthropic.APIConnectionError(request=httpx2.Request("POST", "https://api.example"))

    result = run(ScriptedClient(fail))
    assert result.value is None
    assert result.record.outcome == "error"
    assert "APIConnectionError" in (result.record.error or "")


@pytest.mark.parametrize(
    ("usage", "expected"),
    [
        (TokenUsage(input_tokens=1), 4),  # $4 per million = 4 micro-USD per token
        (TokenUsage(cache_read_tokens=3), 1),  # 0.6 rounds half up to 1
        (TokenUsage(cache_read_tokens=2), 0),  # 0.4 rounds down
        (TokenUsage(cache_write_tokens=2000, output_tokens=10), 10200),  # 10000 + 200
    ],
)
def test_cost_in_micro_usd(usage: TokenUsage, expected: int) -> None:
    assert cost_micro_usd(usage, PRICE) == expected


def test_the_models_config_is_complete_and_dated() -> None:
    cfg = load_models_config()
    task = cfg.task("quote_extract")
    assert task.model in cfg.prices
    assert cfg.task("quote_extract", model_override="claude-haiku-5-5").model == "claude-haiku-5-5"
    with pytest.raises(ValueError, match="no price configured"):
        cfg.task("quote_extract", model_override="some-unpriced-model")


def _live_run(client: AnthropicClient) -> Any:
    return run_structured(
        client,
        purpose="test",
        mode="live",
        task=TASK,
        price=PRICE,
        schema=Part,
        json_schema={"type": "object"},
        system="x",
        user="y",
    )


def test_a_missing_credentials_file_is_an_error_outcome(monkeypatch: pytest.MonkeyPatch) -> None:
    # DEFECT_LOG #13: the app must fall back to manual entry, not answer 500.
    for name in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_PROFILE"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("ANTHROPIC_CONFIG_DIR", "/nonexistent-brimline-test")
    result = _live_run(AnthropicClient())
    assert (result.value, result.record.outcome) == (None, "error")
    assert "CredentialsError" in (result.record.error or "")


class _NoAuthSdk:
    """Stands in for the SDK when no credential exists at all: it raises a plain TypeError."""

    class messages:  # noqa: N801  (mirrors the SDK attribute name)
        @staticmethod
        def create(**kwargs: Any) -> Any:
            raise TypeError('"Could not resolve authentication method. Expected one of api_key"')


def test_no_credential_at_all_is_an_error_outcome() -> None:
    result = _live_run(AnthropicClient(sdk=_NoAuthSdk()))  # type: ignore[arg-type]
    assert (result.value, result.record.outcome) == (None, "error")
    assert "ModelUnavailableError" in (result.record.error or "")


def test_other_type_errors_still_crash() -> None:
    def broken(turns: list[Turn]) -> ModelReply:
        raise TypeError("a real bug in our code")

    with pytest.raises(TypeError, match="a real bug"):
        run(ScriptedClient(broken))
    assert issubclass(ModelUnavailableError, Exception)
