# Simple MCP Chat

A Python **web app** for chatting with AI models that call tools from
[Workato Enterprise MCP](https://www.workato.com/) servers (or any MCP server), built to
**benchmark and optimize those servers/recipes across models** for token efficiency,
latency, and correctness.

Built with [Streamlit](https://streamlit.io/), it gives you a graphical chat interface,
a side-by-side **benchmarking workspace** (compare **models** *or* **MCP servers**),
point-and-click MCP server management, saved system prompts, secure-ish credential
storage, **per-model cost estimates**, and detailed per-call metrics. Pick which servers
and which model to use, run the same prompt across several models (or one model across
several servers), and see exactly what each costs in **dollars**, tokens, latency, and
tool reliability. Export a whole benchmark run as a ready-to-paste prompt for an external
LLM to analyze.

> Originally a set of command-line scripts, this project is now a single web app. The
> provider tool-calling logic lives in `providers/` + `mcp_core.py`; everything else
> (servers, credentials, prompts, conversations, logs, benchmarks) is persisted in SQLite.

**Supported AI providers** (pick per chat from the sidebar):
- **OpenAI** — cloud; model list **fetched live from the API**
- **Claude** (Anthropic) — cloud; model list **fetched live from the API**
- **Ollama** — local open-source models (llama3.2, mistral, qwen, …)
- **LM Studio** — local models via its OpenAI-compatible server

---

## Run with Docker (recommended — no coding needed)

This is the easiest way to run the app. **Docker** packages everything (Python,
Streamlit, and all dependencies) into one ready-to-run image, so the only thing you
install is Docker itself. Everything runs **on your own computer** and your data
stays there.

**1. Install Docker Desktop** (one time)
Download it for Windows or Mac from
<https://www.docker.com/products/docker-desktop/>, install it, then open it once and
wait until the whale icon stops animating — that means Docker is running.

**2. Get the `docker-compose.yml` file**
That single file is all you need (download it from this repo, or ask whoever shared
the app for it). Put it in a folder, e.g. `Documents/mcp-chat/`.

**3. Start the app**
Open a terminal **in that folder**:
- **Windows:** Shift + right-click the folder → *Open PowerShell window here*
- **Mac:** right-click the folder → *Services* → *New Terminal at Folder*

Then run:

```bash
docker compose up -d        # downloads the app the first time, then starts it
```

Open **http://localhost:8501** in your browser (bookmark it).

**4. First-time setup, in the browser**
1. **⚙️ Settings** → add an OpenAI and/or Claude API key → **Save**.
2. **🔌 MCP Servers** → add a server (name + URL + auth type).
3. Adding an **OAuth** server starts sign-in automatically — click the **🔐 sign-in link**
   that appears and log in (re-run later with **🔄 Reconnect MCP servers** if needed).
4. **💬 Home** → pick a model and start chatting.

**Everyday use**

```bash
docker compose down                          # stop the app (your data is kept)
docker compose up -d                         # start it again later
docker compose pull && docker compose up -d  # update to the newest version
```

**Where's my data?** Conversations, API keys, servers, sign-ins, and logs are saved
in a **`data/` folder next to your `docker-compose.yml`** (the database, OAuth tokens,
and logs), so they survive restarts and updates and are easy to back up or move.
(Deleting that folder erases everything.)

**If something goes wrong**
- *"Cannot connect to the Docker daemon" / nothing happens* — Docker Desktop isn't
  running. Start it, wait for the whale icon to settle, and try again.
- *Port already in use* — something else is using `8501` or `8080`. Edit the `ports:`
  lines in `docker-compose.yml` (keep `8080` mapped — it's needed for OAuth sign-in).
- *Local AI servers (Ollama / LM Studio)* — inside Docker, `localhost` means the
  container, not your computer. In **Settings**, point their URLs at
  `host.docker.internal`, e.g. `http://host.docker.internal:11434`.

> The same quick-start also appears on the image's
> [Docker Hub page](https://hub.docker.com/r/mattcarpenterwkto/simple-enterprise-mcp-chat).

---

## Run from source (for developers)

```bash
uv sync                       # install dependencies (incl. Streamlit)
uv run streamlit run app.py   # open http://localhost:8501
```

Then:
1. Open **⚙️ Settings** (left nav) and add at least one API key (e.g. OpenAI or Claude).
2. Open **🔌 MCP Servers**, add/enable a server, and authenticate if it uses OAuth.
3. Go back to **💬 Home**, pick a provider/model and which servers to use, and start chatting.
4. Open **⚗️ Benchmark** to run one prompt across several models or MCP servers and compare them.

If you previously used the command-line version, your existing `.env` and
`mcp_servers.json` (if present) are **imported automatically** into the database on first
launch — your setup carries over with no manual steps. This import is one-time; afterward
the app is fully database-driven. (OAuth tokens aren't imported; click **🔐 Re-authenticate**
on the MCP Servers page once.)

---

## What it does

1. **Connects** to one or more MCP servers simultaneously.
2. **Discovers** the tools each server exposes (CRM data, spreadsheets, tickets, …).
3. **Chats** with an AI that automatically calls the right tools to answer you.
4. **Measures** every LLM and tool call so you can tune which servers/recipes and models
   give the best answer for the fewest tokens and least latency.

For example, with a Salesforce MCP server connected:
- "Show me my open opportunities over $50k"
- "What deals closed last week?"

With multiple servers (e.g. Salesforce + Google Sheets):
- "Pull my pipeline data and add it to my forecast spreadsheet"

The AI picks the right tools from the right servers and replies in natural language. Tool
names are automatically prefixed with the server name (e.g. `salesforce__Query_Records`)
to avoid conflicts — which also lets the app filter the tools offered to the model down to
the servers you select.

---

## Key concepts

### What is MCP?
**MCP (Model Context Protocol)** is a standard way for AI models to use external tools and
data sources — a universal adapter that lets any AI talk to any service.

### What is Workato Enterprise MCP?
Workato provides hosted MCP servers that connect to enterprise services (CRMs, databases,
productivity tools) with OAuth 2.0 security, audit logging, and rate limiting. This app
works with those, and with any MCP server speaking JSON-RPC.

### What is tool (function) calling?
When you ask a question, the model decides whether it needs external data. If so it names a
tool to call; the app calls it on the MCP server, returns the result to the model, and the
model produces a human-readable answer — looping for multi-step queries.

---

## Using the app

The app has a Chat page plus five more pages in the left nav, in this order: **💬 Home**,
**⚗️ Benchmark**, **🔌 MCP Servers**, **📝 System Prompts**, **⚙️ Settings**, **📊 Logs**.

### 💬 Home (Chat)
- **Provider** and **Model** pickers in the sidebar. For OpenAI and Claude the model list is
  **fetched live from the provider API** (cached). Only models that have a **price** are
  offered (set/adjust prices on the Settings page); local Ollama/LM Studio models always
  show. Re-fetch the live lists with **🔄 Refresh models** on the **⚙️ Settings** page.
- **MCP servers** — a multiselect that picks which servers' tools are offered to the model.
  Use 1, 2, or all of them; defaults to all enabled servers.
- **System prompt** — optionally apply a saved prompt (or "(none)").
- Each conversation is **locked to the provider it started with** (switching mid-chat would
  mix incompatible message formats). To use a different model, click **➕ New chat**.
- Conversations are saved automatically; reopen or delete them from the sidebar.
- A status caption shows the active provider/model and the selected server/tool counts, plus
  a **💲 Est. cost so far** for the conversation; per-server discovery errors surface as a
  warning (fix them on the MCP Servers page).
- While the model works, a **live status panel** shows each tool call and a preview of its
  result.
- Expand **📊 Logs & usage (this chat)** to see token totals, LLM time, tool-call count,
  **estimated cost**, and a table of every call (provider, call type, prompt/completion
  tokens, duration, result size, **success/error**, **retry attempt**, server, tool
  **arguments**, and a preview).

### ⚗️ Benchmark
Run **one prompt** across several variants, then compare them side by side — the core tuning
loop. Two modes (a **Compare** toggle):

- **Models** — run the prompt across multiple **(provider × model)** variants against a chosen
  set of MCP servers. Find the cheapest/fastest model that still answers well.
- **MCP servers** — fix one model and run **one variant per MCP server** (optionally plus an
  "all servers" baseline). See how a model behaves with each server in isolation (tool
  reliability, latency, answer quality).

Steps: enter the **prompt**, pick a **system prompt**, choose the variants (models or servers
per the mode), optionally add a **label** and **notes**, then click **▶ Run benchmark**.

Each variant runs in its own conversation tagged with a `benchmark_run_id`; a progress bar
tracks the run. The **comparison** shows, per variant: **total turn time**, total / prompt /
completion **tokens**, LLM calls and LLM time, **tool calls**, **tool errors**, **retries**,
**estimated cost ($)**, and the **final answer** (expandable, for the quality check), plus
bar charts of tokens, total time, and cost. Below it:

- **🔍 Per-call detail for this run** — every LLM and tool call across all variants (same
  columns as the Logs page, with a leading **Variant** column).
- **🧠 Export for LLM analysis** — a one-click **📋 Copy to clipboard** button that copies a
  single **JSON** payload (analysis instructions + run metadata + per-variant metrics & cost
  + every per-call row + final answers), plus a preview/download. Paste it into any LLM to get
  a full analysis of the run. (Copy happens in the browser, so it works in Docker too.)

A variant with a missing API key is reported as failed rather than crashing the run. Pick a
past run from the **run selector** to view (and export) its data. Change a recipe or switch a
model/server, re-run the same prompt, and see what got cheaper/faster without hurting the
answer.

### 🔌 MCP Servers
Add, edit, enable/disable, and delete MCP servers. Per server you choose an auth type:
- **none** — no auth header
- **token** — a static `Authorization: Bearer <token>`
- **oauth** — browser-based OAuth 2.0 (see below)

- **Adding an OAuth server starts authentication automatically** — a **🔐 sign-in link**
  appears (and the browser opens when running natively); finish login and you're connected.
- **🔄 Reconnect MCP servers** (top of the page) — authenticates any enabled OAuth server
  lacking a valid token and re-discovers tools.
- For each OAuth server the page shows the stored token's expiry (or "no token yet") and a
  **🔐 Re-authenticate** button to (re)run the flow; a sign-in link is shown so it works
  whether or not a browser opens (e.g. in Docker). Optional OAuth overrides can be supplied
  as JSON in the server's config field.

### 📝 System Prompts
Create, edit, and delete reusable system prompts in a Markdown editor with a **live preview**.
Click **💾 Save** to add a new prompt — the fields clear automatically so you're ready for the
next one. The selected prompt is sent as the system message for the chat.

### ⚙️ Settings
- **API keys** — add `OPENAI_API_KEY` / `CLAUDE_API_KEY` (current values shown masked; leave a
  field blank to keep it unchanged).
- **Provider defaults** — `OPENAI_MODEL`, `CLAUDE_MODEL`, `OLLAMA_BASE_URL`, `OLLAMA_MODEL`,
  `LMSTUDIO_BASE_URL`, `LMSTUDIO_MODEL`, and `APP_LOG_LEVEL`.
- **Behavior** — toggle **Inject current date/time** into the system prompt (default on) and
  **Debug: log full tool call & response** to the app log file (default off).
- **Models** — **🔄 Refresh models** re-fetches the live Claude/OpenAI model lists.
- **Model pricing** — an editable table of per-model cost rates (USD per **1M tokens**, input
  and output, **Claude & OpenAI only**). Seeded with known rates; add/edit/delete rows. A model
  matches by exact ID, then by the longest **family prefix** (so `claude-sonnet-4` also prices
  dated snapshots like `claude-sonnet-4-5-20250929`). Models discovered without a price are
  auto-added here as blank rows to fill in — and only **priced** models appear in the chat /
  benchmark dropdowns.
- **Maintenance** — **clear a stored secret**, **clear all auth tokens** (deletes OAuth
  tokens/registrations and re-discovers tools), or **clear all benchmark runs** (all guarded by
  a confirmation).

### 📊 Logs
Browse and benchmark — see [Logging & benchmarking](#logging--benchmarking). Includes a
global CSV-exportable log table, per-conversation detail, model and MCP-server/tool comparison
charts, an app-log viewer, and guarded buttons to clear one chat's logs, all logs, or all
conversations.

---

## Providers

Choose the provider/model in the sidebar; defaults are configured in **Settings**.

### OpenAI / Claude (cloud)
Add `OPENAI_API_KEY` and/or `CLAUDE_API_KEY` in Settings. The model dropdown is **fetched
live from the provider API** (`/v1/models`) and reflects exactly what your key can access — no
hardcoded list to maintain. OpenAI results are filtered to chat-capable models and dated
snapshots (e.g. `gpt-4o-2024-08-06`) are hidden in favor of their rolling aliases (`gpt-4o`);
the list is cached and refreshable via **🔄 Refresh models** on the **⚙️ Settings** page. Only
models that have a **price** (Settings → Model pricing) are offered in the dropdowns; unpriced
ones are parked in the pricing table for you to fill in. If the API is unreachable or no key is
set, the dropdown falls back to a small built-in list.

### Ollama (local)
1. Install Ollama from [ollama.ai](https://ollama.ai) and ensure it's running
   (`curl http://localhost:11434/api/tags`).
2. Pull a model that supports **function calling**: `ollama pull llama3.2`
   (others: `mistral`, `qwen2.5`, `llama3.1`).
3. In Settings set `OLLAMA_BASE_URL` (default `http://localhost:11434`) and `OLLAMA_MODEL`.

> Not all Ollama models support tool calling. Use one that does (see
> [ollama.ai/library](https://ollama.ai/library)). The web app does not auto-pull models —
> pull them first.

### LM Studio (local)
1. Install [LM Studio](https://lmstudio.ai), load a function-calling-capable model, and start
   its local server.
2. In Settings set `LMSTUDIO_BASE_URL` (default `http://localhost:1234/v1`).

> Ollama and LM Studio use their configured/static model names rather than live API discovery.

| Provider  | Cost            | Privacy | Notes                                   |
|-----------|-----------------|---------|-----------------------------------------|
| OpenAI    | Per token       | Cloud   | Fast, reliable; live model list         |
| Claude    | Per token       | Cloud   | Strong reasoning, long context; live list |
| Ollama    | Free            | Local   | Open-source models, needs a capable GPU |
| LM Studio | Free            | Local   | OpenAI-compatible local server          |

---

## MCP server authentication

Configure servers on the **🔌 MCP Servers** page.

**Token-based** — paste the bearer token into the server's form; it's sent as
`Authorization: Bearer <token>`.

**OAuth 2.0** — set the auth type to `oauth`. Authentication starts **automatically when you
add the server** (and can be re-run anytime with **🔐 Re-authenticate** or **🔄 Reconnect MCP
servers**). The app:
1. Auto-discovers OAuth endpoints via `.well-known/oauth-authorization-server`.
2. Auto-registers an OAuth client via dynamic client registration (RFC 7591).
3. Shows a **sign-in link** (and opens your browser when running natively), with a local
   callback (default port 8080).
4. Exchanges the code for tokens using **PKCE** (RFC 7636).
5. Stores tokens in the database and refreshes them automatically.

If a request later returns **401**, the app silently refreshes the token once and retries
before surfacing an error. Optional OAuth overrides (`client_id`, `client_secret`, `scopes`,
`redirect_port`, `auth_url`, `token_url`) can be supplied as JSON in the server's OAuth config
field if a server needs them.

> **Docker note:** OAuth works when the container runs on the **same machine** as your
> browser (the default local setup). The browser is redirected to `http://localhost:8080/
> callback`, which reaches the container via the published port — keep **8080** mapped.

---

## Logging & benchmarking

Every LLM call and MCP tool call is logged to SQLite (`chat_logs` table) — no log files to
manage. For each call the app records: provider, model, call type (`initial_request` /
`tool_followup`), token usage (prompt / completion / total), latency in ms (LLM response time
*and* MCP round-trip time), the MCP server + tool used (with arguments) and the **size of data
returned**, plus a response preview. Tool calls additionally record **success/error**, the
**retry attempt** number (Nth call of that tool within the turn; `>1` marks a retry), and a
`benchmark_run_id` when part of a benchmark. The shared turn runner also measures **total turn
time** (end-to-end wall clock for one user message). A Workato **job ID** is auto-detected from
tool response headers/body when present.

**Where to see it:**
- **Per chat:** the *📊 Logs & usage* expander on the Chat page (token totals, LLM time, tool
  calls, **estimated cost**, and a full per-call table), plus a **💲 Est. cost so far** caption.
- **⚗️ Benchmark page:** side-by-side variant comparison for one prompt — total turn time,
  tokens, tool calls/errors, retries, **estimated cost**, and final answers; a **per-call
  detail** table; and a one-click **JSON export** for external-LLM analysis (see *Using the
  app*).
- **📊 Logs page:**
  - A global, CSV-exportable table of every log row.
  - **Per-conversation** metrics + detail table. The per-call tables (chat, per-conversation,
    benchmark) share one column set: provider, call type, prompt/completion/total tokens,
    duration, result size, success/error, attempt, server, tool **arguments**, and preview.
  - **Models** — tokens and average latency by provider/model (tune your model choice).
  - **MCP servers & tools** — call counts, average/max round-trip time, and average
    returned-data size (tune which servers/tools to keep).
  - Buttons to **clear one chat's logs**, **clear all logs**, or **delete all conversations**.

This makes cost/performance tradeoffs visible — e.g. spotting when a model issues a broad MCP
query that returns a huge payload, inflating the next call's prompt tokens and latency.

### App log (file) vs conversation logs (DB)
Two distinct layers of observability:
- **Conversation logs** (above) live in the database — per-turn tokens, tools, timing, and
  reliability for *what happened in a chat*.
- **App log** is a rotating file, `logs/app.log` (1 MB × 3 backups), capturing *whether the app
  itself is healthy* — errors, tracebacks, and MCP/OAuth/tool failures. Every error surfaced in
  the UI is also written here. View or clear its tail from the **🐞 App log** section at the
  bottom of the Logs page; set verbosity via **App log level** in Settings (restart to apply).

**Full tool-I/O debug (opt-in):** enable **"Debug: log full tool call & response to the app log
file"** in Settings to write each MCP tool call's complete arguments, response headers, body,
and any detected Workato job ID to `logs/app.log`. It's off by default (the payloads can be
large); the database always keeps only a concise preview.

### Current date/time injection
With **"Inject current date/time"** enabled in Settings (default on), the current date/time is
appended to the system prompt so the model can resolve relative dates ("last 3 days", "this
week"). Disable it for tests with historical data.

---

## Data & storage

Everything lives in a single SQLite database, **`mcp_chat.db`** (git-ignored). Its tables:

| Table | Holds |
|-------|-------|
| `servers` | MCP server configs (name, URL, auth type, enabled, OAuth config) |
| `oauth_tokens` | OAuth access/refresh tokens + client credentials, per server |
| `secrets` | API keys and settings (key/value) |
| `system_prompts` | Saved, reusable system prompts |
| `conversations` | Chat sessions (locked to a provider/model) |
| `messages` | Full message history (provider-native format) |
| `chat_logs` | Per-call metrics: tokens, latency, data size, success/retry, arguments, etc. |
| `benchmark_runs` | One benchmark run (prompt + label + notes + mode: models/servers) |
| `benchmark_variants` | Per-variant result of a run (provider/model, servers, status, total time, conversation link) |
| `model_prices` | Per-model cost rates (USD per 1M input/output tokens), seeded + editable |

The schema is created on first run; new columns added in later versions are applied with an
idempotent `ALTER TABLE` migration, so existing databases upgrade in place.

> **Security note:** secrets are stored in `mcp_chat.db` as **plaintext** — the same exposure
> level as a `.env` file, just centralized. Keep the database out of version control (it's
> already in `.gitignore`).

On first launch the app imports any existing `.env` and `mcp_servers.json`, then is fully
DB-driven. The database and `logs/` live next to the code by default; set the
**`MCP_CHAT_DATA_DIR`** environment variable to relocate all persistent state (the Docker
image points it at the mounted `/app/data` volume).

---

## Project structure

```
simple-mcp-chat/
├── app.py                     # Streamlit entry point + Chat page
├── pages/                     # Benchmark, MCP Servers, System Prompts, Settings, Logs
├── providers/                 # Provider catalog + live model fetch + chat backends
│   ├── __init__.py            #   registry, get_provider(), fetch_models()
│   ├── base.py                #   Provider interface (chat_turn)
│   ├── claude.py              #   Anthropic Claude provider
│   └── openai_like.py         #   OpenAI / Ollama / LM Studio provider
├── chat_runner.py             # Shared turn runner (logging, success/retry, total time)
├── mcp_core.py                # Shared MCP client (discover + call tools, job-id detection)
├── db.py                      # SQLite store (servers, tokens, keys, prompts, chats, logs, benchmarks)
├── oauth_store.py             # OAuth 2.0 / PKCE flow with DB-backed token storage
├── logging_setup.py           # Rotating app-log file configuration
├── ui_common.py               # Shared Streamlit helpers (nav, MCP discovery, model lists)
├── Dockerfile                 # Container image (Alpine + uv); CMD runs Streamlit
├── docker-compose.yml         # Local run: ports 8501/8080, ./data volume
├── .dockerignore              # Keeps local state/secrets out of the image
├── DOCKERHUB.md               # Paste-ready text for the Docker Hub repo page
├── data/                      # Runtime state when using Docker (DB + logs; git-ignored)
├── mcp_chat.db                # SQLite database for `uv run` (auto-generated, don't commit!)
├── mcp_servers.json           # Optional seed config (imported once if present)
├── .env                       # Optional seed config (imported once if present)
├── pyproject.toml / uv.lock   # Dependencies
└── README.md                  # You're reading it
```

---

## Prerequisites
- **Python 3.10+**
- **uv** package manager ([install](https://github.com/astral-sh/uv))
- An **AI provider**: an OpenAI or Claude API key, or a local Ollama / LM Studio
- One or more **MCP server URLs** (e.g. from your Workato workspace)

Dependencies (from `pyproject.toml`): `openai`, `anthropic`, `python-dotenv`, `requests`,
`streamlit`, `urllib3` (≥2.7, security floor). Or just use Docker — no Python/uv needed.

---

## Troubleshooting

**"No tools discovered" / a server fails**
Check the server URL on the MCP Servers page. For token auth, verify the token; for OAuth,
click **🔐 Re-authenticate**. Other servers keep working if one fails — the chat caption
surfaces per-server errors.

**401 Unauthorized**
- Token auth: the token likely expired — update it on the MCP Servers page.
- OAuth: the app auto-refreshes once; if that fails, click **🔐 Re-authenticate**.

**OAuth: "authentication failed"**
- Browser didn't open → click the **🔐 sign-in link** shown in the UI.
- Port 8080 in use → set a different `redirect_port` in the server's OAuth config (in Docker,
  also publish that port in `docker-compose.yml`).
- Server doesn't support dynamic registration → provide `client_id`/`client_secret` in the
  OAuth config.

**A model is missing from the dropdown**
Only **priced** Claude/OpenAI models are shown. Open **⚙️ Settings → Model pricing** and give
the model input/output rates (it's auto-listed there once discovered); it then appears in the
chat and benchmark pickers. Local Ollama/LM Studio models are always shown.

**Model dropdown is empty or out of date**
Click **🔄 Refresh models** on the **⚙️ Settings** page to re-fetch from the provider API. With
no key or when offline, the list falls back to a small built-in set.

**"API key is not set"**
Add the provider's key in **⚙️ Settings**.

**Ollama: can't connect / model not found**
Ensure Ollama is running (`curl http://localhost:11434/api/tags`) and the model is pulled
(`ollama pull llama3.2`). Use a model that supports function calling.

**LM Studio: can't connect / tools not called**
Ensure LM Studio's local server is started and `LMSTUDIO_BASE_URL` matches. Load a model that
supports tool use (e.g. Mistral Instruct, Qwen, function-calling Llama).

**Can't switch model mid-conversation**
That's intentional — conversations are locked to their provider. Click **➕ New chat**.

---

## License

MIT
