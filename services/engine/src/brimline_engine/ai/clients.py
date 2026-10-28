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
from brimline_engine.ai.guard import GuardedClient, RecordingClient, ReplayClient, demo_config
from brimline_engine.settings import REPO_ROOT, get_settings


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


def _fake_event(type_: str, **fields: object) -> dict[str, object]:
    base: dict[str, object] = {
        "type": type_,
        "machine": None,
        "material": None,
        "order": None,
        "line": None,
        "from_phrase": None,
        "until_phrase": None,
    }
    return base | fields


def _fake_disruption(message: str) -> str:
    """Prepared readings of the disruption messages the tests and browser tests send."""
    events: list[dict[str, object]] = []
    unclear, injection = False, "ignore" in message
    if "printer 3 jammed until 5pm" in message:
        events.append(_fake_event("machine_down", machine="FDM-3", until_phrase="5pm"))
    elif "resin printer is down until 12/11" in message:
        events.append(_fake_event("machine_down", machine="RESIN-1", until_phrase="12/11"))
    elif "cancel bl-0005 and bl-0006" in message:
        events += [
            _fake_event("cancellation", order="BL-0005"),
            _fake_event("cancellation", order="BL-0006"),
        ]
    elif "needs another 2 hours" in message:
        events.append(_fake_event("print_overrun", machine="RESIN-1", until_phrase="in 2 hours"))
    elif "bl-0007 is a rush" in message:
        events.append(_fake_event("rush_job", order="BL-0007"))
    else:
        unclear = True
    return json.dumps(
        {
            "events": events,
            "unclear": unclear,
            "unclear_reason": "no disruption I can read" if unclear else "",
            "question_for_planner": "What happened, and to which machine?" if unclear else "",
            "injection_suspected": injection,
        }
    )


def _fake_summary(diff_text: str) -> str:
    """A grounded summary built only from the diff's own numbers (or, on request, one that
    mentions an order the diff does not contain, to test the grounding check)."""
    diff = json.loads(diff_text)
    if "fake-ungrounded" in diff_text:
        return json.dumps({"summary": "BL-9999 moved to FDM-9.", "highlights": []})
    totals = diff["totals"]
    return json.dumps(
        {
            "summary": f"{totals['jobs_moved']} jobs move; late jobs go from "
            f"{totals['late_before']} to {totals['late_after']}.",
            "highlights": [],
        }
    )


def _fake_search(question: str) -> str:
    """Prepared readings of the search questions the tests send."""
    reply: dict[str, object] = {
        "unclear": False,
        "unclear_reason": "",
        "conditions": [],
        "due": None,
        "sort": "due_date",
        "injection_suspected": "ignore" in question,
    }
    if "due this week not printed" in question:
        reply["conditions"] = [{"field": "printed", "op": "is", "values": ["false"]}]
        reply["due"] = {"op": "between", "rule": "this_week", "phrase": None, "phrase_to": None}
    elif "willow" in question:
        reply["conditions"] = [{"field": "customer", "op": "in", "values": ["C-WILLOW"]}]
    elif "due 12/11" in question:
        reply["due"] = {"op": "on", "rule": "phrase", "phrase": "12/11", "phrase_to": None}
    elif "drop table" in question:
        reply["conditions"] = [
            {"field": "part_name", "op": "contains", "values": ["'; DROP TABLE jobs; --"]}
        ]
    elif "everything" in question:
        reply["unclear"] = True
        reply["unclear_reason"] = (
            "Willow Street Dental Lab has secret orders"  # must never be shown
        )
    else:
        reply["unclear"] = True
        reply["unclear_reason"] = "not a search I can read"
    return json.dumps(reply)


def fake_reply(turns: list[Turn]) -> ModelReply:
    """A tiny stand-in for the model. It only recognises the phrases the tests use."""
    content = turns[0].content
    message = content.lower()
    if "<planner_message>" in message:
        text = _fake_disruption(message)
        return ModelReply(text=text, stop_reason="end_turn", usage=TokenUsage())
    if content.startswith("<question>"):
        return ModelReply(text=_fake_search(message), stop_reason="end_turn", usage=TokenUsage())
    if content.startswith("<file_checks>"):
        advice = {"advice": ["Print it on its largest flat face to avoid supports."]}
        return ModelReply(text=json.dumps(advice), stop_reason="end_turn", usage=TokenUsage())
    if content.startswith("<plan_diff>"):
        inner = content.removeprefix("<plan_diff>").rsplit("</plan_diff>", 1)[0]
        return ModelReply(text=_fake_summary(inner), stop_reason="end_turn", usage=TokenUsage())
    if "phone stand" in message:
        text = _PHONE_STANDS
    elif "fake-invalid" in message:
        text = '{"lines": "not a list"}'
    else:
        text = _draft()
    return ModelReply(text=text, stop_reason="end_turn", usage=TokenUsage())


def _live(model: str) -> ModelClient:
    cfg = models_config()
    provider = cfg.prices[model].provider
    if provider == "deepseek":
        key = get_settings().deepseek_api_key
        return DeepSeekClient(
            api_key=key.get_secret_value() if key else None,
            base_url=cfg.providers["deepseek"].base_url,
        )
    return AnthropicClient()


def client_for(mode: str, model: str) -> ModelClient | None:
    """The client for `model` in this mode, or None when AI is off. In demo mode a live client
    is guarded by the spending limits (ai/guard.py) and falls back to recorded replies."""
    if mode == "fake":
        return ScriptedClient(fake_reply)
    recording = REPO_ROOT / demo_config().recording.path
    if mode == "replay":
        return ReplayClient(recording)
    if mode == "record":
        return RecordingClient(_live(model), recording)
    if mode != "live":
        return None
    settings = get_settings()
    if settings.demo_mode:
        return GuardedClient(
            _live(model), ReplayClient(recording), settings.database_url, demo_config().budget
        )
    return _live(model)
