"""Which model client to use, from AI_MODE:

live  the real API of the model's provider in config/models.toml
      (DeepSeek: DEEPSEEK_API_KEY; Claude: ANTHROPIC_API_KEY or another credential the SDK finds)
fake  prepared replies, for tests and browser tests: deterministic and free
off   no model at all: quotes start empty and staff fill them in
"""

import json
from typing import Any

from brimline_engine.ai.config import models_config
from brimline_engine.ai.deepseek import DeepSeekClient
from brimline_engine.ai.gateway import (
    AnthropicClient,
    ModelClient,
    ModelReply,
    ScriptedClient,
    TokenUsage,
    Turn,
)
from brimline_engine.settings import get_settings


def _draft(**overrides: object) -> str:
    draft: dict[str, Any] = {
        "lines": [],
        "due": {
            "kind": "none",
            "year": None,
            "month": None,
            "day": None,
            "weekday": None,
            "count": None,
        },
        "rush_requested": False,
        "notes_for_shop": "",
        "missing": ["part", "quantity", "material", "due_date"],
        "questions_for_customer": [
            "What would you like us to make, how many, and in which material?"
        ],
        "requests_for_staff": [],
        "language": "en",
    }
    draft.update(overrides)
    return json.dumps(draft)


_PHONE_STANDS = _draft(
    lines=[
        {
            "part_description": "Phone stand",
            "quantity": 20,
            "material_code": "PETG-BLACK",
            "material_as_written": "black PETG",
            "post_processing": [],
            "uncertain": [],
        }
    ],
    due={
        "kind": "next_weekday",
        "year": None,
        "month": None,
        "day": None,
        "weekday": "friday",
        "count": None,
    },
    missing=[],
    questions_for_customer=[],
)


def fake_reply(turns: list[Turn]) -> ModelReply:
    """A tiny stand-in for the model. It only recognises the phrases the tests use."""
    message = turns[0].content.lower()
    if "phone stand" in message:
        text = _PHONE_STANDS
    elif "fake-invalid" in message:
        text = '{"lines": "not a list"}'
    else:
        text = _draft()
    return ModelReply(text=text, stop_reason="end_turn", usage=TokenUsage())


def client_for(mode: str, model: str) -> ModelClient | None:
    """The client for `model` in this mode, or None when AI is off."""
    if mode == "fake":
        return ScriptedClient(fake_reply)
    if mode != "live":
        return None
    cfg = models_config()
    provider = cfg.prices[model].provider
    if provider == "deepseek":
        key = get_settings().deepseek_api_key
        return DeepSeekClient(
            api_key=key.get_secret_value() if key else None,
            base_url=cfg.providers["deepseek"].base_url,
        )
    return AnthropicClient()
