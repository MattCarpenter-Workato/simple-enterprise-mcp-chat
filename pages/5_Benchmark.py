"""Benchmarking workspace.

Run one prompt across several (provider, model) variants against the current MCP
servers, then compare tokens / latency / total turn time / tool reliability side by
side. This is the core tuning workflow: change a recipe or model, re-run the same
prompt, and see what got cheaper/faster without hurting the answer.
"""

import json
import logging

import streamlit as st

import chat_runner
import db
import providers
from chat_runner import server_of
from ui_common import (init_app, render_nav, effective_system_prompt,
                       display_text, get_client_and_tools, server_signature,
                       selectable_models, log_table_rows, fmt_cost, copy_button)

st.set_page_config(page_title="Benchmark", page_icon="⚗️", layout="wide")
init_app()
render_nav()

logger = logging.getLogger("mcpchat.benchmark")

# Instruction text bundled into the export payload so an external LLM knows how to
# analyze the run (the export is JSON-only; this lives in its `instructions` field).
_ANALYSIS_INSTRUCTIONS = (
    "You are an expert evaluator of LLM + MCP-tool benchmark runs. Analyze EVERY part "
    "of the benchmark run in the JSON below and produce a thorough, structured report. "
    "`run.mode` is 'models' (variants differ by provider/model, sharing servers) or "
    "'servers' (one fixed model, one variant per MCP server) — frame the comparison "
    "accordingly. For every variant, assess and compare: cost (est_cost_usd) and token "
    "efficiency (prompt/completion/total tokens); latency (total_ms end-to-end and "
    "llm_ms model time, noting tool overhead); tool reliability (tool_calls vs "
    "tool_errors and retries — call out failures); and answer quality/correctness "
    "(read each variant's final_answer against run.prompt). Use the per-call `calls` "
    "data to explain WHY a variant was slow or expensive — e.g. oversized tool results "
    "(data_chars) inflating later prompt tokens, repeated/retried tool calls, failed "
    "calls (success=false, see error), or unusually slow calls. Then deliver: (1) the "
    "best variant for cost, for speed, and overall best tradeoff, each justified with "
    "numbers; (2) concrete tuning recommendations (which model/server to keep, prompt "
    "or tool changes); (3) anomalies or data-quality caveats."
)


def _final_answer(conversation_id) -> str:
    """Last assistant text for a variant's conversation (for the export payload)."""
    if not conversation_id:
        return ""
    for m in reversed(db.get_messages(conversation_id)):
        shown = display_text(m)
        if shown and shown[0] == "assistant" and shown[1]:
            return shown[1]
    return ""


def _call_arguments(detail_json):
    if not detail_json:
        return None
    try:
        return json.loads(detail_json).get("arguments")
    except (json.JSONDecodeError, TypeError):
        return None


def _call_preview(lg: dict) -> str:
    if lg["response_preview"]:
        return lg["response_preview"]
    if lg["detail_json"]:
        try:
            return json.loads(lg["detail_json"]).get("result_preview", "")
        except (json.JSONDecodeError, TypeError):
            return ""
    return ""


def _build_run_export(run: dict, rows: list[dict], row_key) -> str:
    """Assemble the whole run (instructions + metadata + per-variant aggregates +
    every per-call row + final answers) into one JSON string for an external LLM."""
    sp = db.get_prompt(run["system_prompt_id"]) if run.get("system_prompt_id") else None
    variants = [
        {
            "label": row_key(r),
            "provider": r["provider"], "model": r["model"], "servers": r["servers"],
            "status": r["status"], "error": r["error"], "total_ms": r["total_ms"],
            "prompt_tokens": r["prompt_tokens"], "completion_tokens": r["completion_tokens"],
            "total_tokens": r["total_tokens"], "llm_calls": r["llm_calls"],
            "llm_ms": r["llm_ms"], "tool_calls": r["tool_calls"],
            "tool_errors": r["tool_errors"], "retries": r["retries"],
            "est_cost_usd": db.estimate_cost(r["provider"], r["model"],
                                             r["prompt_tokens"], r["completion_tokens"]),
            "final_answer": _final_answer(r["conversation_id"]),
        }
        for r in rows
    ]
    label_by_conv = {r["conversation_id"]: row_key(r) for r in rows}
    calls = [
        {
            "variant": label_by_conv.get(lg["conversation_id"], ""),
            "event_type": lg["event_type"], "provider": lg["provider"], "model": lg["model"],
            "call_type": lg["call_type"], "prompt_tokens": lg["prompt_tokens"],
            "completion_tokens": lg["completion_tokens"], "total_tokens": lg["total_tokens"],
            "duration_ms": lg["duration_ms"], "data_chars": lg["data_chars"],
            "success": lg["success"], "error": lg["error"], "attempt": lg["attempt"],
            "server": lg["server"], "tools": lg["tools"],
            "arguments": _call_arguments(lg["detail_json"]), "preview": _call_preview(lg),
        }
        for lg in db.benchmark_run_logs(run["id"])
    ]
    payload = {
        "instructions": _ANALYSIS_INSTRUCTIONS,
        "run": {
            "id": run["id"], "created_at": run["created_at"], "label": run["label"],
            "notes": run["notes"], "mode": run.get("mode") or "models",
            "prompt": run["prompt"],
            "system_prompt": ({"id": sp["id"], "name": sp["name"], "content": sp["content"]}
                              if sp else None),
        },
        "variants": variants,
        "calls": calls,
    }
    return json.dumps(payload, indent=2, default=str)


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

# All selectable variants: every model under every provider. For Claude/OpenAI only
# priced models are offered (unpriced ones are parked in Settings → Model pricing);
# local providers show everything.
VARIANTS: list[tuple[str, str]] = [
    (p, m) for p in providers.PROVIDER_NAMES
    for m in selectable_models(p)
]
def _variant_label(v: tuple[str, str]) -> str:
    return f"{v[0]} · {v[1]}"

st.caption("Claude/OpenAI models without a price are hidden — add prices in "
           "⚙️ Settings → Model pricing.")

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

# Export the whole run as a JSON analysis prompt for an external LLM.
st.markdown("### 🧠 Export for LLM analysis")
st.caption("Copies a single JSON payload — analysis instructions plus this run's full "
           "data (metadata, per-variant metrics & cost, every LLM/tool call, and final "
           "answers) — to paste into any LLM.")
_export = _build_run_export(run, rows, _row_key)
copy_button(_export, key=f"bench_{run['id']}")
with st.expander("Preview / download JSON"):
    st.download_button("⬇ Download JSON", _export,
                       file_name=f"benchmark_run_{run['id']}.json",
                       mime="application/json", key=f"dl_bench_{run['id']}")
    st.code(_export, language="json")

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
