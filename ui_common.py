"""
Shared helpers for the Streamlit pages.

Keeps one-time setup (DB seeding) and message-rendering logic in one place so the
Chat page and the sub-pages stay small.
"""

import json
from datetime import datetime
from typing import Any, Optional

import streamlit as st

import db
import providers
from logging_setup import configure_logging
from mcp_core import MCPClient


@st.cache_resource
def init_app() -> bool:
    """Run once per server process: create schema, import legacy file config, and
    set up app-level file logging."""
    db.seed_from_files_if_empty()
    configure_logging(db.get_secret("APP_LOG_LEVEL", "INFO"))
    return True


@st.cache_resource
def get_client_and_tools(signature: str):
    """Build an MCP client and discover tools. Cached across reruns and shared by
    the Chat and Benchmark pages; the `signature` (from server_signature) busts the
    cache when server config or a token changes. Returns (client, tools, errors)."""
    client = MCPClient()
    tools = client.discover_tools()
    return client, tools, dict(client.errors)


def model_fingerprint(name: str) -> str:
    """Non-secret fingerprint of the provider's API key, so the cached model list
    busts when the key changes. Empty for non-live providers (no key involved)."""
    spec = providers.PROVIDERS.get(name) or {}
    if not spec.get("live"):
        return ""
    if spec.get("local"):
        # Keyless local provider (Ollama/LM Studio): bust the cache when its host
        # changes, keyed off that provider's own base-URL secret.
        return (db.get_secret(spec["base_url_key"]) or "")[-12:]
    key_secret = "OPENAI_API_KEY" if spec["kind"] == "openai" else "CLAUDE_API_KEY"
    return (db.get_secret(key_secret) or "")[-8:]


@st.cache_data(ttl=3600, show_spinner=False)
def available_models(name: str, fingerprint: str) -> list[str]:
    """Model dropdown options for a provider: the live API list when available,
    else the static fallback. `fingerprint` only participates in the cache key
    (busts on key change) — it is otherwise unused. Clear this cache to refresh."""
    live = providers.fetch_models(name)
    if not live:
        return providers.model_options(name)
    # Local providers (Ollama): the discovered list is authoritative — a model that
    # isn't installed can't run, so don't inject the configured default if it's
    # absent (it would just 404 on the first turn). Paid providers keep their custom
    # model visible since an arbitrary id may still be a valid API model.
    if (providers.PROVIDERS.get(name) or {}).get("local"):
        return live
    chosen = db.get_secret(providers.PROVIDERS[name]["model_key"])
    if chosen and chosen not in live:
        live = [chosen] + live
    return live


def selectable_models(provider: str) -> list[str]:
    """Models to offer in a picker for `provider`. Local providers (no cost concept)
    show everything. Paid/live providers (Claude, OpenAI) show only models that have
    a price; any model with no price at all is parked in the pricing table (so it
    appears in Settings → Model pricing) and hidden until the user gives it a cost.
    Not cached: it writes placeholder rows and must reflect pricing edits live."""
    models = available_models(provider, model_fingerprint(provider))
    spec = providers.PROVIDERS.get(provider) or {}
    if not spec.get("live") or spec.get("local"):
        return list(models)
    out = []
    for m in models:
        if db.is_priced(provider, m):
            out.append(m)
        else:
            db.ensure_model_listed(provider, m)
    return out


def server_signature() -> str:
    """Cache key for discovery. Includes a per-server token fingerprint so that
    (re)authenticating or refreshing a token busts the cache and re-discovers —
    otherwise a stale 'not authenticated' result would persist after re-auth."""
    parts = []
    for s in db.list_servers(enabled_only=True):
        fp = ""
        if s["auth_type"] == "oauth":
            tok = (db.get_oauth_token(s["name"]) or {}).get("access_token") or ""
            fp = tok[-12:]  # changes on re-auth/refresh, not the full secret
        parts.append(f"{s['name']}:{s['url']}:{s['auth_type']}:{fp}")
    return "|".join(parts)


# Sidebar pages: (script path, label, icon). The entry script (app.py) is shown as
# "Home". We hide Streamlit's auto nav (which would label the entry "app") and
# render these custom links instead.
_NAV_PAGES = [
    ("app.py", "Home", "💬"),
    ("pages/5_Benchmark.py", "Benchmark", "⚗️"),
    ("pages/1_MCP_Servers.py", "MCP Servers", "🔌"),
    ("pages/2_System_Prompts.py", "System Prompts", "📝"),
    ("pages/3_Settings.py", "Settings", "⚙️"),
    ("pages/4_Logs.py", "Logs", "📊"),
]


def render_nav() -> None:
    """Render the sidebar navigation with custom labels (call near the top of each
    page). Replaces the default auto-generated nav so the entry page reads 'Home'."""
    st.markdown(
        "<style>[data-testid='stSidebarNav']{display:none;}</style>",
        unsafe_allow_html=True,
    )
    with st.sidebar:
        for path, label, icon in _NAV_PAGES:
            st.page_link(path, label=label, icon=icon)
        st.divider()


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


def copy_button(text: str, label: str = "📋 Copy to clipboard",
                height: int = 46, key: str = "copy") -> None:
    """Render a button that copies `text` to the user's clipboard in the browser.

    Uses a temp-textarea + document.execCommand('copy') inside the component iframe
    (navigator.clipboard is usually blocked there). Works for web/Docker since the
    copy happens client-side. `text` is embedded as a safe JS string literal."""
    payload = json.dumps(text)  # safe JS string literal (quotes/newlines/unicode)
    btn_id = f"copybtn_{key}"
    # st.iframe renders the HTML in a sandboxed iframe, so the <script> runs (unlike
    # st.html, which strips scripts). Replaces the deprecated components.v1.html.
    html = (
        f'<button id="{btn_id}" style="'
        "width:100%; padding:8px 12px; cursor:pointer; border-radius:8px;"
        "border:1px solid rgba(49,51,63,0.2); background:#fff; color:#262730;"
        f'font-size:14px; font-weight:600;">{label}</button>'
        "<script>"
        f"const data = {payload};"
        f'const btn = document.getElementById("{btn_id}");'
        'btn.addEventListener("click", () => {'
        '  const ta = document.createElement("textarea");'
        "  ta.value = data;"
        '  ta.style.position = "fixed"; ta.style.opacity = "0";'
        "  document.body.appendChild(ta);"
        "  ta.focus(); ta.select();"
        "  let ok = false;"
        '  try { ok = document.execCommand("copy"); } catch (e) { ok = false; }'
        "  document.body.removeChild(ta);"
        f"  const original = {json.dumps(label)};"
        '  btn.textContent = ok ? "✓ Copied!" : "⚠ Press Ctrl/Cmd+C";'
        "  setTimeout(() => { btn.textContent = original; }, 2000);"
        "});"
        "</script>"
    )
    st.iframe(html, height=height)


def fmt_cost(value: Optional[float]) -> str:
    """Format an estimated USD cost. `None` (unpriced / local model) shows as '—'.
    Small amounts keep enough precision to be meaningful (e.g. '$0.0123')."""
    if value is None:
        return "—"
    if value == 0:
        return "$0.00"
    if value < 0.01:
        return f"${value:.4f}"
    if value < 1:
        return f"${value:.3f}"
    return f"${value:,.2f}"


def _log_preview(r: dict[str, Any]) -> str:
    """Best-effort preview text for a chat_logs row: the stored response preview,
    else the tool result preview tucked inside detail_json."""
    if r.get("response_preview"):
        return r["response_preview"]
    if r.get("detail_json"):
        try:
            return json.loads(r["detail_json"]).get("result_preview", "")
        except (json.JSONDecodeError, TypeError):
            return ""
    return ""


def _log_arguments(r: dict[str, Any]) -> str:
    """The tool-call arguments stored in detail_json, rendered as compact JSON."""
    if r.get("detail_json"):
        try:
            args = json.loads(r["detail_json"]).get("arguments")
            return json.dumps(args) if args is not None else ""
        except (json.JSONDecodeError, TypeError):
            return ""
    return ""


def log_table_rows(logs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Map raw chat_logs rows to the standardized per-call table columns shared by
    the Chat, Logs, and Benchmark pages — one source of truth so every per-call
    table shows the same metrics."""
    return [
        {
            "Time": (r["created_at"] or "")[11:],
            "Event": r["event_type"],
            "Provider": r["provider"],
            "Model": r["model"],
            "Call type": r["call_type"],
            "Prompt tokens": r["prompt_tokens"],
            "Completion tokens": r["completion_tokens"],
            "Total tokens": r["total_tokens"],
            "Duration (ms)": r["duration_ms"],
            "Result size (chars)": r["data_chars"],
            "Success": r["success"],
            "Error": r["error"],
            "Attempt": r["attempt"],
            "Server": r["server"],
            "Tools": r["tools"],
            "Arguments": _log_arguments(r),
            "Preview": _log_preview(r),
        }
        for r in logs
    ]


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
