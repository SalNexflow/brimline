"""The AI gateway: the only way the engine calls a model (hard rules 2 and 8).

    result = run_structured(client, task, QuoteDraft, system=..., user=..., context=...)

1. Sends the request with structured outputs (a JSON schema derived from the pydantic model).
2. Validates the reply with that pydantic model in our own code, whatever the API promised.
3. On a validation failure, asks once for a corrected reply, showing the errors. Then gives up.
4. Returns the parsed value (or None) and a CallRecord: model, tokens, cost, latency, outcome.

It never writes to the database; callers store the CallRecord (see brimline_engine.ai.calls).
"""

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Literal, Protocol

import anthropic
from anthropic.types import (
    AssistantMessageParam,
    MessageParam,
    OutputConfigParam,
    TextBlockParam,
    UserMessageParam,
)
from pydantic import BaseModel, ValidationError

from brimline_engine.ai.config import Effort, ModelPrice, TaskConfig

Outcome = Literal["valid", "repaired", "invalid", "refused", "error", "skipped"]


@dataclass(frozen=True)
class TokenUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0

    def __add__(self, other: "TokenUsage") -> "TokenUsage":
        return TokenUsage(
            self.input_tokens + other.input_tokens,
            self.output_tokens + other.output_tokens,
            self.cache_read_tokens + other.cache_read_tokens,
            self.cache_write_tokens + other.cache_write_tokens,
        )


@dataclass(frozen=True)
class ModelReply:
    text: str | None  # the JSON text block, if any
    stop_reason: str | None
    usage: TokenUsage


@dataclass(frozen=True)
class Turn:
    role: Literal["user", "assistant"]
    content: str


class ModelClient(Protocol):
    def call(
        self,
        *,
        model: str,
        system: str,
        turns: list[Turn],
        json_schema: dict[str, Any],
        max_tokens: int,
        effort: Effort,
    ) -> ModelReply: ...


@dataclass(frozen=True)
class CallRecord:
    purpose: str
    mode: str
    model: str | None
    prompt_version: str
    outcome: Outcome
    attempts: int
    usage: TokenUsage
    cost_micro_usd: int
    latency_ms: int
    error: str | None = None
    raw_replies: tuple[str | None, ...] = field(default=())


@dataclass(frozen=True)
class GatewayResult[T]:
    value: T | None
    record: CallRecord


def cost_micro_usd(usage: TokenUsage, price: ModelPrice) -> int:
    """Cost in millionths of a dollar. USD per million tokens x tokens = micro-USD."""
    total = (
        usage.input_tokens * price.input_usd_per_mtok
        + usage.output_tokens * price.output_usd_per_mtok
        + usage.cache_read_tokens * price.cache_read_usd_per_mtok
        + usage.cache_write_tokens * price.cache_write_usd_per_mtok
    )
    return int(Decimal(total).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def _repair_message(error: str) -> str:
    return (
        "Your reply did not pass validation:\n"
        f"{error}\n"
        "Reply again with corrected JSON for the same message. Change only what the errors require."
    )


def _short(exc: ValidationError | ValueError) -> str:
    if isinstance(exc, ValidationError):
        return "\n".join(
            f"- {'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()[:10]
        )
    return f"- {exc}"


def run_structured[T: BaseModel](
    client: ModelClient,
    *,
    purpose: str,
    mode: str,
    task: TaskConfig,
    price: ModelPrice,
    schema: type[T],
    json_schema: dict[str, Any],
    system: str,
    user: str,
    context: dict[str, Any] | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> GatewayResult[T]:
    turns = [Turn("user", user)]
    usage = TokenUsage()
    replies: list[str | None] = []
    started = clock()

    def record(outcome: Outcome, error: str | None = None) -> CallRecord:
        return CallRecord(
            purpose=purpose,
            mode=mode,
            model=task.model,
            prompt_version=task.prompt_version,
            outcome=outcome,
            attempts=len(replies),
            usage=usage,
            cost_micro_usd=cost_micro_usd(usage, price),
            latency_ms=round((clock() - started) * 1000),
            error=error,
            raw_replies=tuple(replies),
        )

    last_error = ""
    for attempt in (1, 2):
        try:
            reply = client.call(
                model=task.model,
                system=system,
                turns=turns,
                json_schema=json_schema,
                max_tokens=task.max_tokens,
                effort=task.effort,
            )
        except anthropic.APIError as exc:
            # The SDK already retried rate limits, overloads and connection errors.
            return GatewayResult(None, record("error", f"{type(exc).__name__}: {exc}"[:500]))
        usage = usage + reply.usage
        replies.append(reply.text)

        if reply.stop_reason == "refusal":
            return GatewayResult(None, record("refused"))
        if reply.stop_reason == "max_tokens" or reply.text is None:
            last_error = f"- reply incomplete (stop_reason={reply.stop_reason})"
        else:
            try:
                value = schema.model_validate_json(reply.text, context=context)
            except (ValidationError, ValueError) as exc:
                last_error = _short(exc)
            else:
                return GatewayResult(value, record("valid" if attempt == 1 else "repaired"))
        if attempt == 1:
            turns += [
                Turn("assistant", reply.text or ""),
                Turn("user", _repair_message(last_error)),
            ]
    return GatewayResult(None, record("invalid", last_error[:500]))


# --- Clients --------------------------------------------------------------------------------


class AnthropicClient:
    """The live client. Credentials come from the environment (ANTHROPIC_API_KEY) as the SDK
    resolves them; nothing secret passes through our code."""

    def __init__(self, sdk: anthropic.Anthropic | None = None) -> None:
        self._sdk = sdk or anthropic.Anthropic()

    def call(
        self,
        *,
        model: str,
        system: str,
        turns: list[Turn],
        json_schema: dict[str, Any],
        max_tokens: int,
        effort: Effort,
    ) -> ModelReply:
        # The instructions are identical for every request, so they are cached.
        system_blocks: list[TextBlockParam] = [
            {"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}
        ]
        messages: list[MessageParam] = [
            UserMessageParam(role="user", content=t.content)
            if t.role == "user"
            else AssistantMessageParam(role="assistant", content=t.content)
            for t in turns
        ]
        output_config: OutputConfigParam = {
            "effort": effort,
            "format": {"type": "json_schema", "schema": json_schema},
        }
        response = self._sdk.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system_blocks,
            messages=messages,
            output_config=output_config,
        )
        text = next((b.text for b in response.content if b.type == "text"), None)
        u = response.usage
        return ModelReply(
            text=text,
            stop_reason=response.stop_reason,
            usage=TokenUsage(
                input_tokens=u.input_tokens,
                output_tokens=u.output_tokens,
                cache_read_tokens=u.cache_read_input_tokens or 0,
                cache_write_tokens=u.cache_creation_input_tokens or 0,
            ),
        )


class ScriptedClient:
    """A stand-in that returns prepared replies, for tests and for AI_MODE=fake."""

    def __init__(self, reply: Callable[[list[Turn]], ModelReply]) -> None:
        self._reply = reply
        self.calls: list[list[Turn]] = []

    def call(
        self,
        *,
        model: str,
        system: str,
        turns: list[Turn],
        json_schema: dict[str, Any],
        max_tokens: int,
        effort: Effort,
    ) -> ModelReply:
        self.calls.append(list(turns))
        return self._reply(turns)
