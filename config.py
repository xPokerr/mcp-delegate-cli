import os
import shutil

from dotenv import load_dotenv

load_dotenv()

CODEX_CMD = os.getenv("CODEX_CMD", "codex")
CLAUDE_CMD = os.getenv("CLAUDE_CMD", "claude")
GEMINI_CMD = os.getenv("GEMINI_CMD", "gemini")
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
MAX_DELEGATE_DEPTH = int(os.getenv("MAX_DELEGATE_DEPTH", "1"))
CURRENT_DELEGATE_DEPTH = int(os.getenv("MCP_DELEGATE_DEPTH", "0"))
DISABLED_DELEGATES: set[str] = {
    s.strip().lower()
    for s in os.getenv("DISABLED_DELEGATES", "").split(",")
    if s.strip()
}


def resolve_binary(name: str) -> str:
    """Resolve a binary name to its full path, or raise if not found."""
    path = shutil.which(name)
    if path is None:
        raise RuntimeError(
            f"Binary '{name}' not found in PATH. "
            f"Set the correct path via environment variable."
        )
    return path


def resolve_binary_optional(name: str) -> str | None:
    """Like resolve_binary but returns None if not found (for optional CLIs)."""
    return shutil.which(name)
