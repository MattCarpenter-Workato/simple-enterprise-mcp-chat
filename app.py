"""
MCP Chat — Streamlit web UI (Chat page).

Run with:  uv run streamlit run app.py

Sidebar: provider/model picker, system-prompt picker, and conversation list.
Main: a chat interface backed by the MCP tool-calling providers. Everything
(servers, credentials, prompts, conversations) is persisted in SQLite via db.py.
Server, prompt, and key management live on the pages in pages/.
"""

import json
import logging

import streamlit as st

import chat_runner
import db
import providers
from ui_common import (init_app, render_nav, render_history, effective_system_prompt,
                       get_client_and_tools, server_signature,
                       available_models, model_fingerprint, log_table_rows, fmt_cost)

st.set_page_config(page_title="MCP Chat", page_icon="💬", layout="wide")
init_app()
render_nav()

logger = logging.getLogger("mcpchat.app")


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

    model_opts = available_models(provider_name, model_fingerprint(provider_name))
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

    # MCP servers to expose to the model. Defaults to all enabled servers; pick a
    # subset to limit which servers' tools the model can call this chat. Tools are
    # prefixed `server__tool`, so we filter the discovered tools by these names.
    enabled_servers = [s["name"] for s in db.list_servers(enabled_only=True)]
    selected_servers = st.multiselect(
        "MCP servers", enabled_servers, default=enabled_servers, key="chat_servers",
        help="Only the selected servers' tools are offered to the model.",
    )

    st.divider()
    if st.button("➕ New chat", width='stretch'):
        new_conversation()
        st.rerun()

    st.caption("Conversations")
    for conv in db.list_conversations():
        cols = st.columns([0.8, 0.2])
        active = conv["id"] == st.session_state.conversation_id
        label = ("▶ " if active else "") + (conv["title"] or f"Chat {conv['id']}")
        if cols[0].button(label, key=f"conv_{conv['id']}", width='stretch'):
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

# Limit the tools offered to the model to the servers picked in the sidebar.
tools = [t for t in tools if chat_runner.server_of(t["name"]) in selected_servers]

n_servers = len(selected_servers)
st.caption(f"Provider: **{provider_name}** · Model: **{st.session_state.model}** · "
           f"{n_servers} server(s), {len(tools)} tool(s)")
if st.session_state.conversation_id is not None:
    _cost = db.conversation_cost(st.session_state.conversation_id)
    st.caption(f"💲 Est. cost so far: **{fmt_cost(_cost)}**")
if disc_errors:
    st.warning(
        "Some servers had issues: "
        + "; ".join(f"{k}: {v}" for k, v in disc_errors.items())
        + "  —  use **🔄 Reconnect MCP servers** on the **🔌 MCP Servers** page; it "
        "will prompt for login if a token is missing or expired."
    )

# Per-chat logs & token/latency usage.
if st.session_state.conversation_id is not None:
    with st.expander("📊 Logs & usage (this chat)"):
        u = db.conversation_usage(st.session_state.conversation_id)
        c1, c2, c3, c4, c5, c6 = st.columns(6)
        c1.metric("Total tokens", f"{u['total_tokens']:,}")
        c2.metric("Prompt tokens", f"{u['prompt_tokens']:,}")
        c3.metric("Completion tokens", f"{u['completion_tokens']:,}")
        c4.metric("LLM time", f"{(u['llm_ms'] or 0) / 1000:.1f}s")
        c5.metric("Tool calls", u["tool_calls"])
        c6.metric("Est. cost", fmt_cost(db.conversation_cost(st.session_state.conversation_id)))
        logs = db.get_logs(st.session_state.conversation_id)
        if logs:
            st.dataframe(log_table_rows(logs), width='stretch', hide_index=True)
        else:
            st.caption("No log entries yet for this chat.")

render_history(st.session_state.messages)

prompt = st.chat_input("Message…")
if prompt:
    # Build the provider (surfaces missing-key errors before we mutate state).
    try:
        provider = providers.get_provider(provider_name)
    except ValueError as e:
        logger.warning("Provider unavailable (%s): %s", provider_name, e)
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

    # When on, the FULL tool call + response (args, headers, body, detected job ID)
    # is written to the app log FILE — not the DB (which stays a concise preview).
    debug_io = (db.get_secret("DEBUG_TOOL_IO", "false") or "false").lower() == "true"

    model = st.session_state.model

    pre_len = len(st.session_state.messages)
    with st.chat_message("assistant"):
        try:
            with st.status("Generating…", expanded=True) as status:
                final_text, _total_ms = chat_runner.run_turn(
                    client=client, provider=provider, provider_name=provider_name,
                    model=model, messages=st.session_state.messages, tools=tools,
                    sys_prompt=sys_prompt, user_prompt=prompt, conv_id=conv_id,
                    debug_io=debug_io, on_status=status.write,
                )
                status.update(label="Done", state="complete", expanded=False)
            st.markdown(final_text or "_(no response)_")
        except Exception as e:  # noqa: BLE001
            logger.exception("Chat turn failed (conv=%s provider=%s model=%s)",
                             conv_id, provider_name, model)
            st.error(f"Error: {e}")
            db.add_log(conv_id, event_type="error", provider=provider_name,
                       model=model, user_prompt=prompt,
                       detail_json=json.dumps({"error": str(e)}))
            # Roll back the user turn we optimistically added.
            del st.session_state.messages[pre_len - 1:]
            st.stop()

    # Persist everything the provider appended (tool turns + final answer).
    for m in st.session_state.messages[pre_len:]:
        db.add_message(conv_id, m["role"], m["content"])
    st.rerun()
