# MCP Tuning Metrics

This app logs every LLM call and MCP tool call so you can tune **Workato MCP
servers and recipes** for **token efficiency, cost, latency, and correct results**.
Every metric below is stored per call in SQLite (`chat_logs`) and exportable to CSV
from the Logs page.

> Legend: ✅ = captured today &nbsp;·&nbsp; ➕ = to add in the capture phase.

## How a turn produces metrics

One user message ("turn") generates a chain of logged events:

```
user prompt
  └─ llm_call (initial_request)      ← model decides which tool(s) to call
       └─ tool_call  (MCP round trip)  ← recipe runs, returns data
  └─ llm_call (tool_followup)        ← model reads the data, answers or calls again
       └─ tool_call ...                ← repeats if the result wasn't good enough
  └─ final answer
```

`event_type` is `llm_call`, `tool_call`, or `error`. All rows from one turn share a
`turn_id`, so a turn can be reconstructed and its total cost/latency/round-count
measured.

---

## 1. Token metrics — *the cost driver*

| Metric | What it is | Status |
|---|---|---|
| `prompt_tokens` | Tokens sent to the model on a call (system + history + tool results) | ✅ |
| `completion_tokens` | Tokens the model generated | ✅ |
| `total_tokens` | Sum | ✅ |
| `result_tokens_est` | ≈ tokens a single tool result added (`chars/4`) | ➕ |

**How it helps tune Workato:** prompt tokens on a `tool_followup` call are dominated
by the **tool result payload**. If a recipe returns 35k characters, the next call
pays ~9k prompt tokens for it. Watching `tool_followup` `prompt_tokens` vs the tool's
`data_chars` tells you exactly which recipe is bloating context — the #1 lever for
cost reduction is making the recipe return **less** (filters, field selection,
pagination, summaries).

---

## 2. Latency metrics — *MCP vs model*

| Metric | What it is | Status |
|---|---|---|
| `duration_ms` (on `tool_call`) | **MCP round-trip** time: recipe execution + network | ✅ |
| `duration_ms` (on `llm_call`) | **LLM** response time | ✅ |

**How it helps tune Workato:** splitting the two answers "is the slow part the recipe
or the model?" A slow `tool_call` points at recipe steps (lookups, joins, external
calls) to optimize; a slow `tool_followup` `llm_call` usually means the payload was
huge (tie back to token/data metrics). Looking at **max/p95** (not just averages)
surfaces the occasional expensive call that an average hides.

---

## 3. Payload / data metrics — *over-fetching detector*

| Metric | What it is | Status |
|---|---|---|
| `data_chars` | Size of the tool result (characters) | ✅ |
| `data_bytes` | Size in bytes (truer measure for non-ASCII) | ➕ |
| `result_items` | **Records the recipe returned** (length of the result's primary list, e.g. `contracts[]`) | ➕ |

**How it helps tune Workato:** `result_items` vs how many the answer actually used
reveals **over-fetching** — e.g. the recipe returns 200 rows but the question needed
3. Each unused row costs tokens and latency. Fixes: tighter query arguments, a
`limit`, server-side filtering, or returning only needed fields. `data_bytes` /
`data_chars` quantify payload weight; `result_tokens_est` (above) converts it to the
token cost it imposes downstream.

---

## 4. Reliability & retry metrics — *wasted round-trips*

| Metric | What it is | Status |
|---|---|---|
| `success` | 1 if the tool returned a usable result, 0 on error | ➕ |
| `error` | Error text when `success=0` | ➕ |
| `attempt` | Nth call of **this tool within the turn** (`>1` = a retry) | ➕ |
| `turn_id` | Groups all calls of one user turn (→ rounds per turn) | ➕ |

**How it helps tune Workato:** retries and extra rounds are pure waste — every retry
re-pays tokens and latency. `attempt > 1` with the prior attempt `success=1` but
`result_items=0` means the recipe returned *nothing useful* and the model had to try
again — a sign to improve the recipe's result or its **tool description/schema** so
the model queries it correctly the first time. A high error rate per tool points at a
flaky recipe. Counting `llm_call`s per `turn_id` shows how many round-trips a task
took (fewer = more efficient).

---

## 5. Identity & grouping — *makes everything comparable*

| Metric | What it is | Status |
|---|---|---|
| `created_at` | Timestamp | ✅ |
| `conversation_id` | Which chat | ✅ |
| `provider` / `model` | Which LLM ran the call | ✅ |
| `server` / `tools` | Which MCP server + tool (recipe) | ✅ |
| `arguments` | The exact arguments the model passed (in `detail_json`) | ✅ |
| `run_tag` | Iteration label (e.g. `agiloft-v1`, `v2`) | ➕ |
| `workato_job_id` | Correlation id to Workato job logs, when the response exposes one | ➕ |

**How it helps tune Workato:** `arguments` shows whether the model issued a **broad
vs narrow query** — the root cause behind payload size and token cost. `run_tag` is
what lets you **A/B compare**: tag a run, change the recipe, re-run the same prompt
under a new tag, and compare tokens/$/latency/quality before vs after.
`workato_job_id` (when present) links a call straight to the recipe's job run for
deep debugging.

---

## 6. Derived metrics (computed from the above — not stored)

These are calculated in the Logs/tuning views, not captured per row:

- **Cost ($)** = `prompt_tokens × input_rate + completion_tokens × output_rate` (per
  model). Turns tokens into money per call / tool / conversation / run.
- **tokens-per-1K-chars** = efficiency of a recipe's payload (lower is leaner).
- **p95 / max latency** = tail performance, per tool and per model.
- **Tool rounds & retry count per turn** = `turn_id` grouping of `llm_call` /
  `attempt`.
- **👍 rate (quality)** = from manual ratings, to ensure token cuts don't hurt answers.

---

## 7. Tuning playbook (how to read the metrics)

| Symptom in the data | Likely cause | Recipe/MCP fix |
|---|---|---|
| High `tool_followup` `prompt_tokens` + high `data_chars` | Recipe returns too much | Add filters / field selection / `limit` / summarize |
| Large `result_items`, few used in the answer | Over-fetching | Narrow query args; server-side filter; paginate |
| `attempt > 1` often | First result poor/empty/wrong shape | Improve recipe output + tool description/schema |
| High tool-call `duration_ms` | Slow recipe steps | Optimize lookups/joins/external calls |
| High error rate (`success=0`) | Flaky recipe / bad inputs | Harden recipe; validate args |
| `v2` run shows fewer tokens/$ but lower 👍 rate | Optimization hurt quality | Re-balance: keep needed fields |

**Goal:** the fewest tokens, lowest latency, and lowest $ per turn that still produce
a 👍 result — verified by comparing `run_tag`s before and after each recipe change.
