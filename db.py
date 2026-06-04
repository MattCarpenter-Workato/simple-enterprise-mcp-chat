"""
SQLite persistence layer for the MCP Chat web UI.

This is the single source of truth for the Streamlit app: MCP server configs,
OAuth tokens, API keys / credentials, saved system prompts, and chat history all
live in one SQLite file (mcp_chat.db, git-ignored).

Secrets are stored in plaintext (same exposure level as the .env approach used by
the CLI scripts, just centralized). The file is created on first import via
CREATE TABLE IF NOT EXISTS.

On first run, seed_from_files_if_empty() imports any existing .env and
mcp_servers.json so the user doesn't have to re-enter anything. This is one-way:
the UI never writes back to those files. OAuth tokens are not seeded from a file —
they live only in the DB, written by the OAuth flow (oauth_store.py).
"""

import os
import json
import sqlite3
import threading
from datetime import datetime
from typing import Any, Optional

# Database file lives in the data directory. Defaults to this module's directory
# (repo root) so a local `uv run` is unchanged; set MCP_CHAT_DATA_DIR to relocate
# all persistent state (used by Docker to point at a mounted volume).
DATA_DIR = os.environ.get("MCP_CHAT_DATA_DIR") or os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(DATA_DIR, "mcp_chat.db")

# One connection PER THREAD. Streamlit runs each rerun/session on its own
# ScriptRunner thread; sharing a single sqlite connection across them can block
# (the cause of "clear all logs hangs"). A thread-local connection avoids that;
# WAL + a busy timeout keep concurrent readers/writers from deadlocking.
_local = threading.local()


def _now() -> str:
    """Current timestamp as an ISO string (stored as text)."""
    return datetime.now().isoformat(timespec="seconds")


def get_conn() -> sqlite3.Connection:
    """Return this thread's connection, initializing schema on first use."""
    conn = getattr(_local, "conn", None)
    if conn is None:
        os.makedirs(DATA_DIR, exist_ok=True)  # ensure a relocated/volume data dir exists
        conn = sqlite3.connect(DB_PATH, timeout=10, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        _init_schema(conn)
        _local.conn = conn
    return conn


def _init_schema(conn: sqlite3.Connection) -> None:
    """Create all tables if they don't already exist."""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS servers (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            name       TEXT UNIQUE NOT NULL,
            url        TEXT NOT NULL,
            enabled    INTEGER NOT NULL DEFAULT 1,
            auth_type  TEXT NOT NULL DEFAULT 'token',
            oauth_json TEXT
        );

        CREATE TABLE IF NOT EXISTS oauth_tokens (
            server_name   TEXT PRIMARY KEY,
            access_token  TEXT,
            refresh_token TEXT,
            client_id     TEXT,
            client_secret TEXT,
            expires_at    TEXT,
            extra_json    TEXT
        );

        CREATE TABLE IF NOT EXISTS secrets (
            name  TEXT PRIMARY KEY,
            value TEXT
        );

        CREATE TABLE IF NOT EXISTS system_prompts (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            name       TEXT UNIQUE NOT NULL,
            content    TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS conversations (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            title            TEXT NOT NULL,
            provider         TEXT,
            model            TEXT,
            system_prompt_id INTEGER,
            created_at       TEXT NOT NULL,
            updated_at       TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS messages (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            conversation_id INTEGER NOT NULL,
            role            TEXT NOT NULL,
            content         TEXT NOT NULL,
            created_at      TEXT NOT NULL,
            FOREIGN KEY (conversation_id) REFERENCES conversations(id)
        );

        CREATE TABLE IF NOT EXISTS chat_logs (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            conversation_id   INTEGER NOT NULL,
            created_at        TEXT NOT NULL,
            event_type        TEXT NOT NULL,   -- 'llm_call' | 'tool_call' | 'error'
            provider          TEXT,
            model             TEXT,
            call_type         TEXT,            -- 'initial_request' | 'tool_followup'
            prompt_tokens     INTEGER,
            completion_tokens INTEGER,
            total_tokens      INTEGER,
            duration_ms       INTEGER,         -- LLM latency or MCP round-trip
            data_chars        INTEGER,         -- size of MCP tool result
            server            TEXT,            -- MCP server name (tool_call)
            user_prompt       TEXT,
            system_prompt     TEXT,
            servers           TEXT,            -- comma-separated
            tools             TEXT,            -- comma-separated
            response_preview  TEXT,
            detail_json       TEXT,
            success           INTEGER,         -- tool_call: 1 ok, 0 errored
            error             TEXT,            -- tool_call: error text when success=0
            attempt           INTEGER,         -- tool_call: Nth call of this tool in the turn
            benchmark_run_id  INTEGER          -- set when the call is part of a benchmark run
        );

        CREATE INDEX IF NOT EXISTS idx_chat_logs_conv ON chat_logs(conversation_id);

        -- Benchmarking: one run = the same prompt fanned out across variants.
        -- mode='models': variants differ by (provider, model), shared servers.
        -- mode='servers': fixed model, one variant per MCP server.
        CREATE TABLE IF NOT EXISTS benchmark_runs (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at       TEXT NOT NULL,
            prompt           TEXT NOT NULL,
            system_prompt_id INTEGER,
            label            TEXT,
            notes            TEXT,
            mode             TEXT DEFAULT 'models'   -- 'models' | 'servers'
        );

        CREATE TABLE IF NOT EXISTS benchmark_variants (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id          INTEGER NOT NULL,
            provider        TEXT NOT NULL,
            model           TEXT NOT NULL,
            conversation_id INTEGER,
            total_ms        INTEGER,
            status          TEXT,              -- 'ok' | 'error'
            error           TEXT,
            servers         TEXT,              -- comma-joined server names exposed to this variant
            FOREIGN KEY (run_id) REFERENCES benchmark_runs(id)
        );

        CREATE INDEX IF NOT EXISTS idx_bench_variants_run ON benchmark_variants(run_id);
        """
    )
    _migrate_chat_logs(conn)
    conn.commit()


def _migrate_chat_logs(conn: sqlite3.Connection) -> None:
    """Add columns introduced after the table was first created.

    `_init_schema` uses CREATE TABLE IF NOT EXISTS, so a DB created by an older
    build keeps its original chat_logs columns. SQLite's ALTER TABLE ADD COLUMN
    is cheap and safe, so we add any missing ones idempotently."""
    existing = {r["name"] for r in conn.execute("PRAGMA table_info(chat_logs)")}
    additions = {
        "success": "INTEGER",
        "error": "TEXT",
        "attempt": "INTEGER",
        "benchmark_run_id": "INTEGER",
    }
    for col, decl in additions.items():
        if col not in existing:
            conn.execute(f"ALTER TABLE chat_logs ADD COLUMN {col} {decl}")


# =============================================================================
# SECRETS (API keys + provider settings) — generic key/value bag
# =============================================================================

def get_secret(name: str, default: Optional[str] = None) -> Optional[str]:
    row = get_conn().execute("SELECT value FROM secrets WHERE name = ?", (name,)).fetchone()
    return row["value"] if row else default


def set_secret(name: str, value: Optional[str]) -> None:
    get_conn().execute(
        "INSERT INTO secrets (name, value) VALUES (?, ?) "
        "ON CONFLICT(name) DO UPDATE SET value = excluded.value",
        (name, value),
    )
    get_conn().commit()


def all_secrets() -> dict[str, str]:
    rows = get_conn().execute("SELECT name, value FROM secrets").fetchall()
    return {r["name"]: r["value"] for r in rows}


# =============================================================================
# SERVERS
# =============================================================================

def list_servers(enabled_only: bool = False) -> list[dict[str, Any]]:
    sql = "SELECT * FROM servers"
    if enabled_only:
        sql += " WHERE enabled = 1"
    sql += " ORDER BY name COLLATE NOCASE"
    return [_server_row(r) for r in get_conn().execute(sql).fetchall()]


def _server_row(r: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": r["id"],
        "name": r["name"],
        "url": r["url"],
        "enabled": bool(r["enabled"]),
        "auth_type": r["auth_type"],
        "oauth": json.loads(r["oauth_json"]) if r["oauth_json"] else None,
    }


def add_server(name: str, url: str, auth_type: str = "token",
               enabled: bool = True, oauth: Optional[dict] = None) -> None:
    get_conn().execute(
        "INSERT INTO servers (name, url, enabled, auth_type, oauth_json) "
        "VALUES (?, ?, ?, ?, ?) "
        "ON CONFLICT(name) DO UPDATE SET url=excluded.url, enabled=excluded.enabled, "
        "auth_type=excluded.auth_type, oauth_json=excluded.oauth_json",
        (name, url, int(enabled), auth_type, json.dumps(oauth) if oauth else None),
    )
    get_conn().commit()


def update_server(server_id: int, **fields) -> None:
    if "oauth" in fields:
        oauth = fields.pop("oauth")
        fields["oauth_json"] = json.dumps(oauth) if oauth else None
    if "enabled" in fields:
        fields["enabled"] = int(bool(fields["enabled"]))
    if not fields:
        return
    cols = ", ".join(f"{k} = ?" for k in fields)
    get_conn().execute(f"UPDATE servers SET {cols} WHERE id = ?", (*fields.values(), server_id))
    get_conn().commit()


def set_server_enabled(server_id: int, enabled: bool) -> None:
    get_conn().execute("UPDATE servers SET enabled = ? WHERE id = ?", (int(enabled), server_id))
    get_conn().commit()


def remove_server(server_id: int) -> None:
    get_conn().execute("DELETE FROM servers WHERE id = ?", (server_id,))
    get_conn().commit()


# =============================================================================
# OAUTH TOKENS (written by the OAuth flow in oauth_store.py)
# =============================================================================

def get_oauth_token(server_name: str) -> Optional[dict[str, Any]]:
    r = get_conn().execute(
        "SELECT * FROM oauth_tokens WHERE server_name = ?", (server_name,)
    ).fetchone()
    if not r:
        return None
    data: dict[str, Any] = {}
    if r["extra_json"]:
        data.update(json.loads(r["extra_json"]))
    for key in ("access_token", "refresh_token", "client_id", "client_secret", "expires_at"):
        if r[key] is not None:
            data[key] = r[key]
    return data or None


def clear_all_oauth_tokens() -> int:
    """Delete all stored OAuth tokens + client credentials, forcing every OAuth
    server to re-register and re-authenticate. Returns rows removed."""
    conn = get_conn()
    cur = conn.execute("DELETE FROM oauth_tokens")
    conn.commit()
    return cur.rowcount


def set_oauth_token(server_name: str, data: dict[str, Any]) -> None:
    known = ("access_token", "refresh_token", "client_id", "client_secret", "expires_at")
    extra = {k: v for k, v in data.items() if k not in known}
    get_conn().execute(
        "INSERT INTO oauth_tokens "
        "(server_name, access_token, refresh_token, client_id, client_secret, expires_at, extra_json) "
        "VALUES (?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(server_name) DO UPDATE SET "
        "access_token=excluded.access_token, refresh_token=excluded.refresh_token, "
        "client_id=excluded.client_id, client_secret=excluded.client_secret, "
        "expires_at=excluded.expires_at, extra_json=excluded.extra_json",
        (
            server_name,
            data.get("access_token"),
            data.get("refresh_token"),
            data.get("client_id"),
            data.get("client_secret"),
            data.get("expires_at"),
            json.dumps(extra) if extra else None,
        ),
    )
    get_conn().commit()


# =============================================================================
# SYSTEM PROMPTS
# =============================================================================

def list_prompts() -> list[dict[str, Any]]:
    rows = get_conn().execute(
        "SELECT * FROM system_prompts ORDER BY name COLLATE NOCASE"
    ).fetchall()
    return [dict(r) for r in rows]


def get_prompt(prompt_id: int) -> Optional[dict[str, Any]]:
    r = get_conn().execute("SELECT * FROM system_prompts WHERE id = ?", (prompt_id,)).fetchone()
    return dict(r) if r else None


def save_prompt(name: str, content: str, prompt_id: Optional[int] = None) -> int:
    conn = get_conn()
    now = _now()
    if prompt_id:
        conn.execute(
            "UPDATE system_prompts SET name = ?, content = ?, updated_at = ? WHERE id = ?",
            (name, content, now, prompt_id),
        )
        conn.commit()
        return prompt_id
    cur = conn.execute(
        "INSERT INTO system_prompts (name, content, created_at, updated_at) VALUES (?, ?, ?, ?)",
        (name, content, now, now),
    )
    conn.commit()
    return cur.lastrowid


def delete_prompt(prompt_id: int) -> None:
    get_conn().execute("DELETE FROM system_prompts WHERE id = ?", (prompt_id,))
    get_conn().commit()


# =============================================================================
# CONVERSATIONS + MESSAGES
# =============================================================================

def create_conversation(title: str, provider: str, model: str,
                         system_prompt_id: Optional[int] = None) -> int:
    conn = get_conn()
    now = _now()
    cur = conn.execute(
        "INSERT INTO conversations (title, provider, model, system_prompt_id, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (title, provider, model, system_prompt_id, now, now),
    )
    conn.commit()
    return cur.lastrowid


def list_conversations() -> list[dict[str, Any]]:
    rows = get_conn().execute(
        "SELECT * FROM conversations ORDER BY updated_at DESC"
    ).fetchall()
    return [dict(r) for r in rows]


def rename_conversation(conversation_id: int, title: str) -> None:
    get_conn().execute(
        "UPDATE conversations SET title = ?, updated_at = ? WHERE id = ?",
        (title, _now(), conversation_id),
    )
    get_conn().commit()


def delete_conversation(conversation_id: int) -> None:
    conn = get_conn()
    conn.execute("DELETE FROM messages WHERE conversation_id = ?", (conversation_id,))
    conn.execute("DELETE FROM chat_logs WHERE conversation_id = ?", (conversation_id,))
    conn.execute("DELETE FROM conversations WHERE id = ?", (conversation_id,))
    conn.commit()


def add_message(conversation_id: int, role: str, content: Any) -> None:
    """Store a message. `content` may be a string or a JSON-serializable structure
    (e.g. provider-native tool blocks); it is stored as JSON text either way."""
    stored = content if isinstance(content, str) else json.dumps(content)
    conn = get_conn()
    conn.execute(
        "INSERT INTO messages (conversation_id, role, content, created_at) VALUES (?, ?, ?, ?)",
        (conversation_id, role, stored, _now()),
    )
    conn.execute(
        "UPDATE conversations SET updated_at = ? WHERE id = ?", (_now(), conversation_id)
    )
    conn.commit()


def get_messages(conversation_id: int) -> list[dict[str, Any]]:
    """Return messages in order. `content` is decoded from JSON when possible,
    otherwise returned as the raw string."""
    rows = get_conn().execute(
        "SELECT role, content FROM messages WHERE conversation_id = ? ORDER BY id",
        (conversation_id,),
    ).fetchall()
    out = []
    for r in rows:
        content = r["content"]
        try:
            content = json.loads(content)
        except (json.JSONDecodeError, TypeError):
            pass
        out.append({"role": r["role"], "content": content})
    return out


# =============================================================================
# CHAT LOGS (per-call token usage, timing, and tool/server tracking)
# =============================================================================

_LOG_COLUMNS = (
    "event_type", "provider", "model", "call_type",
    "prompt_tokens", "completion_tokens", "total_tokens",
    "duration_ms", "data_chars", "server",
    "user_prompt", "system_prompt", "servers", "tools",
    "response_preview", "detail_json",
    "success", "error", "attempt", "benchmark_run_id",
)


def add_log(conversation_id: int, **fields) -> None:
    """Insert one log row. Unknown keys are ignored; absent columns default NULL."""
    cols = ["conversation_id", "created_at"]
    vals: list[Any] = [conversation_id, _now()]
    for col in _LOG_COLUMNS:
        if col in fields:
            cols.append(col)
            vals.append(fields[col])
    placeholders = ", ".join("?" for _ in cols)
    conn = get_conn()
    conn.execute(
        f"INSERT INTO chat_logs ({', '.join(cols)}) VALUES ({placeholders})", vals
    )
    conn.commit()


def get_logs(conversation_id: int) -> list[dict[str, Any]]:
    rows = get_conn().execute(
        "SELECT * FROM chat_logs WHERE conversation_id = ? ORDER BY id",
        (conversation_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def all_logs() -> list[dict[str, Any]]:
    """Every log row across all conversations, joined to its conversation title.
    Used for the global, CSV-exportable table on the Logs page."""
    rows = get_conn().execute(
        """
        SELECT c.title AS conversation, cl.*
        FROM chat_logs cl
        LEFT JOIN conversations c ON c.id = cl.conversation_id
        ORDER BY cl.created_at DESC, cl.id DESC
        """
    ).fetchall()
    return [dict(r) for r in rows]


def clear_all_logs() -> int:
    """Delete every log row across all conversations. Returns rows removed."""
    conn = get_conn()
    cur = conn.execute("DELETE FROM chat_logs")
    conn.commit()
    return cur.rowcount


def delete_all_conversations() -> int:
    """Delete every conversation, its messages, and its logs. Returns the number
    of conversations removed. Config (servers/keys/prompts) is untouched."""
    conn = get_conn()
    cur = conn.execute("SELECT COUNT(*) FROM conversations")
    n = cur.fetchone()[0]
    conn.execute("DELETE FROM messages")
    conn.execute("DELETE FROM chat_logs")
    conn.execute("DELETE FROM conversations")
    conn.commit()
    return n


def conversation_usage(conversation_id: int) -> dict[str, Any]:
    """Aggregate token + timing stats for a single conversation."""
    r = get_conn().execute(
        """
        SELECT
            COALESCE(SUM(prompt_tokens), 0)     AS prompt_tokens,
            COALESCE(SUM(completion_tokens), 0) AS completion_tokens,
            COALESCE(SUM(total_tokens), 0)      AS total_tokens,
            COALESCE(SUM(CASE WHEN event_type='llm_call'  THEN 1 ELSE 0 END), 0) AS llm_calls,
            COALESCE(SUM(CASE WHEN event_type='tool_call' THEN 1 ELSE 0 END), 0) AS tool_calls,
            COALESCE(SUM(CASE WHEN event_type='llm_call'  THEN duration_ms END), 0) AS llm_ms,
            ROUND(AVG(CASE WHEN event_type='tool_call' THEN duration_ms END), 0)    AS avg_tool_ms
        FROM chat_logs WHERE conversation_id = ?
        """,
        (conversation_id,),
    ).fetchone()
    return dict(r)


def usage_by_provider_model() -> list[dict[str, Any]]:
    """Per provider+model token totals and average LLM latency (model tuning)."""
    rows = get_conn().execute(
        """
        SELECT provider, model,
               COUNT(*)                       AS calls,
               COALESCE(SUM(prompt_tokens), 0)     AS prompt_tokens,
               COALESCE(SUM(completion_tokens), 0) AS completion_tokens,
               COALESCE(SUM(total_tokens), 0)      AS total_tokens,
               ROUND(AVG(duration_ms), 0)     AS avg_ms
        FROM chat_logs
        WHERE event_type = 'llm_call'
        GROUP BY provider, model
        ORDER BY total_tokens DESC
        """
    ).fetchall()
    return [dict(r) for r in rows]


def usage_by_server_tool() -> list[dict[str, Any]]:
    """Per server+tool call count, latency, and returned-data size (MCP tuning)."""
    rows = get_conn().execute(
        """
        SELECT server, tools AS tool,
               COUNT(*)                   AS calls,
               ROUND(AVG(duration_ms), 0) AS avg_ms,
               MAX(duration_ms)           AS max_ms,
               ROUND(AVG(data_chars), 0)  AS avg_data_chars
        FROM chat_logs
        WHERE event_type = 'tool_call'
        GROUP BY server, tools
        ORDER BY calls DESC
        """
    ).fetchall()
    return [dict(r) for r in rows]


# =============================================================================
# BENCHMARKING (run one prompt across model variants, then compare)
# =============================================================================

def create_benchmark_run(prompt: str, system_prompt_id: Optional[int] = None,
                         label: Optional[str] = None, notes: Optional[str] = None,
                         mode: str = "models") -> int:
    conn = get_conn()
    cur = conn.execute(
        "INSERT INTO benchmark_runs (created_at, prompt, system_prompt_id, label, notes, mode) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (_now(), prompt, system_prompt_id, label, notes, mode),
    )
    conn.commit()
    return cur.lastrowid


def add_benchmark_variant(run_id: int, provider: str, model: str,
                          conversation_id: Optional[int], total_ms: Optional[int],
                          status: str, error: Optional[str] = None,
                          servers: Optional[str] = None) -> int:
    conn = get_conn()
    cur = conn.execute(
        "INSERT INTO benchmark_variants "
        "(run_id, provider, model, conversation_id, total_ms, status, error, servers) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (run_id, provider, model, conversation_id, total_ms, status, error, servers),
    )
    conn.commit()
    return cur.lastrowid


def list_benchmark_runs() -> list[dict[str, Any]]:
    rows = get_conn().execute(
        "SELECT * FROM benchmark_runs ORDER BY id DESC"
    ).fetchall()
    return [dict(r) for r in rows]


def clear_all_benchmark_runs() -> int:
    """Delete every benchmark run and its variants, plus the per-variant
    conversations they created (and those conversations' messages and logs).
    Returns the number of runs removed. Regular chats are untouched."""
    conn = get_conn()
    conv_ids = [r[0] for r in conn.execute(
        "SELECT conversation_id FROM benchmark_variants "
        "WHERE conversation_id IS NOT NULL"
    ).fetchall()]
    for cid in conv_ids:
        conn.execute("DELETE FROM messages WHERE conversation_id = ?", (cid,))
        conn.execute("DELETE FROM chat_logs WHERE conversation_id = ?", (cid,))
        conn.execute("DELETE FROM conversations WHERE id = ?", (cid,))
    n = conn.execute("SELECT COUNT(*) FROM benchmark_runs").fetchone()[0]
    conn.execute("DELETE FROM benchmark_variants")
    conn.execute("DELETE FROM benchmark_runs")
    conn.commit()
    return n


def get_benchmark_variants(run_id: int) -> list[dict[str, Any]]:
    rows = get_conn().execute(
        "SELECT * FROM benchmark_variants WHERE run_id = ? ORDER BY id",
        (run_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def benchmark_comparison(run_id: int) -> list[dict[str, Any]]:
    """One row per variant: the recorded run status/total time joined to the
    per-conversation token/latency/tool aggregates from chat_logs. Reuses the
    same aggregate shape as conversation_usage()."""
    variants = get_benchmark_variants(run_id)
    conn = get_conn()
    out = []
    for v in variants:
        agg = {
            "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0,
            "llm_calls": 0, "tool_calls": 0, "tool_errors": 0, "retries": 0,
            "llm_ms": 0, "answer": "",
        }
        if v["conversation_id"] is not None:
            r = conn.execute(
                """
                SELECT
                    COALESCE(SUM(prompt_tokens), 0)     AS prompt_tokens,
                    COALESCE(SUM(completion_tokens), 0) AS completion_tokens,
                    COALESCE(SUM(total_tokens), 0)      AS total_tokens,
                    COALESCE(SUM(CASE WHEN event_type='llm_call'  THEN 1 ELSE 0 END), 0) AS llm_calls,
                    COALESCE(SUM(CASE WHEN event_type='tool_call' THEN 1 ELSE 0 END), 0) AS tool_calls,
                    COALESCE(SUM(CASE WHEN event_type='tool_call' AND success=0 THEN 1 ELSE 0 END), 0) AS tool_errors,
                    COALESCE(SUM(CASE WHEN event_type='tool_call' AND attempt>1 THEN 1 ELSE 0 END), 0) AS retries,
                    COALESCE(SUM(CASE WHEN event_type='llm_call'  THEN duration_ms END), 0) AS llm_ms
                FROM chat_logs WHERE conversation_id = ?
                """,
                (v["conversation_id"],),
            ).fetchone()
            agg.update(dict(r))
            ans = conn.execute(
                "SELECT response_preview FROM chat_logs "
                "WHERE conversation_id = ? AND event_type='llm_call' "
                "AND response_preview IS NOT NULL AND response_preview != '' "
                "ORDER BY id DESC LIMIT 1",
                (v["conversation_id"],),
            ).fetchone()
            agg["answer"] = ans["response_preview"] if ans else ""
        out.append({**v, **agg})
    return out


# =============================================================================
# FIRST-RUN IMPORT
# =============================================================================

def seed_from_files_if_empty() -> None:
    """If the DB has never been seeded, import existing file-based config.

    Reads .env and mcp_servers.json from the repo root. Marked done via a sentinel
    secret so we never clobber later edits. One-way only. (OAuth tokens are not
    imported — they live only in the DB, written by the OAuth flow.)
    """
    conn = get_conn()
    if get_secret("_seeded") == "1":
        return

    root = os.path.dirname(os.path.abspath(__file__))

    # --- .env -> secrets ---
    env_path = os.path.join(root, ".env")
    if os.path.exists(env_path):
        try:
            from dotenv import dotenv_values
            for k, v in dotenv_values(env_path).items():
                if v is not None and get_secret(k) is None:
                    set_secret(k, v)
        except Exception:
            pass

    # --- mcp_servers.json -> servers ---
    servers_path = os.path.join(root, "mcp_servers.json")
    if os.path.exists(servers_path) and not list_servers():
        try:
            with open(servers_path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            for s in cfg.get("servers", []):
                name, url = s.get("name"), s.get("url")
                if name and url:
                    add_server(
                        name=name,
                        url=url,
                        auth_type=s.get("auth_type", "token"),
                        enabled=s.get("enabled", True),
                        oauth=s.get("oauth"),
                    )
        except Exception:
            pass

    # OAuth tokens are not seeded from a file: they live only in the DB, written
    # by the OAuth flow (oauth_store.py). Re-authenticate via the MCP Servers page.

    set_secret("_seeded", "1")
    conn.commit()
