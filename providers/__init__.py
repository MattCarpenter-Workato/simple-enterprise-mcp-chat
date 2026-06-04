"""
Provider registry.

Maps the four provider names to a configured Provider instance, reading API keys,
base URLs, and model names from the SQLite secrets table (db.py) rather than
environment variables. OpenAI, Ollama, and LM Studio all use the OpenAI-compatible
provider; Claude has its own.
"""

import logging
import re
from typing import Any, Optional

import db
from .base import Provider
from .claude import ClaudeProvider
from .openai_like import OpenAILikeProvider

logger = logging.getLogger("mcpchat.providers")

# Provider catalog: display name -> default model + the secret key holding the
# user's chosen model. `kind` selects the implementation. `live` providers fetch
# their model list from the API (see fetch_models); the others use `models` as-is.
PROVIDERS: dict[str, dict[str, Any]] = {
    "OpenAI": {
        "kind": "openai",
        "model_key": "OPENAI_MODEL",
        "default_model": "gpt-4o-mini",
        "models": ["gpt-4o-mini", "gpt-4o", "gpt-4-turbo", "gpt-3.5-turbo"],
        "live": True,
    },
    "Claude": {
        "kind": "claude",
        "model_key": "CLAUDE_MODEL",
        "default_model": "claude-sonnet-4-5-20250929",
        "models": ["claude-sonnet-4-5-20250929", "claude-opus-4-1-20250805", "claude-3-5-haiku-20241022"],
        "live": True,
    },
    "Ollama": {
        "kind": "openai",
        "model_key": "OLLAMA_MODEL",
        "default_model": "llama3.2",
        "models": ["llama3.2", "mistral", "qwen3:8b", "qwen2.5"],  # static fallback
        "live": True,
        "local": True,  # no API key, no per-model pricing gate
    },
    "LM Studio": {
        "kind": "openai",
        "model_key": "LMSTUDIO_MODEL",
        "default_model": "local-model",
        "models": ["local-model"],
        "local": True,
    },
}

PROVIDER_NAMES = list(PROVIDERS.keys())


def default_model(name: str) -> str:
    """The user's configured model for a provider, or its built-in default."""
    spec = PROVIDERS[name]
    return db.get_secret(spec["model_key"]) or spec["default_model"]


def model_options(name: str) -> list[str]:
    """Suggested models for a provider, including any user-configured one.

    This is the static fallback list (catalog + the user's configured default),
    used when live fetching is off or fails. See fetch_models for the live list."""
    opts = list(PROVIDERS[name]["models"])
    chosen = db.get_secret(PROVIDERS[name]["model_key"])
    if chosen and chosen not in opts:
        opts.insert(0, chosen)
    return opts


# OpenAI's /v1/models returns far more than chat models. Keep ids that look like a
# chat completion model and drop the audio/image/embedding/etc. variants.
_OPENAI_ALLOW_PREFIXES = ("gpt-", "o1", "o3", "o4", "chatgpt")
_OPENAI_DENY_SUBSTRINGS = (
    "instruct", "audio", "realtime", "transcribe", "tts", "image",
    "embedding", "moderation", "search", "dall-e", "whisper",
)


# Dated snapshot suffix, e.g. "gpt-4o-2024-08-06" or "gpt-5-2025-08-07". OpenAI also
# exposes an undated rolling alias for each (e.g. "gpt-4o"), so we hide the snapshots
# to keep the dropdown short. (Claude uses a different "-YYYYMMDD" form and several of
# its models only exist dated, so this is intentionally OpenAI-only.)
_OPENAI_SNAPSHOT_RE = re.compile(r"-\d{4}-\d{2}-\d{2}$")


def _is_openai_chat_model(mid: str) -> bool:
    m = mid.lower()
    if not m.startswith(_OPENAI_ALLOW_PREFIXES):
        return False
    if _OPENAI_SNAPSHOT_RE.search(m):
        return False
    return not any(bad in m for bad in _OPENAI_DENY_SUBSTRINGS)


def fetch_models(name: str) -> Optional[list[str]]:
    """Live-fetch the model list from the provider's API for `live` providers.

    Returns a sorted list of model ids, or None when the provider isn't live, has
    no key configured, or the call fails — callers fall back to model_options().
    Reuses get_provider() so the API key/base URL resolution stays in one place."""
    spec = PROVIDERS.get(name)
    if not spec or not spec.get("live"):
        return None
    try:
        client = get_provider(name).client  # raises ValueError if the key is missing
        if spec.get("local"):  # Ollama: keep every installed *chat* model (no gpt-*
            # filter), but drop embedding models — they speak a different endpoint and
            # would 404 on a chat turn. Ollama's /v1/models doesn't tag model type.
            ids = [m.id for m in client.models.list().data if "embed" not in m.id.lower()]
        elif spec["kind"] == "claude":
            ids = [m.id for m in client.models.list(limit=100).data
                   if m.id.startswith("claude")]
        else:  # openai
            ids = [m.id for m in client.models.list().data
                   if _is_openai_chat_model(m.id)]
        return sorted(set(ids)) or None
    except Exception as e:  # noqa: BLE001 — any failure falls back to the static list
        logger.info("Live model fetch failed for %s: %s", name, e)
        return None


def ping(name: str) -> Optional[str]:
    """Liveness probe: None if the provider's endpoint is reachable, else a short
    error string. Intended for local providers (Ollama/LM Studio) so the UI can
    show 'service running?' without waiting for a chat turn to fail. Deliberately
    uncached — callers want the current state, not the 1h-cached model list."""
    try:
        get_provider(name).client.models.list()
        return None
    except Exception as e:  # noqa: BLE001 — any failure means "not reachable"
        return str(e)


def _ollama_base_url() -> str:
    base = (db.get_secret("OLLAMA_BASE_URL") or "http://localhost:11434").rstrip("/")
    if not base.endswith("/v1"):
        base += "/v1"
    return base


def get_provider(name: str) -> Provider:
    """Construct a configured Provider instance for the given name.

    Raises ValueError with a user-facing message when required config is missing.
    """
    if name not in PROVIDERS:
        raise ValueError(f"Unknown provider: {name}")

    if name == "OpenAI":
        key = db.get_secret("OPENAI_API_KEY")
        if not key:
            raise ValueError("OPENAI_API_KEY is not set. Add it on the Settings page.")
        return OpenAILikeProvider("OpenAI", api_key=key)

    if name == "Claude":
        key = db.get_secret("CLAUDE_API_KEY")
        if not key:
            raise ValueError("CLAUDE_API_KEY is not set. Add it on the Settings page.")
        return ClaudeProvider(api_key=key)

    if name == "Ollama":
        return OpenAILikeProvider("Ollama", api_key="ollama", base_url=_ollama_base_url())

    if name == "LM Studio":
        base = (db.get_secret("LMSTUDIO_BASE_URL") or "http://localhost:1234/v1").rstrip("/")
        if not base.endswith("/v1"):
            base += "/v1"
        return OpenAILikeProvider("LM Studio", api_key="lm-studio", base_url=base)

    raise ValueError(f"Unhandled provider: {name}")
