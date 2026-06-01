"""
Application-level logging to a rotating file (logs/app.log).

This is distinct from the per-conversation logging in the DB (`chat_logs`):
- **conversation logs** (db.py) = tokens, tools, latency for each chat turn.
- **app logs** (here) = errors, tracebacks, MCP/OAuth failures, startup events —
  i.e. "is the *app* healthy?" vs "what happened in this *conversation*?".

Configured once per process (init is idempotent + guarded). The root logger gets a
rotating file handler so our own modules (`mcpchat.*`, `mcp_core`) and Streamlit's
uncaught-exception logs all land in the same file.
"""

import logging
import os
from logging.handlers import RotatingFileHandler

LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
APP_LOG_PATH = os.path.join(LOG_DIR, "app.log")

_configured = False


def configure_logging(level: str = "INFO") -> str:
    """Attach a rotating file handler to the root logger. Returns the log path."""
    global _configured
    if _configured:
        return APP_LOG_PATH

    os.makedirs(LOG_DIR, exist_ok=True)
    lvl = getattr(logging, str(level).upper(), logging.INFO)

    handler = RotatingFileHandler(
        APP_LOG_PATH, maxBytes=1_000_000, backupCount=3, encoding="utf-8"
    )
    handler.setFormatter(logging.Formatter(
        "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))

    root = logging.getLogger()
    root.setLevel(lvl)
    # Avoid stacking duplicate handlers across Streamlit reruns.
    if not any(isinstance(h, RotatingFileHandler) and
               getattr(h, "baseFilename", None) == handler.baseFilename
               for h in root.handlers):
        root.addHandler(handler)

    # Quiet noisy third-party loggers; their ERRORs still pass through.
    for noisy in ("watchdog", "urllib3", "httpx", "streamlit"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    logging.getLogger("mcpchat").info("App logging initialized (level=%s)", lvl)
    _configured = True
    return APP_LOG_PATH


def read_tail(max_lines: int = 200) -> str:
    """Return the last `max_lines` of the app log (for the in-UI viewer)."""
    if not os.path.exists(APP_LOG_PATH):
        return ""
    try:
        with open(APP_LOG_PATH, "r", encoding="utf-8", errors="replace") as f:
            return "".join(f.readlines()[-max_lines:])
    except OSError as e:
        return f"(could not read log: {e})"


def clear_log() -> None:
    """Truncate the app log file."""
    if os.path.exists(APP_LOG_PATH):
        open(APP_LOG_PATH, "w", encoding="utf-8").close()
