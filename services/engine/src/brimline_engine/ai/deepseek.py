"""DeepSeek client: the OpenAI-format chat completions API in JSON output mode.

DeepSeek's JSON mode guarantees a JSON object, not a particular schema, so the schema is written
into the system prompt and the gateway validates every reply with our pydantic model anyway
(hard rule 2). Docs read 2026-10-26: api-docs.deepseek.com (JSON mode, create chat completion).
"""

import json
import time
from collections.abc import Callable
from typing import Any

import httpx2

from brimline_engine.ai.config import Effort
from brimline_engine.ai.gateway import ModelReply, ModelUnavailableError, TokenUsage, Turn

# Our effort levels -> DeepSeek's reasoning_effort (none, low, high, max).
_EFFORT = {"low": "low", "medium": "high", "high": "high", "xhigh": "max", "max": "max"}

# DeepSeek finish_reason -> the gateway's stop reasons.
_STOP = {"stop": "end_turn", "length": "max_tokens", "content_filter": "refusal"}

# Statuses worth one more try: rate limits and passing server trouble.
_RETRY = {429, 500, 502, 503}


def system_with_schema(system: str, json_schema: dict[str, Any]) -> str:
    # JSON mode requires the prompt to mention JSON and show the expected shape.
    return (
        f"{system}\n"
        "Reply with one JSON object and nothing else. It must match this JSON Schema exactly "
        "(every property present, null where the schema allows it):\n"
        f"{json.dumps(json_schema, sort_keys=True)}"
    )


class DeepSeekClient:
    def __init__(
        self,
        *,
        api_key: str | None,
        base_url: str,
        http: httpx2.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._api_key = api_key
        self._url = f"{base_url.rstrip('/')}/chat/completions"
        self._http = http  # injected in tests; otherwise one short-lived client per call
        self._sleep = sleep

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
        if not self._api_key:
            raise ModelUnavailableError("DEEPSEEK_API_KEY is not set")
        body = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_with_schema(system, json_schema)},
                *({"role": t.role, "content": t.content} for t in turns),
            ],
            "response_format": {"type": "json_object"},
            "reasoning_effort": _EFFORT[effort],
            "max_tokens": max_tokens,
        }
        headers = {"Authorization": f"Bearer {self._api_key}"}
        if self._http is not None:
            return self._send(self._http, body, headers)
        # A client per call, closed afterwards, so no connections are left open.
        with httpx2.Client(timeout=120.0) as http:
            return self._send(http, body, headers)

    def _send(
        self, http: httpx2.Client, body: dict[str, Any], headers: dict[str, str]
    ) -> ModelReply:
        for attempt in range(3):
            try:
                response = http.post(self._url, json=body, headers=headers)
            except httpx2.HTTPError as exc:
                if attempt == 2:
                    raise ModelUnavailableError(
                        f"DeepSeek unreachable: {type(exc).__name__}"
                    ) from exc
                self._sleep(2**attempt)
                continue
            if response.status_code in _RETRY and attempt < 2:
                self._sleep(2**attempt)
                continue
            break
        if response.status_code != 200:
            # The body explains the error; it never contains our key.
            raise ModelUnavailableError(
                f"DeepSeek HTTP {response.status_code}: {response.text[:300]}"
            )

        data = response.json()
        choice = data["choices"][0]
        content = choice["message"].get("content") or None  # empty content does happen
        usage = data.get("usage", {})
        return ModelReply(
            text=content,
            stop_reason=_STOP.get(choice.get("finish_reason"), choice.get("finish_reason")),
            usage=TokenUsage(
                input_tokens=usage.get("prompt_cache_miss_tokens", usage.get("prompt_tokens", 0)),
                output_tokens=usage.get("completion_tokens", 0),  # includes reasoning tokens
                cache_read_tokens=usage.get("prompt_cache_hit_tokens", 0),
                cache_write_tokens=0,
            ),
        )
