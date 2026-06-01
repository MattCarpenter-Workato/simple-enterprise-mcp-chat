"""
Provider registry.

Maps the four provider names to a configured Provider instance, reading API keys,
base URLs, and model names from the SQLite secrets table (db.py) rather than
environment variables. OpenAI, Ollama, and LM Studio all use the OpenAI-compatible
provider; Claude has its own.
"""

from typing import Any

import db
from .base import Provider
from .claude import ClaudeProvider
from .openai_like import OpenAILikeProvider

# Provider catalog: display name -> default model + the secret key holding the
# user's chosen model. `kind` selects the implementation.
PROVIDERS: dict[str, dict[str, Any]] = {
    "OpenAI": {
        "kind": "openai",
        "model_key": "OPENAI_MODEL",
        "default_model": "gpt-4o-mini",
        "models": ["gpt-4o-mini", "gpt-4o", "gpt-4-turbo", "gpt-3.5-turbo"],
    },
    "Claude": {
        "kind": "claude",
        "model_key": "CLAUDE_MODEL",
        "default_model": "claude-sonnet-4-5-20250929",
        "models": ["claude-sonnet-4-5-20250929", "claude-opus-4-1-20250805", "claude-3-5-haiku-20241022"],
    },
    "Ollama": {
        "kind": "openai",
        "model_key": "OLLAMA_MODEL",
        "default_model": "llama3.2",
        "models": ["llama3.2", "mistral", "qwen3:8b", "qwen2.5"],
    },
    "LM Studio": {
        "kind": "openai",
        "model_key": "LMSTUDIO_MODEL",
        "default_model": "local-model",
        "models": ["local-model"],
    },
}

PROVIDER_NAMES = list(PROVIDERS.keys())


def default_model(name: str) -> str:
    """The user's configured model for a provider, or its built-in default."""
    spec = PROVIDERS[name]
    return db.get_secret(spec["model_key"]) or spec["default_model"]


def model_options(name: str) -> list[str]:
    """Suggested models for a provider, including any user-configured one."""
    opts = list(PROVIDERS[name]["models"])
    chosen = db.get_secret(PROVIDERS[name]["model_key"])
    if chosen and chosen not in opts:
        opts.insert(0, chosen)
    return opts


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
