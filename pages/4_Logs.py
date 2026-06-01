"""Logs & benchmarking page.

Browse per-chat logs and compare models (tokens / latency) and MCP servers/tools
(latency / returned-data size) to tune them.
"""

import json
import os

import streamlit as st

import db
from ui_common import init_app
from logging_setup import APP_LOG_PATH, read_tail, clear_log

st.set_page_config(page_title="Logs", page_icon="📊", layout="wide")
init_app()

st.title("📊 Logs & Benchmarking")

# --- clear all logs (guarded) ------------------------------------------------
with st.popover("🗑 Clear all logs"):
    st.caption("Permanently deletes every conversation log row (across all "
               "conversations) and clears the app log file. Chats and messages "
               "are not affected.")
    confirm = st.checkbox("Yes, I'm sure", key="confirm_clear_all")
    if st.button("Delete all logs", type="primary", disabled=not confirm):
        removed = db.clear_all_logs()
        clear_log()
        st.success(f"Cleared {removed} conversation log row(s) and the app log.")
        st.rerun()

# =============================================================================
# ALL LOG ENTRIES (global, CSV-exportable)
# =============================================================================
st.subheader("All conversation log entries")
all_rows = db.all_logs()
if all_rows:
    st.caption(f"{len(all_rows)} entries — hover the table and click ⬇ to export to CSV.")

    def _preview(r: dict) -> str:
        if r["response_preview"]:
            return r["response_preview"]
        if r["detail_json"]:
            try:
                return json.loads(r["detail_json"]).get("result_preview", "")
            except (json.JSONDecodeError, TypeError):
                return ""
        return ""

    def _arguments(r: dict) -> str:
        if r["detail_json"]:
            try:
                args = json.loads(r["detail_json"]).get("arguments")
                return json.dumps(args) if args is not None else ""
            except (json.JSONDecodeError, TypeError):
                return ""
        return ""

    st.dataframe(
        [
            {
                "id": r["id"],
                "created_at": r["created_at"],
                "conversation": r["conversation"],
                "conversation_id": r["conversation_id"],
                "event_type": r["event_type"],
                "provider": r["provider"],
                "model": r["model"],
                "call_type": r["call_type"],
                "prompt_tokens": r["prompt_tokens"],
                "completion_tokens": r["completion_tokens"],
                "total_tokens": r["total_tokens"],
                "duration_ms": r["duration_ms"],
                "data_chars": r["data_chars"],
                "server": r["server"],
                "servers": r["servers"],
                "tools": r["tools"],
                "arguments": _arguments(r),
                "user_prompt": r["user_prompt"],
                "system_prompt": r["system_prompt"],
                "preview": _preview(r),
            }
            for r in all_rows
        ],
        width='stretch', hide_index=True,
    )
else:
    st.caption("No log entries yet.")

st.divider()

# =============================================================================
# PER-CHAT LOGS
# =============================================================================
st.subheader("Per-conversation logs")

convs = db.list_conversations()
if not convs:
    st.info("No conversations yet.")
else:
    labels = [f"{c['title']} (#{c['id']}, {c['provider']})" for c in convs]
    idx = st.selectbox("Conversation", range(len(convs)), format_func=lambda i: labels[i])
    conv = convs[idx]

    u = db.conversation_usage(conv["id"])
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total tokens", f"{u['total_tokens']:,}")
    c2.metric("LLM calls", u["llm_calls"])
    c3.metric("LLM time", f"{(u['llm_ms'] or 0) / 1000:.1f}s")
    c4.metric("Avg tool ms", int(u["avg_tool_ms"] or 0))

    logs = db.get_logs(conv["id"])
    if logs:
        st.dataframe(
            [
                {
                    "time": r["created_at"][11:],
                    "type": r["event_type"],
                    "provider": r["provider"],
                    "model": r["model"],
                    "call_type": r["call_type"],
                    "prompt_tok": r["prompt_tokens"],
                    "completion_tok": r["completion_tokens"],
                    "total_tok": r["total_tokens"],
                    "ms": r["duration_ms"],
                    "data_chars": r["data_chars"],
                    "server": r["server"],
                    "tools": r["tools"],
                    "preview": (r["response_preview"] or
                                (json.loads(r["detail_json"]).get("result_preview")
                                 if r["detail_json"] else "")),
                }
                for r in logs
            ],
            width='stretch', hide_index=True,
        )
    else:
        st.caption("No log entries for this conversation.")

st.divider()

# =============================================================================
# MODEL COMPARISON
# =============================================================================
st.subheader("Models — tokens & latency")
st.caption("Across all conversations. Use this to compare models/providers.")
model_rows = db.usage_by_provider_model()
if model_rows:
    st.dataframe(model_rows, width='stretch', hide_index=True)
    chart = {r["model"] or r["provider"]: (r["avg_ms"] or 0) for r in model_rows}
    if chart:
        st.bar_chart(chart, y_label="avg LLM latency (ms)")
else:
    st.caption("No LLM calls logged yet.")

st.divider()

# =============================================================================
# MCP SERVER / TOOL COMPARISON
# =============================================================================
st.subheader("MCP servers & tools — latency & data size")
st.caption("Across all conversations. Use this to tune which MCP servers to keep.")
tool_rows = db.usage_by_server_tool()
if tool_rows:
    st.dataframe(tool_rows, width='stretch', hide_index=True)
    # Average latency per server (aggregate the per-tool rows by server).
    by_server: dict[str, list[int]] = {}
    for r in tool_rows:
        if r["server"]:
            by_server.setdefault(r["server"], []).append(r["avg_ms"] or 0)
    if by_server:
        st.bar_chart(
            {s: sum(v) / len(v) for s, v in by_server.items()},
            y_label="avg round-trip (ms)",
        )
else:
    st.caption("No MCP tool calls logged yet.")

st.divider()

# =============================================================================
# APP LOG (file-based) — app health, distinct from the per-conversation logs above
# =============================================================================
st.subheader("🐞 App log")
st.caption(f"Application errors & events from `{os.path.relpath(APP_LOG_PATH)}` "
           "(rotating file). Separate from the conversation logs above.")
c1, c2 = st.columns([0.25, 0.75])
n_lines = c1.number_input("Lines to show", min_value=20, max_value=2000,
                          value=200, step=20)
if c2.button("🗑 Clear app log"):
    clear_log()
    st.rerun()
tail = read_tail(int(n_lines))
st.code(tail or "(app log is empty)", language="log")
