"""
MCP Chat — Streamlit web UI (Chat page).

Run with:  uv run streamlit run app.py

Sidebar: provider/model picker, system-prompt picker, and conversation list.
Main: a chat interface backed by the MCP tool-calling providers. Everything
(servers, credentials, prompts, conversations) is persisted in SQLite via db.py.
Server, prompt, and key management live on the pages in pages/.
"""

import streamlit as st

import db
import providers
from mcp_core import MCPClient
from ui_common import init_app, render_history, effective_system_prompt

st.set_page_config(page_title="MCP Chat", page_icon="💬", layout="wide")
init_app()


@st.cache_resource
def get_client_and_tools(signature: str):
    """Build an MCP client and discover tools. Cached across reruns; the
    `signature` (derived from the enabled-server set) busts the cache when the
    server configuration changes. Returns (client, tools, errors)."""
    client = MCPClient()
    tools = client.discover_tools()
    return client, tools, dict(client.errors)


def server_signature() -> str:
    return "|".join(
        f"{s['name']}:{s['url']}:{s['auth_type']}"
        for s in db.list_servers(enabled_only=True)
    )


def load_conversation(conv_id: int) -> None:
    convs = {c["id"]: c for c in db.list_conversations()}
    conv = convs.get(conv_id)
    if not conv:
        return
    st.session_state.conversation_id = conv_id
    st.session_state.messages = db.get_messages(conv_id)
    if conv["provider"]:
        st.session_state.provider = conv["provider"]
    if conv["model"]:
        st.session_state.model = conv["model"]
    st.session_state.system_prompt_id = conv["system_prompt_id"]


def new_conversation() -> None:
    st.session_state.conversation_id = None
    st.session_state.messages = []


# --- session defaults --------------------------------------------------------
st.session_state.setdefault("provider", providers.PROVIDER_NAMES[0])
st.session_state.setdefault("model", providers.default_model(st.session_state.provider))
st.session_state.setdefault("messages", [])
st.session_state.setdefault("conversation_id", None)
st.session_state.setdefault("system_prompt_id", None)

# =============================================================================
# SIDEBAR
# =============================================================================
with st.sidebar:
    st.header("💬 MCP Chat")

    # Provider + model. Once a conversation has started it is locked to the
    # provider/model it began with — switching mid-chat would send one provider's
    # message format to another's API. Use ➕ New chat to pick a different model.
    locked = st.session_state.conversation_id is not None and len(st.session_state.messages) > 0

    provider_name = st.selectbox(
        "Provider", providers.PROVIDER_NAMES,
        index=providers.PROVIDER_NAMES.index(st.session_state.provider),
        disabled=locked,
    )
    if not locked and provider_name != st.session_state.provider:
        st.session_state.provider = provider_name
        st.session_state.model = providers.default_model(provider_name)

    model_opts = providers.model_options(provider_name)
    # Guarantee the active model is selectable so a locked chat never falls back
    # to opts[0].
    if st.session_state.model not in model_opts:
        model_opts = [st.session_state.model] + model_opts
    st.session_state.model = st.selectbox(
        "Model", model_opts, index=model_opts.index(st.session_state.model),
        disabled=locked,
    )

    if locked:
        st.caption(f"🔒 Locked to **{st.session_state.provider}** for this chat — "
                   "click ➕ New chat to use a different model.")

    # System prompt
    prompts = db.list_prompts()
    prompt_labels = ["(none)"] + [p["name"] for p in prompts]
    prompt_ids = [None] + [p["id"] for p in prompts]
    cur_idx = prompt_ids.index(st.session_state.system_prompt_id) \
        if st.session_state.system_prompt_id in prompt_ids else 0
    sel = st.selectbox("System prompt", prompt_labels, index=cur_idx)
    st.session_state.system_prompt_id = prompt_ids[prompt_labels.index(sel)]

    st.divider()
    if st.button("➕ New chat", use_container_width=True):
        new_conversation()
        st.rerun()

    st.caption("Conversations")
    for conv in db.list_conversations():
        cols = st.columns([0.8, 0.2])
        active = conv["id"] == st.session_state.conversation_id
        label = ("▶ " if active else "") + (conv["title"] or f"Chat {conv['id']}")
        if cols[0].button(label, key=f"conv_{conv['id']}", use_container_width=True):
            load_conversation(conv["id"])
            st.rerun()
        if cols[1].button("🗑", key=f"del_{conv['id']}"):
            db.delete_conversation(conv["id"])
            if active:
                new_conversation()
            st.rerun()

# =============================================================================
# MAIN — CHAT
# =============================================================================
client, tools, disc_errors = get_client_and_tools(server_signature())

n_servers = len(client.servers)
st.caption(f"Provider: **{provider_name}** · Model: **{st.session_state.model}** · "
           f"{n_servers} server(s), {len(tools)} tool(s)")
if disc_errors:
    st.warning("Some servers had issues: " +
               "; ".join(f"{k}: {v}" for k, v in disc_errors.items()))

render_history(st.session_state.messages)

prompt = st.chat_input("Message…")
if prompt:
    # Build the provider (surfaces missing-key errors before we mutate state).
    try:
        provider = providers.get_provider(provider_name)
    except ValueError as e:
        st.error(str(e))
        st.stop()

    # Lazily create a conversation on the first message.
    if st.session_state.conversation_id is None:
        title = prompt[:50] + ("…" if len(prompt) > 50 else "")
        st.session_state.conversation_id = db.create_conversation(
            title, provider_name, st.session_state.model, st.session_state.system_prompt_id
        )
    conv_id = st.session_state.conversation_id

    # Record + show the user message.
    st.session_state.messages.append({"role": "user", "content": prompt})
    db.add_message(conv_id, "user", prompt)
    with st.chat_message("user"):
        st.markdown(prompt)

    # Resolve the system prompt (+ optional date injection).
    base_prompt = ""
    if st.session_state.system_prompt_id:
        p = db.get_prompt(st.session_state.system_prompt_id)
        base_prompt = p["content"] if p else ""
    inject_date = (db.get_secret("INJECT_CURRENT_DATE", "true") or "true").lower() == "true"
    sys_prompt = effective_system_prompt(base_prompt, inject_date)

    pre_len = len(st.session_state.messages)
    with st.chat_message("assistant"):
        try:
            with st.status("Generating…", expanded=True) as status:
                def on_event(kind: str, payload: dict) -> None:
                    if kind == "tool_call":
                        status.write(f"🔧 Calling `{payload['name']}`…")
                    elif kind == "tool_result":
                        preview = str(payload["result"])[:120]
                        status.write(f"✓ `{payload['name']}` → {preview}")

                final_text = provider.chat_turn(
                    st.session_state.messages, tools, sys_prompt,
                    st.session_state.model, client.call_tool, on_event,
                )
                status.update(label="Done", state="complete", expanded=False)
            st.markdown(final_text or "_(no response)_")
        except Exception as e:  # noqa: BLE001
            st.error(f"Error: {e}")
            # Roll back the user turn we optimistically added.
            del st.session_state.messages[pre_len - 1:]
            st.stop()

    # Persist everything the provider appended (tool turns + final answer).
    for m in st.session_state.messages[pre_len:]:
        db.add_message(conv_id, m["role"], m["content"])
    st.rerun()
