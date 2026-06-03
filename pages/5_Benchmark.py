"""Benchmarking workspace.

Run one prompt across several (provider, model) variants against the current MCP
servers, then compare tokens / latency / total turn time / tool reliability side by
side. This is the core tuning workflow: change a recipe or model, re-run the same
prompt, and see what got cheaper/faster without hurting the answer.
"""

import logging

import streamlit as st

import chat_runner
import db
import providers
from chat_runner import server_of
from ui_common import (init_app, render_nav, effective_system_prompt,
                       display_text, get_client_and_tools, server_signature,
                       available_models, model_fingerprint)

st.set_page_config(page_title="Benchmark", page_icon="⚗️", layout="wide")
init_app()
render_nav()

logger = logging.getLogger("mcpchat.benchmark")

st.title("⚗️ Benchmark — compare models on one prompt")
st.caption("Run the same prompt across multiple models against your current MCP "
           "servers, then compare tokens, latency, and tool reliability.")

# Shared (cached) MCP client + discovered tools — identical to the Chat page.
client, tools, disc_errors = get_client_and_tools(server_signature())
st.caption(f"MCP context: **{len(client.servers)}** server(s), **{len(tools)}** tool(s).")
if disc_errors:
    st.warning("Some servers had issues: "
               + "; ".join(f"{k}: {v}" for k, v in disc_errors.items())
               + "  —  fix on the **🔌 MCP Servers** page.")

# All selectable variants: every model under every provider (live list for
# Claude/OpenAI, static otherwise).
VARIANTS: list[tuple[str, str]] = [
    (p, m) for p in providers.PROVIDER_NAMES
    for m in available_models(p, model_fingerprint(p))
]
def _variant_label(v: tuple[str, str]) -> str:
    return f"{v[0]} · {v[1]}"

# =============================================================================
# SETUP
# =============================================================================
st.subheader("1. Set up the run")

prompt = st.text_area("Prompt", height=120, placeholder="Ask the same thing of every model…")

prompts = db.list_prompts()
prompt_labels = ["(none)"] + [p["name"] for p in prompts]
prompt_ids = [None] + [p["id"] for p in prompts]
sys_idx = st.selectbox("System prompt", range(len(prompt_labels)),
                       format_func=lambda i: prompt_labels[i])
system_prompt_id = prompt_ids[sys_idx]

# Pre-select the Chat page's current provider/model if one is set.
default_variant = (st.session_state.get("provider"), st.session_state.get("model"))
selected = st.multiselect(
    "Models to compare", VARIANTS, format_func=_variant_label,
    default=[v for v in VARIANTS if v == default_variant],
)
if st.button("🔄 Refresh models", key="refresh_models_bench"):
    available_models.clear()
    st.rerun()

# MCP servers to expose to the models for this run. Tools are prefixed
# `server__tool`, so we filter the discovered tool list down to the chosen servers.
# Use this to A/B whether a model does better with fewer / different servers.
all_servers = sorted(client.servers.keys())
selected_servers = st.multiselect(
    "MCP servers to use", all_servers, default=all_servers,
    help="Only the selected servers' tools are offered to the models for this run.",
)
active_tools = [t for t in tools if server_of(t["name"]) in selected_servers]
st.caption(f"Using **{len(selected_servers)}** of {len(all_servers)} server(s) → "
           f"**{len(active_tools)}** tool(s) for this run.")

col_a, col_b = st.columns(2)
label = col_a.text_input("Run label (optional)", placeholder="e.g. agiloft-v2")
notes = col_b.text_input("Notes (optional)")

run_clicked = st.button("▶ Run benchmark", type="primary",
                        disabled=not (prompt.strip() and selected))

# =============================================================================
# EXECUTE
# =============================================================================
if run_clicked:
    inject_date = (db.get_secret("INJECT_CURRENT_DATE", "true") or "true").lower() == "true"
    base_prompt = ""
    if system_prompt_id:
        p = db.get_prompt(system_prompt_id)
        base_prompt = p["content"] if p else ""
    sys_prompt = effective_system_prompt(base_prompt, inject_date)
    debug_io = (db.get_secret("DEBUG_TOOL_IO", "false") or "false").lower() == "true"

    run_id = db.create_benchmark_run(prompt, system_prompt_id, label or None, notes or None)
    progress = st.progress(0.0, text="Starting…")

    for i, (prov_name, model) in enumerate(selected):
        progress.progress(i / len(selected), text=f"Running {prov_name} · {model}…")
        try:
            provider = providers.get_provider(prov_name)
        except ValueError as e:
            # Missing key / unconfigured provider — record and keep going.
            db.add_benchmark_variant(run_id, prov_name, model, None, None, "error", str(e))
            continue

        title = f"[bench #{run_id}] {model} — {prompt[:40]}"
        conv_id = db.create_conversation(title, prov_name, model, system_prompt_id)
        messages = [{"role": "user", "content": prompt}]
        db.add_message(conv_id, "user", prompt)
        try:
            final_text, total_ms = chat_runner.run_turn(
                client=client, provider=provider, provider_name=prov_name,
                model=model, messages=messages, tools=active_tools, sys_prompt=sys_prompt,
                user_prompt=prompt, conv_id=conv_id, benchmark_run_id=run_id,
                debug_io=debug_io,
            )
            for m in messages[1:]:
                db.add_message(conv_id, m["role"], m["content"])
            db.add_benchmark_variant(run_id, prov_name, model, conv_id, total_ms, "ok")
        except Exception as e:  # noqa: BLE001
            logger.exception("Benchmark variant failed (run=%s %s %s)", run_id, prov_name, model)
            db.add_log(conv_id, event_type="error", provider=prov_name, model=model,
                       user_prompt=prompt, benchmark_run_id=run_id)
            db.add_benchmark_variant(run_id, prov_name, model, conv_id, None, "error", str(e))

    progress.progress(1.0, text="Done.")
    st.session_state["benchmark_run_id"] = run_id
    st.success(f"Benchmark run #{run_id} complete.")

st.divider()

# =============================================================================
# COMPARE
# =============================================================================
st.subheader("2. Compare runs")

runs = db.list_benchmark_runs()
if not runs:
    st.info("No benchmark runs yet — set one up above.")
    st.stop()

def _run_label(r: dict) -> str:
    tag = f" · {r['label']}" if r["label"] else ""
    return f"#{r['id']} — {r['prompt'][:50]}{tag} ({r['created_at']})"

# Default to the most recent / just-run run.
default_run = st.session_state.get("benchmark_run_id", runs[0]["id"])
run_idx = next((i for i, r in enumerate(runs) if r["id"] == default_run), 0)
sel = st.selectbox("Run", range(len(runs)), index=run_idx, format_func=lambda i: _run_label(runs[i]))
run = runs[sel]

st.caption(f"**Prompt:** {run['prompt']}")

rows = db.benchmark_comparison(run["id"])
if not rows:
    st.info("This run has no variants.")
    st.stop()

st.dataframe(
    [
        {
            "variant": f"{r['provider']} · {r['model']}",
            "status": r["status"],
            "total time (s)": round((r["total_ms"] or 0) / 1000, 1),
            "total tokens": r["total_tokens"],
            "prompt tok": r["prompt_tokens"],
            "completion tok": r["completion_tokens"],
            "LLM calls": r["llm_calls"],
            "LLM time (s)": round((r["llm_ms"] or 0) / 1000, 1),
            "tool calls": r["tool_calls"],
            "tool errors": r["tool_errors"],
            "retries": r["retries"],
            "answer": r["answer"],
        }
        for r in rows
    ],
    width="stretch", hide_index=True,
)

# Charts: total tokens and total turn time per variant.
ok_rows = [r for r in rows if r["status"] == "ok"]
if ok_rows:
    c1, c2 = st.columns(2)
    with c1:
        st.caption("Total tokens per variant")
        st.bar_chart({f"{r['provider']} · {r['model']}": r["total_tokens"] for r in ok_rows})
    with c2:
        st.caption("Total turn time per variant (s)")
        st.bar_chart({f"{r['provider']} · {r['model']}": round((r["total_ms"] or 0) / 1000, 2)
                      for r in ok_rows})

# Full final answers for quality eyeballing.
st.markdown("**Final answers**")
for r in rows:
    header = f"{r['provider']} · {r['model']}"
    with st.expander(header + (f"  — ⚠️ {r['error']}" if r["status"] == "error" else "")):
        if r["status"] == "error":
            st.error(r["error"] or "Variant failed.")
        elif r["conversation_id"]:
            answer = ""
            for m in reversed(db.get_messages(r["conversation_id"])):
                shown = display_text(m)
                if shown and shown[0] == "assistant" and shown[1]:
                    answer = shown[1]
                    break
            st.markdown(answer or "_(no text answer)_")
