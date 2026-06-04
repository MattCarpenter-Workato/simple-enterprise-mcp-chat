<!--
Paste-ready text for the Docker Hub repository page
(https://hub.docker.com/r/mattcarpenterwkto/simple-enterprise-mcp-chat).

- "Short description" field  -> use the one line under SHORT DESCRIPTION below.
- "Overview" / full description -> paste everything under OVERVIEW (it's Markdown).
-->

## SHORT DESCRIPTION (max ~100 chars)

Web chat for AI models that call Workato/MCP tools — with built-in benchmarking. Runs locally.

---

## OVERVIEW

# Simple Enterprise MCP Chat

A self-hosted **web app** for chatting with AI models (OpenAI, Claude, Ollama, LM Studio)
that call tools from **Workato Enterprise MCP** servers — or any MCP server. It includes a
side-by-side **benchmarking workspace** so you can run one prompt across several models or
servers and compare token cost, latency, and tool reliability.

Everything runs **on your own machine**; your conversations, API keys, and sign-ins stay in
a local Docker volume and never leave your computer.

## Quick start

You need [Docker Desktop](https://www.docker.com/products/docker-desktop/). Then:

```bash
docker run -d \
  -p 127.0.0.1:8501:8501 \
  -p 127.0.0.1:8080:8080 \
  -v "$(pwd)/data:/app/data" \
  --name mcp-chat \
  mattcarpenterwkto/simple-enterprise-mcp-chat:latest
```

Open **http://localhost:8501** in your browser. Your data is saved in a `data/`
folder in the current directory.

### Or with Docker Compose (recommended)

Save this as `docker-compose.yml` and run `docker compose up -d`:

```yaml
services:
  mcp-chat:
    image: mattcarpenterwkto/simple-enterprise-mcp-chat:latest
    ports:
      - "127.0.0.1:8501:8501"   # web UI
      - "127.0.0.1:8080:8080"   # OAuth sign-in callback
    volumes:
      - ./data:/app/data        # your data (DB, tokens, logs) — kept next to this file
    restart: unless-stopped
```

## First-time setup (in the browser)

1. **⚙️ Settings** → add an OpenAI and/or Claude API key.
2. **🔌 MCP Servers** → add a server (name + URL + auth type).
3. For OAuth servers, click **🔐 Re-authenticate** — a sign-in link appears; click it and log in.
4. **💬 Home** → pick a model and start chatting.

## Configuration

| Item | Detail |
|------|--------|
| **Web UI port** | `8501` |
| **OAuth callback port** | `8080` (must be published for MCP OAuth sign-in to work) |
| **Data folder** | `/app/data` in the container, bind-mounted to `./data` on your machine — SQLite database, OAuth tokens, and app logs |
| **`MCP_CHAT_DATA_DIR`** | Where state is stored inside the container (default `/app/data`) |

No API keys or server configs are baked into the image — you enter them in the app's UI.

> **Local model servers (Ollama / LM Studio):** inside Docker, `localhost` is the container,
> not your machine. In **Settings**, set their URLs to `host.docker.internal`
> (e.g. `http://host.docker.internal:11434`).

## Tags

- `latest` — most recent release
- `vX.Y.Z` — specific versions

Built for **linux/amd64** and **linux/arm64** (Intel/AMD PCs and Apple-Silicon Macs).

## Source & docs

GitHub: <https://github.com/MattCarpenter-Workato/simple-enterprise-mcp-chat>

## License

MIT
