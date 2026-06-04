"""Settings page — API keys, provider defaults, and behavior toggles (in SQLite)."""

import streamlit as st

import db
from ui_common import init_app, render_nav, available_models

st.set_page_config(page_title="Settings", page_icon="⚙️", layout="wide")
init_app()
render_nav()

st.title("⚙️ Settings")
st.caption("Credentials and settings are stored in mcp_chat.db (plaintext, "
           "git-ignored). Leave a secret blank to keep the existing value.")


def mask(value: str | None) -> str:
    if not value:
        return "— not set —"
    if len(value) <= 8:
        return "•" * len(value)
    return f"{value[:4]}…{value[-4:]}"


# --- API keys (secrets) ------------------------------------------------------
SECRET_FIELDS = [
    ("OPENAI_API_KEY", "OpenAI API key"),
    ("CLAUDE_API_KEY", "Claude (Anthropic) API key"),
]
PLAIN_FIELDS = [
    ("OPENAI_MODEL", "OpenAI model", "gpt-4o-mini"),
    ("CLAUDE_MODEL", "Claude model", "claude-sonnet-4-5-20250929"),
    ("OLLAMA_BASE_URL", "Ollama base URL", "http://localhost:11434"),
    ("OLLAMA_MODEL", "Ollama model", "llama3.2"),
    ("LMSTUDIO_BASE_URL", "LM Studio base URL", "http://localhost:1234/v1"),
    ("LMSTUDIO_MODEL", "LM Studio model", "local-model"),
    ("APP_LOG_LEVEL", "App log level (DEBUG/INFO/WARNING/ERROR) — restart to apply", "INFO"),
]

st.subheader("API keys")
for key, label in SECRET_FIELDS:
    st.caption(f"{label}: current value `{mask(db.get_secret(key))}`")

with st.form("settings"):
    st.markdown("**Secrets** (blank = unchanged)")
    secret_inputs = {
        key: st.text_input(label, value="", type="password", key=f"in_{key}")
        for key, label in SECRET_FIELDS
    }

    st.markdown("**Provider defaults**")
    plain_inputs = {
        key: st.text_input(label, value=db.get_secret(key) or default, key=f"in_{key}")
        for key, label, default in PLAIN_FIELDS
    }

    st.markdown("**Behavior**")
    inject = st.checkbox(
        "Inject current date/time into the system prompt",
        value=(db.get_secret("INJECT_CURRENT_DATE", "true") or "true").lower() == "true",
    )
    debug_io = st.checkbox(
        "Debug: log full tool call & response to the app log file",
        value=(db.get_secret("DEBUG_TOOL_IO", "false") or "false").lower() == "true",
        help="Writes each MCP tool call's full arguments, response headers, body, "
             "and any detected Workato job ID to logs/app.log (viewable on the Logs "
             "page). The database keeps only a concise preview either way.",
    )

    if st.form_submit_button("💾 Save settings"):
        for key, value in secret_inputs.items():
            if value:  # only overwrite when the user typed something
                db.set_secret(key, value)
        for key, value in plain_inputs.items():
            db.set_secret(key, value)
        db.set_secret("INJECT_CURRENT_DATE", "true" if inject else "false")
        db.set_secret("DEBUG_TOOL_IO", "true" if debug_io else "false")
        st.toast("Settings saved.", icon="✅")
        st.rerun()

# --- models ------------------------------------------------------------------
st.divider()
st.subheader("Models")
st.caption("Live model lists (Claude/OpenAI) are cached. Refresh to re-fetch from "
           "the provider API — e.g. after adding a key or when a new model ships.")
if st.button("🔄 Refresh models"):
    available_models.clear()
    st.success("Model lists refreshed.")

# --- model pricing -----------------------------------------------------------
st.divider()
st.subheader("Model pricing")
st.caption("Estimated cost rates in **USD per 1,000,000 tokens**, used for the chat "
           "and benchmark cost metrics. Claude & OpenAI only (local models are free). "
           "A model matches by exact ID, then by the longest family-prefix — so a stem "
           "like `claude-sonnet-4` also prices dated snapshots like "
           "`claude-sonnet-4-5-20250929`. Add a row for an exact model to override.")
price_edit = st.data_editor(
    db.list_model_prices(),
    num_rows="dynamic",
    width="stretch",
    key="model_prices_editor",
    column_config={
        "provider": st.column_config.TextColumn("Provider", help="Claude or OpenAI"),
        "model": st.column_config.TextColumn("Model (exact ID or family stem)"),
        "input_per_mtok": st.column_config.NumberColumn("Input $/1M", format="%.4f", min_value=0.0),
        "output_per_mtok": st.column_config.NumberColumn("Output $/1M", format="%.4f", min_value=0.0),
    },
)
if st.button("💾 Save pricing"):
    db.replace_model_prices(price_edit)
    st.toast("Model pricing saved.", icon="✅")
    st.rerun()

# --- danger zone -------------------------------------------------------------
st.divider()
st.subheader("Maintenance")

with st.expander("Clear a stored secret"):
    keys = [k for k, _ in SECRET_FIELDS]
    target = st.selectbox("Secret to clear", keys)
    if st.button("Clear secret"):
        db.set_secret(target, None)
        st.toast(f"Cleared {target}.", icon="✅")
        st.rerun()

with st.popover("🔑 Clear all auth tokens (force re-sync)"):
    st.caption("Deletes all stored OAuth tokens and client registrations, and "
               "re-discovers tools. Every OAuth server will need to be "
               "re-authenticated (🔐 Re-authenticate on the MCP Servers page).")
    if st.checkbox("Yes, clear all auth tokens", key="confirm_clear_tokens"):
        if st.button("Clear auth tokens", type="primary"):
            removed = db.clear_all_oauth_tokens()
            st.cache_resource.clear()  # bust the discovery cache so tools re-sync
            st.toast(f"Cleared {removed} token(s). Re-authenticate each OAuth "
                     "server on the MCP Servers page.", icon="✅")
            st.rerun()

with st.popover("🗑 Clear all benchmark runs"):
    st.caption("Permanently deletes every benchmark run and its variants, plus the "
               "per-variant conversations they created (and their messages/logs). "
               "Your regular chats, servers, keys, and prompts are kept.")
    if st.checkbox("Yes, clear all benchmark runs", key="confirm_clear_benchmarks"):
        if st.button("Clear benchmark runs", type="primary"):
            removed = db.clear_all_benchmark_runs()
            # The benchmark page may point at a now-deleted run.
            st.session_state.pop("benchmark_run_id", None)
            st.toast(f"Cleared {removed} benchmark run(s).", icon="✅")
            st.rerun()
