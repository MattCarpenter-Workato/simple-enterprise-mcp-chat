"""
Shared helpers for the Streamlit pages.

Keeps one-time setup (DB seeding) and message-rendering logic in one place so the
Chat page and the sub-pages stay small.
"""

from datetime import datetime
from typing import Any, Optional

import streamlit as st

import db
from logging_setup import configure_logging


@st.cache_resource
def init_app() -> bool:
    """Run once per server process: create schema, import legacy file config, and
    set up app-level file logging."""
    db.seed_from_files_if_empty()
    configure_logging(db.get_secret("APP_LOG_LEVEL", "INFO"))
    return True


def display_text(message: dict[str, Any]) -> Optional[tuple[str, str]]:
    """Reduce a stored (provider-native) message to (role, text) for display, or
    None if it's tool plumbing with nothing user-facing to show.

    Handles both OpenAI-style (string content, tool_calls) and Claude-style
    (list-of-blocks content) messages.
    """
    role = message.get("role")
    content = message.get("content")

    if role not in ("user", "assistant"):
        return None  # tool / system messages are plumbing

    # Claude-style list of content blocks
    if isinstance(content, list):
        texts = [b.get("text", "") for b in content
                 if isinstance(b, dict) and b.get("type") == "text"]
        text = "\n".join(t for t in texts if t).strip()
        return (role, text) if text else None

    # OpenAI-style: assistant turn that only requested tools has no text
    if isinstance(content, str):
        text = content.strip()
        return (role, text) if text else None

    return None


def render_history(messages: list[dict[str, Any]]) -> None:
    """Render the visible chat history."""
    for msg in messages:
        shown = display_text(msg)
        if shown:
            role, text = shown
            with st.chat_message(role):
                st.markdown(text)


def effective_system_prompt(system_prompt: str, inject_date: bool) -> str:
    """Optionally append a current date/time line, mirroring the CLI's
    INJECT_CURRENT_DATE behavior but via the system prompt (keeps chat bubbles
    clean and works for every provider)."""
    if not inject_date:
        return system_prompt
    now = datetime.now()
    date_line = (f"The current date and time is {now:%Y-%m-%d %H:%M:%S} "
                 f"(ISO: {now:%Y-%m-%dT%H:%M:%S}).")
    return f"{system_prompt}\n\n{date_line}".strip() if system_prompt else date_line
