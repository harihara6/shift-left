"""Where Feature Kickoff's AI step runs, and which models it may run on.

Providers are pluggable behind one shape. The model list always comes from the provider itself,
at request time, so the picker offers what the account can actually use today and never a
hardcoded id that might not exist.

* **claude**: the Anthropic API, the same key guided setup uses. Models from `GET /v1/models`.
* **cursor**: models from Cursor's `GET /v1/models`, with the team's API key. Listed, never run
  here: Cursor's API launches agents on repositories and has no call that answers a prompt, so
  its models run in the editor. The picker shows them so nobody wonders where they went.
* **rules**: no model. The keyword reader. Always available, and the fallback whenever a model
  call fails, so the flow degrades rather than disappears.

Being unavailable is an expected state, not an error (the same stance as the Rovo connector).
"""

import logging
import time
from dataclasses import dataclass, field

from app.connectors import http
from app.core.config import get_settings

logger = logging.getLogger("shiftleft.kickoff")

RULES_MODEL = "rules"
CURSOR_API = "https://api.cursor.com"
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


async def _cursor_models(api_key: str) -> tuple[list[ModelOption], str]:
    cached = _cache.get("cursor")
    if cached and time.monotonic() - cached[0] < MODEL_LIST_TTL_SECONDS:
        return cached[1], cached[2]
    try:
        async with http.client(timeout=10.0) as c:
            response = await c.get(f"{CURSOR_API}/v1/models", auth=(api_key, ""))
        response.raise_for_status()
        items = response.json().get("items", [])
        models = [ModelOption(id=str(i["id"]), display_name=str(i.get("displayName") or i["id"]))
                  for i in items if isinstance(i, dict) and i.get("id")][:MODEL_LIST_LIMIT]
        note = (
            f"Connected: {len(models)} model(s) on the team's Cursor account. They run in the editor, "
            "not here: Cursor's API launches agents on repositories and can't answer a prompt directly."
        )
    except Exception as exc:  # a list that can't be fetched says so; it never invents one
        logger.warning("Could not list Cursor models: %s", type(exc).__name__)
        models, note = [], f"Couldn't list Cursor's models just now ({type(exc).__name__})."
    _cache["cursor"] = (time.monotonic(), models, note)
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

    if settings.cursor_api_key:
        models, note = await _cursor_models(settings.cursor_api_key.get_secret_value())
        out.append(Provider("cursor", "Cursor", False, note, models))
    else:
        out.append(Provider(
            "cursor", "Cursor", False,
            "Not connected. Set SHIFTLEFT_CURSOR_API_KEY to list the models on the team's Cursor account.",
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
