"""Where Feature Kickoff's AI step runs, and which models it may run on.

Providers are pluggable behind one shape. The model list always comes from the provider itself,
at request time, so the picker offers what the account can actually use today and never a
hardcoded id that might not exist.

* **claude**: the Anthropic API, the same key guided setup uses. Models from `GET /v1/models`.
* **cursor**: the team's Cursor plan, through the Cursor CLI on the machine running ShiftLeft
  (`cursor_cli`). Models from `agent models`. For when there's a Cursor seat but no Anthropic key.
* **rules**: no model. The keyword reader. Always available, and the fallback whenever a model
  call fails, so the flow degrades rather than disappears.

Being unavailable is an expected state, not an error (the same stance as the Rovo connector).
"""

import logging
import time
from dataclasses import dataclass, field

from app.core.config import get_settings
from app.services import cursor_cli

logger = logging.getLogger("shiftleft.kickoff")

RULES_MODEL = "rules"
AI_PROVIDERS = ("claude", "cursor")
# A person is waiting on the picker. The list is re-fetched at most this often per process.
MODEL_LIST_TTL_SECONDS = 300
MODEL_LIST_LIMIT = 50


@dataclass
class ModelOption:
    id: str
    display_name: str


@dataclass
class Provider:
    key: str
    name: str
    available: bool
    note: str
    models: list[ModelOption] = field(default_factory=list)
    default_model: str = ""


_cache: dict[str, tuple[float, list[ModelOption], str]] = {}


async def _claude_models(api_key: str, default_model: str) -> tuple[list[ModelOption], str]:
    cached = _cache.get("claude")
    if cached and time.monotonic() - cached[0] < MODEL_LIST_TTL_SECONDS:
        return cached[1], cached[2]

    import anthropic

    client = anthropic.AsyncAnthropic(api_key=api_key, timeout=10.0, max_retries=1)
    models: list[ModelOption] = []
    try:
        async for model in client.models.list():
            models.append(ModelOption(id=model.id, display_name=model.display_name))
            if len(models) >= MODEL_LIST_LIMIT:
                break
        note = f"{len(models)} model(s) available to this API key."
    except Exception as exc:  # the picker still works with the configured default
        logger.warning("Could not list Claude models: %s", exc)
        models = [ModelOption(id=default_model, display_name=default_model)]
        note = "Couldn't list models just now, so only the configured default is offered."
    _cache["claude"] = (time.monotonic(), models, note)
    return models, note


async def providers() -> list[Provider]:
    settings = get_settings()
    out: list[Provider] = []

    if settings.anthropic_api_key:
        try:
            models, note = await _claude_models(settings.anthropic_api_key, settings.anthropic_model)
            available = True
        except ImportError:
            models, note, available = [], (
                "The Anthropic SDK isn't installed (pip install -e \"backend[ai]\")."
            ), False
        default = (
            settings.anthropic_model
            if any(m.id == settings.anthropic_model for m in models)
            else (models[0].id if models else "")
        )
        out.append(Provider("claude", "Claude (Anthropic API)", available, note, models, default))
    else:
        out.append(Provider(
            "claude", "Claude (Anthropic API)", False,
            "Not configured. Set SHIFTLEFT_ANTHROPIC_API_KEY to read PRDs with Claude.",
        ))

    cursor = await cursor_cli.status()
    out.append(Provider(
        "cursor", "Cursor (your Cursor plan)", cursor.available, cursor.note,
        [ModelOption(model_id, name) for model_id, name in cursor.models], cursor.default_model,
    ))
    out.append(Provider(
        "rules", "No model", True,
        "Keyword reader. Always available; every fact still needs a quote from the PRD.",
        [ModelOption(RULES_MODEL, "Rule-based reader (no AI)")], RULES_MODEL,
    ))
    return out


async def choose(provider_key: str, model: str) -> tuple[Provider, str] | str:
    """The provider and model to run, or the reason they can't be used."""
    for provider in await providers():
        if provider.key != provider_key:
            continue
        if not provider.available:
            return f"{provider.name} isn't available: {provider.note}"
        if not any(m.id == model for m in provider.models):
            return f"{model!r} isn't offered by {provider.name}. Pick one from the list."
        return provider, model
    return f"Unknown model provider {provider_key!r}."


async def default_ai() -> tuple[str, str] | None:
    """The provider and model for the AI steps that have no picker, or None for rules.

    Claude when a key is set, as before; otherwise Cursor when its CLI is signed in.
    """
    settings = get_settings()
    if settings.anthropic_api_key:
        return "claude", settings.anthropic_model
    cursor = await cursor_cli.status()
    if cursor.available and cursor.default_model:
        return "cursor", cursor.default_model
    return None
