"""
Thin wrapper around the LM Studio `lms` CLI.

LM Studio's OpenAI-compatible HTTP API only reports *loaded* models, so it can
neither enumerate downloaded-but-unloaded models nor load one on demand. The
`lms` CLI can: `lms ls` lists everything downloaded and `lms load` loads a model
into the running LM Studio service. These helpers power LM Studio model discovery
and the sidebar "Load model" control, degrading gracefully (empty list /
(False, msg)) when the CLI is absent so callers fall back to HTTP discovery.

Note: the CLI controls the LM Studio service on *this* machine, so loading only
works when the app and LM Studio run on the same host (a remote LMSTUDIO_BASE_URL
still serves chat over HTTP, but its models can't be managed from here).
"""

import json
import logging
import shutil
import subprocess
from typing import Any

logger = logging.getLogger("mcpchat.lms")

_LIST_TIMEOUT = 15   # seconds — `lms ls --json` is fast
_LOAD_TIMEOUT = 300  # seconds — loading a large model can take a while


def available() -> bool:
    """True when the `lms` CLI is on PATH."""
    return shutil.which("lms") is not None


def _run_json(args: list[str], timeout: int) -> list[dict[str, Any]]:
    """Run an `lms` subcommand that emits a JSON array; [] on any failure."""
    if not available():
        return []
    try:
        proc = subprocess.run(
            ["lms", *args], capture_output=True, text=True, timeout=timeout
        )
    except Exception as e:  # noqa: BLE001 — missing CLI / timeout / OS error
        logger.info("`lms %s` failed: %s", " ".join(args), e)
        return []
    if proc.returncode != 0:
        logger.info("`lms %s` exited %s: %s", " ".join(args), proc.returncode,
                    proc.stderr.strip())
        return []
    try:
        data = json.loads(proc.stdout)
        return data if isinstance(data, list) else []
    except json.JSONDecodeError:
        return []


def downloaded_chat_models() -> list[str]:
    """modelKeys of all downloaded chat models (embeddings excluded), e.g.
    'qwen/qwen3-14b'. Empty when the CLI is unavailable — callers fall back to
    HTTP discovery."""
    return [m["modelKey"] for m in _run_json(["ls", "--json"], _LIST_TIMEOUT)
            if m.get("type") != "embedding" and m.get("modelKey")]


def load(model_key: str) -> tuple[bool, str]:
    """Load a model into LM Studio (`lms load <key> -y`, default settings).
    Returns (ok, message). Blocking — can take a while for large models."""
    if not available():
        return False, "`lms` CLI not found on PATH."
    try:
        proc = subprocess.run(
            ["lms", "load", model_key, "-y"],
            capture_output=True, text=True, timeout=_LOAD_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        return False, f"Timed out loading {model_key}."
    except Exception as e:  # noqa: BLE001
        return False, str(e)
    msg = (proc.stdout or proc.stderr or "").strip()
    return proc.returncode == 0, msg or model_key
