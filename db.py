"""
SQLite persistence layer for the MCP Chat web UI.

This is the single source of truth for the Streamlit app: MCP server configs,
OAuth tokens, API keys / credentials, saved system prompts, and chat history all
live in one SQLite file (mcp_chat.db, git-ignored).

Secrets are stored in plaintext (same exposure level as the .env approach used by
the CLI scripts, just centralized). The file is created on first import via
CREATE TABLE IF NOT EXISTS.

On first run, seed_from_files_if_empty() imports any existing .env,
mcp_servers.json, and .mcp_tokens.json so the user doesn't have to re-enter
anything. This is one-way: the UI never writes back to those files, so the legacy
CLI scripts keep working from their own file-based config.
"""

import os
import json
import sqlite3
from datetime import datetime
from typing import Any, Optional

# Database file lives next to this module (repo root)
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mcp_chat.db")

# Single shared connection. Streamlit reruns the script in one process/thread per
# session, but cached resources can be touched across threads, so allow it.
_conn: Optional[sqlite3.Connection] = None


def _now() -> str:
    """Current timestamp as an ISO string (stored as text)."""
    return datetime.now().isoformat(timespec="seconds")


def get_conn() -> sqlite3.Connection:
    """Return the shared connection, initializing schema on first use."""
    global _conn
    if _conn is None:
        _conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _init_schema(_conn)
    return _conn


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
        """
    )
    conn.commit()


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
        fields["oauth_json"] = json.dumps(fields.pop("oauth")) if fields["oauth"] else None
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
# OAUTH TOKENS (replaces .mcp_tokens.json)
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
# FIRST-RUN IMPORT
# =============================================================================

def seed_from_files_if_empty() -> None:
    """If the DB has never been seeded, import existing file-based config.

    Reads .env, mcp_servers.json, and .mcp_tokens.json from the repo root. Marked
    done via a sentinel secret so we never clobber later edits. One-way only.
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

    # --- .mcp_tokens.json -> oauth_tokens ---
    tokens_path = os.path.join(root, ".mcp_tokens.json")
    if os.path.exists(tokens_path):
        try:
            with open(tokens_path, "r", encoding="utf-8") as f:
                tokens = json.load(f)
            for server_name, data in tokens.items():
                if isinstance(data, dict) and not get_oauth_token(server_name):
                    set_oauth_token(server_name, data)
        except Exception:
            pass

    set_secret("_seeded", "1")
    conn.commit()
