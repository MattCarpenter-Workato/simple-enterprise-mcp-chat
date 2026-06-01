# Simple MCP Chat

A Python **web app** for chatting with AI models that can call tools from
[Workato Enterprise MCP](https://www.workato.com/) servers (or any MCP server).
Built with [Streamlit](https://streamlit.io/), it gives you a graphical chat
interface, point-and-click MCP server management, saved system prompts, secure-ish
credential storage, and built-in **token/latency benchmarking** so you can compare
models and MCP servers.

> Originally a set of command-line scripts, this project is now a single web app.
> The provider tool-calling logic lives in `providers/` + `mcp_core.py`.

**Supported AI providers** (pick per chat from the sidebar):
- **OpenAI** (GPT-4o, GPT-4o-mini, …) — cloud
- **Claude** (Anthropic) — cloud
- **Ollama** — local open-source models (llama3.2, mistral, qwen, …)
- **LM Studio** — local models via its OpenAI-compatible server

---

## Quick start

```bash
uv sync                       # install dependencies (incl. Streamlit)
uv run streamlit run app.py   # open http://localhost:8501
```

Then:
1. Open **⚙️ Settings** (left nav) and add at least one API key (e.g. OpenAI or Claude).
2. Open **🔌 MCP Servers** and add/enable a server (and authenticate if it uses OAuth).
3. Go back to the chat, pick a provider/model in the sidebar, and start chatting.

If you previously used the command-line version, your existing `.env`,
`mcp_servers.json`, and `.mcp_tokens.json` are **imported automatically** into the
database on first launch — your setup carries over with no manual steps.

---

## What it does

1. **Connects** to one or more MCP servers simultaneously.
2. **Discovers** the tools each server exposes (CRM data, spreadsheets, tickets, …).
3. **Chats** with an AI that automatically calls the right tools to answer you.

For example, with a Salesforce MCP server connected:
- "Show me my open opportunities over $50k"
- "What deals closed last week?"

With multiple servers (e.g. Salesforce + Google Sheets):
- "Pull my pipeline data and add it to my forecast spreadsheet"

The AI picks the right tools from the right servers and replies in natural language.
Tool names are automatically prefixed with the server name (e.g.
`salesforce__Query_Records`) to avoid conflicts.

---

## Key concepts

### What is MCP?
**MCP (Model Context Protocol)** is a standard way for AI models to use external
tools and data sources — a universal adapter that lets any AI talk to any service.

### What is Workato Enterprise MCP?
Workato provides hosted MCP servers that connect to enterprise services (CRMs,
databases, productivity tools) with OAuth 2.0 security, audit logging, and rate
limiting. This app works with those, and with any MCP server speaking JSON-RPC.

### What is tool (function) calling?
When you ask a question, the model decides whether it needs external data. If so it
names a tool to call; the app calls it on the MCP server, returns the result to the
model, and the model produces a human-readable answer — looping for multi-step
queries.

---

## Using the app

The app has a Chat page plus four pages in the left nav.

### 💬 Chat
- Pick **Provider** and **Model** in the sidebar, and optionally a saved **System
  prompt**.
- Each conversation is **locked to the provider it started with** (switching mid-chat
  would mix incompatible message formats). To use a different model, click **➕ New
  chat**.
- Conversations are saved automatically; reopen them from the sidebar.
- Expand **📊 Logs & usage (this chat)** to see token totals, LLM time, and a table
  of every call.

### 🔌 MCP Servers
Add, edit, enable/disable, and delete MCP servers. Per server you choose an auth type:
- **none** — no auth header
- **token** — a static `Authorization: Bearer <token>`
- **oauth** — browser-based OAuth 2.0 (see below); use the **🔐 Re-authenticate**
  button to (re)run the flow

### 📝 System Prompts
Create, edit, and delete reusable system prompts. The selected prompt is sent as the
system message for the chat.

### ⚙️ Settings
Store API keys and provider defaults (model names, Ollama/LM Studio base URLs), and
toggle date injection. Includes a **Legacy / unused secrets** cleanup and the ability
to clear individual secrets.

### 📊 Logs
Benchmark and inspect — see [Logging & benchmarking](#logging--benchmarking).

---

## Providers

Choose the provider/model in the sidebar; defaults are configured in **Settings**.

### OpenAI / Claude (cloud)
Add `OPENAI_API_KEY` and/or `CLAUDE_API_KEY` in Settings. Recommended models:
- OpenAI: `gpt-4o-mini` (fast/cheap), `gpt-4o`
- Claude: `claude-sonnet-4-5-20250929` (recommended), `claude-opus-4-1-20250805`,
  `claude-3-5-haiku-20241022`

### Ollama (local)
1. Install Ollama from [ollama.ai](https://ollama.ai) and ensure it's running
   (`curl http://localhost:11434/api/tags`).
2. Pull a model that supports **function calling**: `ollama pull llama3.2`
   (others: `mistral`, `qwen2.5`, `llama3.1`).
3. In Settings set `OLLAMA_BASE_URL` (default `http://localhost:11434`) and
   `OLLAMA_MODEL`.

> Not all Ollama models support tool calling. Use one that does (see
> [ollama.ai/library](https://ollama.ai/library)). Unlike the old CLI, the web app
> does not auto-pull models — pull them first.

### LM Studio (local)
1. Install [LM Studio](https://lmstudio.ai), load a function-calling-capable model,
   and start its local server.
2. In Settings set `LMSTUDIO_BASE_URL` (default `http://localhost:1234/v1`).

| Provider  | Cost            | Privacy | Notes                                   |
|-----------|-----------------|---------|-----------------------------------------|
| OpenAI    | Per token       | Cloud   | Fast, reliable                          |
| Claude    | Per token       | Cloud   | Strong reasoning, long context          |
| Ollama    | Free            | Local   | Open-source models, needs a capable GPU |
| LM Studio | Free            | Local   | OpenAI-compatible local server          |

---

## MCP server authentication

Configure servers on the **🔌 MCP Servers** page.

**Token-based** — paste the bearer token into the server's form; it's sent as
`Authorization: Bearer <token>`.

**OAuth 2.0** — set the auth type to `oauth` and click **🔐 Re-authenticate**. The app:
1. Auto-discovers OAuth endpoints via `.well-known/oauth-authorization-server`
2. Auto-registers an OAuth client via dynamic client registration (RFC 7591)
3. Opens your browser for authorization, with a local callback on port 8080
4. Exchanges the code for tokens using **PKCE** (RFC 7636)
5. Stores tokens in the database and refreshes them automatically

**Security features:** PKCE, dynamic client registration, automatic endpoint
discovery, and Bearer-token auth. Optional OAuth overrides (`client_id`,
`client_secret`, `scopes`, `redirect_port`, `auth_url`, `token_url`) can be supplied
as JSON in the server's OAuth config field if a server needs them.

---

## Logging & benchmarking

Every LLM call and MCP tool call is logged to SQLite (`chat_logs` table) — no log
files to manage. For each call the app records: provider, model, call type
(`initial_request` / `tool_followup`), token usage (prompt/completion/total), latency
in ms, the MCP server + tool used (with arguments) and the **size of data returned**,
plus a response preview.

**Where to see it:**
- **Per chat:** the *📊 Logs & usage* expander on the Chat page (token totals, LLM
  time, tool calls, full table).
- **📊 Logs page:**
  - **Per-conversation** detail table.
  - **Models** — tokens and average latency by provider/model (tune your model choice).
  - **MCP servers & tools** — call counts, average/max round-trip time, and average
    returned-data size (tune which servers/tools to keep).
  - Buttons to **clear one chat's logs** or **all logs**.

This makes cost/performance tradeoffs visible — e.g. spotting when a model issues a
broad MCP query that returns a huge payload, inflating the next call's prompt tokens
and latency.

### App log (file) vs conversation logs (DB)
Two distinct layers of observability:
- **Conversation logs** (above) live in the database — per-turn tokens, tools, and
  timing for *what happened in a chat*.
- **App log** is a rotating file, `logs/app.log`, capturing *whether the app itself
  is healthy* — errors, tracebacks, and MCP/OAuth failures. View or clear its tail
  from the **🐞 App log** section at the bottom of the Logs page; set the verbosity
  via **App log level** in Settings (restart to apply).

### Current date/time injection
With **"Inject current date/time"** enabled in Settings (default on), the current
date/time is appended to the system prompt so the model can resolve relative dates
("last 3 days", "this week"). Disable it for tests with historical data.

---

## Data & storage

Everything lives in a single SQLite database, **`mcp_chat.db`** (git-ignored):
servers, OAuth tokens, API keys/settings, saved system prompts, conversations,
messages, and logs.

> **Security note:** secrets are stored in `mcp_chat.db` as **plaintext** — the same
> exposure level as a `.env` file, just centralized. Keep the database out of version
> control (it's already in `.gitignore`).

On first launch the app imports any existing `.env`, `mcp_servers.json`, and
`.mcp_tokens.json`, then is fully DB-driven.

---

## Project structure

```
simple-mcp-chat/
├── app.py                     # Streamlit entry point + Chat page
├── pages/                     # MCP Servers, System Prompts, Settings, Logs
├── providers/                 # Unified chat backend (OpenAI-compatible + Claude)
├── mcp_core.py                # Shared MCP client (discover + call tools)
├── db.py                      # SQLite store (servers, tokens, keys, prompts, chats, logs)
├── oauth_store.py             # DB-backed OAuth handler (subclasses oauth_handler)
├── oauth_handler.py           # OAuth 2.0 / PKCE flow (auto-discovery + registration)
├── ui_common.py               # Shared Streamlit helpers
├── mcp_chat.db                # SQLite database (auto-generated, don't commit!)
├── mcp_servers.json           # Legacy seed config (optional, imported once)
├── mcp_servers.example.json   # Example server configuration
├── .env / env.example         # Legacy seed config / template
├── pyproject.toml / uv.lock   # Dependencies
└── README.md                  # You're reading it
```

---

## Prerequisites
- **Python 3.10+**
- **uv** package manager ([install](https://github.com/astral-sh/uv))
- An **AI provider**: an OpenAI or Claude API key, or a local Ollama / LM Studio
- One or more **MCP server URLs** (e.g. from your Workato workspace)

---

## Troubleshooting

**"No tools discovered" / a server fails**
Check the server URL on the MCP Servers page. For token auth, verify the token; for
OAuth, click **🔐 Re-authenticate**. Other servers keep working if one fails — the
chat caption surfaces per-server errors.

**401 Unauthorized**
- Token auth: the token likely expired — update it on the MCP Servers page.
- OAuth: click **🔐 Re-authenticate** to refresh the token.

**OAuth: "authentication failed"**
- Port 8080 in use → set a different `redirect_port` in the server's OAuth config.
- Browser didn't open → copy the URL printed in the terminal.
- Server doesn't support dynamic registration → provide `client_id`/`client_secret`
  in the OAuth config.

**"API key is not set"**
Add the provider's key in **⚙️ Settings**.

**Ollama: can't connect / model not found**
Ensure Ollama is running (`curl http://localhost:11434/api/tags`) and the model is
pulled (`ollama pull llama3.2`). Use a model that supports function calling.

**LM Studio: can't connect / tools not called**
Ensure LM Studio's local server is started and `LMSTUDIO_BASE_URL` matches. Load a
model that supports tool use (e.g. Mistral Instruct, Qwen, function-calling Llama).

**Can't switch model mid-conversation**
That's intentional — conversations are locked to their provider. Click **➕ New chat**.

---

## License

MIT
