# syntax=docker/dockerfile:1
# Build: docker build -t mcp-chat .
# Multi-arch publish is handled by .github/workflows/release.yml (buildx).

FROM python:3.12-slim

# uv for fast, lockfile-faithful installs.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# Install dependencies first (cached layer) using only the manifest + lockfile,
# so source edits don't bust the dependency cache.
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# App source.
COPY . .
RUN uv sync --frozen --no-dev

# Put the project venv on PATH so `streamlit` resolves.
ENV PATH="/app/.venv/bin:$PATH"

# All persistent state (SQLite DB, OAuth tokens, logs) lives here — mount a volume.
ENV MCP_CHAT_DATA_DIR=/app/data
RUN mkdir -p /app/data

# 8501 = Streamlit UI; 8080 = OAuth callback listener (oauth_store.py).
EXPOSE 8501 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8501/_stcore/health', timeout=4).status==200 else 1)"

CMD ["streamlit", "run", "app.py", \
     "--server.address=0.0.0.0", \
     "--server.port=8501", \
     "--server.headless=true", \
     "--browser.gatherUsageStats=false"]
