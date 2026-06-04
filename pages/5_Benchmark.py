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
                       available_models, model_fingerprint, log_table_rows, fmt_cost)

st.set_page_config(page_title="Benchmark", page_icon="⚗️", layout="wide")
init_app()
render_nav()

logger = logging.getLogger("mcpchat.benchmark")

st.title("⚗️ Benchmark — compare models or MCP servers on one prompt")
st.caption("Run the same prompt across multiple models (against your current MCP "
           "servers), or across MCP servers with one fixed model, then compare "
           "tokens, latency, and tool reliability.")

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

# What axis are we comparing on this run?
mode = st.radio(
    "Compare", ["Models", "MCP servers"], horizontal=True,
    help="Models: same prompt across models (shared servers). "
         "MCP servers: one fixed model, one variant per server.",
)
mode_key = "servers" if mode == "MCP servers" else "models"

all_servers = sorted(client.servers.keys())
# Pre-select the Chat page's current provider/model if one is set.
default_variant = (st.session_state.get("provider"), st.session_state.get("model"))

# `bench_plan` is the list of variants to run: each is (provider, model, [servers]).
bench_plan: list[tuple[str, str, list[str]]] = []

if mode_key == "models":
    selected = st.multiselect(
        "Models to compare", VARIANTS, format_func=_variant_label,
        default=[v for v in VARIANTS if v == default_variant],
    )

    # MCP servers to expose to the models for this run. Tools are prefixed
    # `server__tool`, so we filter the discovered tool list down to the chosen
    # servers. Use this to A/B whether a model does better with fewer servers.
    selected_servers = st.multiselect(
        "MCP servers to use", all_servers, default=all_servers,
        help="Only the selected servers' tools are offered to the models for this run.",
    )
    active_tools = [t for t in tools if server_of(t["name"]) in selected_servers]
    st.caption(f"Using **{len(selected_servers)}** of {len(all_servers)} server(s) → "
               f"**{len(active_tools)}** tool(s) for this run.")
    bench_plan = [(p, m, selected_servers) for (p, m) in selected]
else:
    # Fixed model, one variant per server: isolate how the model does with each.
    default_idx = next((i for i, v in enumerate(VARIANTS) if v == default_variant), 0)
    model_idx = st.selectbox(
        "Model", range(len(VARIANTS)), index=default_idx if VARIANTS else 0,
        format_func=lambda i: _variant_label(VARIANTS[i]),
    )
    chosen_provider, chosen_model = VARIANTS[model_idx] if VARIANTS else (None, None)

    compare_servers = st.multiselect(
        "Servers to compare", all_servers, default=all_servers,
        help="Each selected server runs as its own variant — only that server's "
             "tools are offered to the model.",
    )
    include_all = st.checkbox(
        "Also run with all servers (baseline)",
        help="Add an extra variant exposing every selected server's tools at once.",
    )
    st.caption(f"Comparing **{len(compare_servers)}** server(s)"
               + (" + an all-servers baseline" if include_all else "")
               + f" on **{_variant_label((chosen_provider, chosen_model))}**."
               if chosen_provider else "No models available.")
    if chosen_provider:
        bench_plan = [(chosen_provider, chosen_model, [s]) for s in compare_servers]
        if include_all and compare_servers:
            bench_plan.append((chosen_provider, chosen_model, list(compare_servers)))

col_a, col_b = st.columns(2)
label = col_a.text_input("Run label (optional)", placeholder="e.g. agiloft-v2")
notes = col_b.text_input("Notes (optional)")

run_clicked = st.button("▶ Run benchmark", type="primary",
                        disabled=not (prompt.strip() and bench_plan))

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

    run_id = db.create_benchmark_run(prompt, system_prompt_id, label or None,
                                     notes or None, mode=mode_key)
    progress = st.progress(0.0, text="Starting…")

    for i, (prov_name, model, variant_servers) in enumerate(bench_plan):
        servers_str = ",".join(variant_servers)
        # In servers mode the server set is what varies, so label progress by it.
        what = servers_str or "(no servers)" if mode_key == "servers" else f"{prov_name} · {model}"
        progress.progress(i / len(bench_plan), text=f"Running {what}…")
        try:
            provider = providers.get_provider(prov_name)
        except ValueError as e:
            # Missing key / unconfigured provider — record and keep going.
            logger.warning("Benchmark variant skipped (%s · %s): %s", prov_name, model, e)
            db.add_benchmark_variant(run_id, prov_name, model, None, None, "error",
                                     str(e), servers=servers_str)
            continue

        # Only this variant's servers' tools are offered to the model.
        variant_tools = [t for t in tools if server_of(t["name"]) in variant_servers]

        title = f"[bench #{run_id}] {model} — {prompt[:40]}"
        conv_id = db.create_conversation(title, prov_name, model, system_prompt_id)
        messages = [{"role": "user", "content": prompt}]
        db.add_message(conv_id, "user", prompt)
        try:
            final_text, total_ms = chat_runner.run_turn(
                client=client, provider=provider, provider_name=prov_name,
                model=model, messages=messages, tools=variant_tools, sys_prompt=sys_prompt,
                user_prompt=prompt, conv_id=conv_id, benchmark_run_id=run_id,
                debug_io=debug_io,
            )
            for m in messages[1:]:
                db.add_message(conv_id, m["role"], m["content"])
            db.add_benchmark_variant(run_id, prov_name, model, conv_id, total_ms, "ok",
                                     servers=servers_str)
        except Exception as e:  # noqa: BLE001
            logger.exception("Benchmark variant failed (run=%s %s %s servers=%s)",
                             run_id, prov_name, model, servers_str)
            db.add_log(conv_id, event_type="error", provider=prov_name, model=model,
                       user_prompt=prompt, benchmark_run_id=run_id)
            db.add_benchmark_variant(run_id, prov_name, model, conv_id, None, "error",
                                     str(e), servers=servers_str)

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

# Servers-mode runs vary by server; label/chart by that. Legacy runs (no mode)
# and model runs key by provider · model exactly as before.
run_mode = run.get("mode") or "models"
def _row_key(r: dict) -> str:
    if run_mode == "servers":
        return (r["servers"] or "(no servers)")
    return f"{r['provider']} · {r['model']}"

col_label = "Server(s)" if run_mode == "servers" else "Model"

st.dataframe(
    [
        {
            col_label: _row_key(r),
            "Status": r["status"],
            "Total time (s)": round((r["total_ms"] or 0) / 1000, 1),
            "Total tokens": r["total_tokens"],
            "Prompt tokens": r["prompt_tokens"],
            "Completion tokens": r["completion_tokens"],
            "LLM calls": r["llm_calls"],
            "LLM time (s)": round((r["llm_ms"] or 0) / 1000, 1),
            "Tool calls": r["tool_calls"],
            "Tool errors": r["tool_errors"],
            "Retries": r["retries"],
            "Est. cost ($)": fmt_cost(db.estimate_cost(
                r["provider"], r["model"], r["prompt_tokens"], r["completion_tokens"])),
            "Answer": r["answer"],
        }
        for r in rows
    ],
    width="stretch", hide_index=True,
)

# Charts: total tokens, total turn time, and estimated cost per variant.
ok_rows = [r for r in rows if r["status"] == "ok"]
if ok_rows:
    unit = "server" if run_mode == "servers" else "model"
    c1, c2, c3 = st.columns(3)
    with c1:
        st.caption(f"Total tokens per {unit}")
        st.bar_chart({_row_key(r): r["total_tokens"] for r in ok_rows})
    with c2:
        st.caption(f"Total turn time per {unit} (s)")
        st.bar_chart({_row_key(r): round((r["total_ms"] or 0) / 1000, 2)
                      for r in ok_rows})
    with c3:
        st.caption(f"Est. cost per {unit} ($)")
        st.bar_chart({_row_key(r): (db.estimate_cost(
            r["provider"], r["model"], r["prompt_tokens"], r["completion_tokens"]) or 0)
            for r in ok_rows})

# Full final answers for quality eyeballing.
st.markdown("**Final answers**")
for r in rows:
    header = _row_key(r)
    with st.expander(header + (f"  — ⚠️ {r['error']}" if r["status"] == "error" else "")):
        if r["status"] == "error":
            st.error(r["error"] or "Model failed.")
        elif r["conversation_id"]:
            answer = ""
            for m in reversed(db.get_messages(r["conversation_id"])):
                shown = display_text(m)
                if shown and shown[0] == "assistant" and shown[1]:
                    answer = shown[1]
                    break
            st.markdown(answer or "_(no text answer)_")

# Per-call detail for the whole run — same metrics as the Logs page, with a
# leading Variant column so each row is attributable to a model/server.
st.markdown("**Per-call detail for this run**")
with st.expander("🔍 Show every LLM & tool call in this run"):
    run_logs = db.benchmark_run_logs(run["id"])
    if run_logs:
        variant_label = {r["conversation_id"]: _row_key(r) for r in rows}
        st.dataframe(
            [
                {"Variant": variant_label.get(lg["conversation_id"], ""), **base}
                for lg, base in zip(run_logs, log_table_rows(run_logs))
            ],
            width="stretch", hide_index=True,
        )
    else:
        st.caption("No per-call logs recorded for this run.")
