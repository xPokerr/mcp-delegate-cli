import json
import os
import re
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

_ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;]*[mGKHF]|\x1b\][^\x07]*\x07|\r")


def strip_ansi(text: str) -> str:
    """Remove ANSI escape sequences and carriage returns from text."""
    return _ANSI_ESCAPE.sub("", text)


def format_response(model: str, status: str, response: str) -> str:
    """Format a successful tool response."""
    return (
        f"[model]\n{model}\n\n"
        f"[status]\n{status}\n\n"
        f"[response]\n{response.strip()}"
    )


def format_error(model: str, status: str, error: str) -> str:
    """Format an error or timeout tool response."""
    return (
        f"[model]\n{model}\n\n"
        f"[status]\n{status}\n\n"
        f"[error]\n{error.strip()}"
    )


def build_task_string(
    action: str,
    target: str | None,
    context: str | None,
    output_format: str | None,
    context_is_file: bool,
) -> str:
    """Build a compact structured task string for the downstream model."""
    lines = [f"ACTION: {action}"]
    if target:
        lines.append(f"TARGET: {target}")
    if context:
        key = "CONTEXT_FILE" if context_is_file else "CONTEXT"
        lines.append(f"{key}: {context}")
    if output_format:
        lines.append(f"OUTPUT: {output_format}")
    return "\n".join(lines)


def write_context_file(content: str, workdir: str, tmp_dir_name: str) -> str:
    """Write content to a temp file and return its absolute path."""
    tmp_dir = Path(workdir) / tmp_dir_name
    tmp_dir.mkdir(exist_ok=True)
    filename = f"ctx_{uuid.uuid4().hex[:8]}.txt"
    path = tmp_dir / filename
    path.write_text(content, encoding="utf-8")
    return str(path)


def cleanup_old_tmp_files(workdir: str, tmp_dir_name: str, max_age_seconds: int) -> None:
    """Delete temp context files older than max_age_seconds."""
    tmp_dir = Path(workdir) / tmp_dir_name
    if not tmp_dir.exists():
        return
    cutoff = time.time() - max_age_seconds
    for f in tmp_dir.glob("ctx_*.txt"):
        if f.stat().st_mtime < cutoff:
            f.unlink(missing_ok=True)


def save_history_entry(
    workdir: str,
    dir_name: str,
    delegate: str,
    task: str,
    response: str,
    duration_s: float,
) -> None:
    """Append one interaction to .mcp_history/{delegate}.jsonl."""
    history_dir = Path(workdir) / dir_name
    history_dir.mkdir(exist_ok=True)
    path = history_dir / f"{delegate}.jsonl"
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "task": task,
        "response": response,
        "duration_s": round(duration_s, 1),
    }
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def load_history(
    workdir: str,
    dir_name: str,
    delegate: str,
    last_n: int,
) -> list[dict]:
    """Return the last last_n entries from .mcp_history/{delegate}.jsonl.

    Returns all entries if last_n == 0. Returns [] if file does not exist.
    """
    path = Path(workdir) / dir_name / f"{delegate}.jsonl"
    if not path.exists():
        return []
    entries = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    return entries[-last_n:] if last_n > 0 else entries


def format_history_footer(
    delegate: str,
    entries: list[dict],
    summary_chars: int,
) -> str:
    """Build a compact footer summarising previous interactions.

    Returns an empty string when entries is empty (no footer appended).
    """
    if not entries:
        return ""

    def _snip(text: str) -> str:
        flat = text.replace("\n", " ")
        if len(flat) > summary_chars:
            return flat[:summary_chars] + "..."
        return flat

    lines = [f"\n─── History ({delegate}, {len(entries)} previous) ───"]
    for i, e in enumerate(entries, 1):
        lines.append(f'  {i}. "{_snip(e["task"])}" → "{_snip(e["response"])}"')
    lines.append(f'Call get_history("{delegate}") for full content.')
    return "\n".join(lines)


def build_history_preview(entries: list[dict], summary_chars: int) -> list[dict]:
    """Return a structured summary of previous interactions."""
    preview = []
    for entry in entries:
        task = str(entry.get("task", "")).replace("\n", " ")
        response = str(entry.get("response", "")).replace("\n", " ")
        if len(task) > summary_chars:
            task = task[:summary_chars] + "..."
        if len(response) > summary_chars:
            response = response[:summary_chars] + "..."
        preview.append(
            {
                "task_summary": task,
                "response_summary": response,
            }
        )
    return preview


def format_history_full(entries: list[dict]) -> str:
    """Build a full formatted string for the get_history tool response."""
    if not entries:
        return "(no history)"
    parts = []
    for i, e in enumerate(entries, 1):
        ts = e.get("timestamp", "unknown")
        dur = e.get("duration_s", "?")
        parts.append(
            f"--- Entry {i} [{ts}] ({dur}s) ---\n"
            f"TASK:\n{e['task']}\n\n"
            f"RESPONSE:\n{e['response']}"
        )
    return "\n\n".join(parts)
