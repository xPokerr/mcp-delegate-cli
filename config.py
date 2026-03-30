import os
import shutil

from dotenv import load_dotenv

load_dotenv()

CODEX_CMD = os.getenv("CODEX_CMD", "codex")
CLAUDE_CMD = os.getenv("CLAUDE_CMD", "claude")
TIMEOUT = int(os.getenv("DELEGATE_TIMEOUT_SECONDS", "300"))
MAX_TASK_CHARS = int(os.getenv("DELEGATE_MAX_TASK_CHARS", "12000"))
STRIP_ANSI = os.getenv("STRIP_ANSI", "true").lower() == "true"
CODEX_JSON_MODE = os.getenv("CODEX_JSON_MODE", "true").lower() == "true"
TASK_CONTEXT_THRESHOLD_CHARS = int(os.getenv("TASK_CONTEXT_THRESHOLD_CHARS", "2000"))
TMP_DIR_NAME = os.getenv("TMP_DIR_NAME", ".mcp_tmp")
PROGRESS_INTERVAL = int(os.getenv("PROGRESS_INTERVAL_SECONDS", "15"))
HISTORY_DIR_NAME = os.getenv("HISTORY_DIR_NAME", ".mcp_history")
HISTORY_FOOTER_ENTRIES = int(os.getenv("HISTORY_FOOTER_ENTRIES", "2"))
HISTORY_SUMMARY_CHARS = int(os.getenv("HISTORY_SUMMARY_CHARS", "80"))


def resolve_binary(name: str) -> str:
    """Resolve a binary name to its full path, or raise if not found."""
    path = shutil.which(name)
    if path is None:
        raise RuntimeError(
            f"Binary '{name}' not found in PATH. "
            f"Set the correct path via environment variable."
        )
    return path
