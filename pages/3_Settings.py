"""Settings page — API keys, provider defaults, and behavior toggles (in SQLite)."""

import streamlit as st

import db
from ui_common import init_app

st.set_page_config(page_title="Settings", page_icon="⚙️", layout="wide")
init_app()

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

    if st.form_submit_button("💾 Save settings"):
        for key, value in secret_inputs.items():
            if value:  # only overwrite when the user typed something
                db.set_secret(key, value)
        for key, value in plain_inputs.items():
            db.set_secret(key, value)
        db.set_secret("INJECT_CURRENT_DATE", "true" if inject else "false")
        st.success("Settings saved.")
        st.rerun()

# --- danger zone -------------------------------------------------------------
st.divider()
with st.expander("Clear a stored secret"):
    keys = [k for k, _ in SECRET_FIELDS]
    target = st.selectbox("Secret to clear", keys)
    if st.button("Clear secret"):
        db.set_secret(target, None)
        st.success(f"Cleared {target}.")
        st.rerun()
