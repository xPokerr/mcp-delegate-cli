"""
MCP server for delegating tasks to local Codex, Claude, and Gemini CLIs.

Launch with:
    mcp-delegate-cli
or:
    python -m mcp_delegate_cli

The server communicates over stdio (standard MCP transport).
"""
import logging
import os
import time
from pathlib import Path

from mcp.server.fastmcp import FastMCP, Context

from adapters import (
    get_delegate_statuses,
    run_codex,
    run_claude,
    run_gemini,
)
from config import (
    MAX_TASK_CHARS, TASK_CONTEXT_THRESHOLD_CHARS, TMP_DIR_NAME, TIMEOUT,
    HISTORY_DIR_NAME, HISTORY_FOOTER_ENTRIES, HISTORY_SUMMARY_CHARS,
    MAX_DELEGATE_DEPTH, CURRENT_DELEGATE_DEPTH, DISABLED_DELEGATES,
)
from utils import (
    build_task_string, write_context_file, cleanup_old_tmp_files,
    save_history_entry, load_history, format_history_full, build_history_preview,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)

# Capture working directory at startup — subprocesses will run here
_WORKDIR = os.getcwd()

# Clean up leftover temp context files from previous server runs
cleanup_old_tmp_files(_WORKDIR, TMP_DIR_NAME, max_age_seconds=TIMEOUT * 2)

mcp = FastMCP("mcp-delegate-cli")


def _check_delegate(label: str, name: str) -> str | None:
    """Return an error string if delegation should be blocked, else None.

    Two independent guards:
    - DISABLED_DELEGATES: prevents an orchestrator from calling its own delegate
      (e.g. Gemini configured with DISABLED_DELEGATES=gemini cannot call delegate_to_gemini)
    - MAX_DELEGATE_DEPTH: prevents subprocess chains from re-delegating further
      (at depth >= MAX_DELEGATE_DEPTH all delegate tools are blocked)
    """
    if name in DISABLED_DELEGATES:
        return (
            f"[{label}] Delegation to '{name}' is disabled for this instance "
            f"(DISABLED_DELEGATES={','.join(sorted(DISABLED_DELEGATES))})."
        )
    if CURRENT_DELEGATE_DEPTH >= MAX_DELEGATE_DEPTH:
        return (
            f"[{label}] Delegation blocked: already at depth {CURRENT_DELEGATE_DEPTH} "
            f"(MAX_DELEGATE_DEPTH={MAX_DELEGATE_DEPTH}). "
            "Delegates cannot recursively delegate."
        )
    return None


def _validate_task(task: str, label: str) -> str | None:
    """Return an error string if task is invalid, else None."""
    if not task or not task.strip():
        return f"[{label}] Task cannot be empty."
    if len(task) > MAX_TASK_CHARS:
        return (
            f"[{label}] Task is too long ({len(task)} chars). "
            f"Maximum allowed: {MAX_TASK_CHARS}."
        )
    return None


def _estimate_timeout(context: str, target: str) -> int:
    """Heuristic: estimate a reasonable timeout based on task size.

    - Short context, single file  → 300s  (default)
    - Medium context or 2-4 files → 600s
    - Large context or 5+ files   → 900s
    """
    file_count = target.count(",") + target.count("\n") + 1 if target.strip() else 0
    ctx_len = len(context)

    if ctx_len > 4000 or file_count >= 5:
        return 900
    if ctx_len > 1000 or file_count >= 2:
        return 600
    return 300


def _resolve_workdir(cwd: str = "") -> str:
    """Resolve an optional cwd override relative to the server workdir."""
    if not cwd or not cwd.strip():
        return _WORKDIR

    candidate = Path(cwd.strip())
    if not candidate.is_absolute():
        candidate = Path(_WORKDIR) / candidate
    candidate = candidate.resolve()
    if not candidate.exists():
        raise ValueError(f"cwd does not exist: {candidate}")
    if not candidate.is_dir():
        raise ValueError(f"cwd is not a directory: {candidate}")
    return str(candidate)


def _build_delegate_success_payload(
    model: str,
    response: str,
    previous: list[dict],
    duration_s: float,
    cwd: str,
) -> dict:
    return {
        "model": model,
        "status": "success",
        "response": response,
        "history_preview": build_history_preview(previous, HISTORY_SUMMARY_CHARS),
        "duration_seconds": round(duration_s, 1),
        "cwd": cwd,
    }


def _build_delegate_error_payload(model: str, status: str, error: str, cwd: str | None = None) -> dict:
    payload = {
        "model": model,
        "status": status,
        "error": error,
    }
    if cwd is not None:
        payload["cwd"] = cwd
    return payload


@mcp.tool()
def prepare_task(
    action: str,
    target: str = "",
    context: str = "",
    output_format: str = "",
) -> dict:
    """
    Build a compact, structured task string to pass to delegate_to_codex or delegate_to_claude.

    Use this tool when you want to delegate a task in a structured, token-efficient way.
    Large context blocks (code, files, data) are automatically written to a temp file
    so the task string stays short.

    Typical flow:
        1. Call prepare_task(...) to get a compact task string
        2. Read the SUGGESTED_TIMEOUT field at the bottom of the returned string
        3. Pass that string to delegate_to_codex(task=..., timeout_seconds=SUGGESTED_TIMEOUT)
           or delegate_to_claude(task=..., timeout_seconds=SUGGESTED_TIMEOUT)

    Args:
        action:        What to do. Examples: "refactor", "explain", "review", "generate_test"
        target:        What to operate on. Examples: "src/auth.py:45-80", "the login function"
        context:       Supporting content (code block, error message, data). If longer than
                       TASK_CONTEXT_THRESHOLD_CHARS it is written to a file automatically.
        output_format: How the downstream model should format its response.
                       Examples: "unified diff only", "bullet list", "plain explanation"

    Returns:
        A compact task string with a SUGGESTED_TIMEOUT field at the bottom.
        Always pass SUGGESTED_TIMEOUT as timeout_seconds when calling delegate tools.
    """
    if not action or not action.strip():
        return {
            "status": "error",
            "error": "[prepare_task] action cannot be empty.",
        }

    context_is_file = False
    context_file = None
    context_value = context.strip() if context else None

    if context_value and len(context_value) > TASK_CONTEXT_THRESHOLD_CHARS:
        context_value = write_context_file(context_value, _WORKDIR, TMP_DIR_NAME)
        context_is_file = True
        context_file = context_value

    task_str = build_task_string(
        action=action.strip(),
        target=target.strip() or None,
        context=context_value,
        output_format=output_format.strip() or None,
        context_is_file=context_is_file,
    )

    suggested_timeout = _estimate_timeout(context or "", target or "")
    return {
        "status": "success",
        "task": task_str,
        "suggested_timeout_seconds": suggested_timeout,
        "context_file": context_file,
    }


@mcp.tool()
def get_history(delegate: str, last_n: int = 5, cwd: str = "") -> dict:
    """
    Retrieve the last N recorded interactions with a delegate.

    Use this when you want to include prior context in a new delegate call.
    Typically: call get_history, then include relevant parts in prepare_task's
    context argument.

    Args:
        delegate: Which delegate's history to retrieve. Must be "codex" or "claude".
        last_n:   How many recent entries to return (default 5, pass 0 for all).

    Returns:
        Formatted string with full task + response + timestamp for each entry,
        or "(no history)" if no interactions have been recorded yet.
    """
    if delegate not in ("codex", "claude", "gemini"):
        return {
            "status": "error",
            "error": f'[get_history] Unknown delegate "{delegate}". Use "codex", "claude", or "gemini".',
        }
    try:
        resolved_cwd = _resolve_workdir(cwd)
    except ValueError as e:
        return {
            "status": "error",
            "error": str(e),
        }

    entries = load_history(resolved_cwd, HISTORY_DIR_NAME, delegate, last_n)
    return {
        "status": "success",
        "delegate": delegate,
        "count": len(entries),
        "entries": entries,
        "formatted": format_history_full(entries),
        "cwd": resolved_cwd,
    }


@mcp.tool()
def list_delegates() -> dict:
    """Return availability and configuration status for each supported delegate."""
    return {
        "status": "success",
        "delegates": get_delegate_statuses(),
        "current_delegate_depth": CURRENT_DELEGATE_DEPTH,
        "max_delegate_depth": MAX_DELEGATE_DEPTH,
    }


@mcp.tool()
async def delegate_to_codex(
    task: str,
    timeout_seconds: int = 0,
    cwd: str = "",
    ctx: Context = None,
) -> dict:
    """
    Delegate a task to the locally installed Codex CLI.

    IMPORTANT: This tool forwards ONLY the `task` argument to Codex.
    It does NOT receive the user's conversation history, reasoning, or metadata.
    The caller must compose a self-contained, complete task string.

    Args:
        task:            A complete, standalone instruction for Codex to execute.
                         Must be non-empty and under DELEGATE_MAX_TASK_CHARS characters.
        timeout_seconds: Override the default timeout for this call only.
                         Use for long-running tasks (e.g. 600 for analysis, 900 for audits).
                         0 means use the global DELEGATE_TIMEOUT_SECONDS default.

    Returns:
        Formatted string with [model], [status], and [response] or [error] sections.
    """
    error = _check_delegate("delegate_to_codex", "codex") or _validate_task(task, "delegate_to_codex")
    if error:
        return _build_delegate_error_payload("codex", "error", error)

    try:
        resolved_cwd = _resolve_workdir(cwd)
        previous = load_history(resolved_cwd, HISTORY_DIR_NAME, "codex", HISTORY_FOOTER_ENTRIES)
        start = time.monotonic()
        result = await run_codex(task, resolved_cwd, timeout=timeout_seconds or None, ctx=ctx)
        duration = time.monotonic() - start
        save_history_entry(resolved_cwd, HISTORY_DIR_NAME, "codex", task, result, duration)
        return _build_delegate_success_payload("codex", result, previous, duration, resolved_cwd)
    except ValueError as e:
        return _build_delegate_error_payload("codex", "error", str(e))
    except TimeoutError as e:
        return _build_delegate_error_payload("codex", "timeout", str(e), resolved_cwd)
    except RuntimeError as e:
        return _build_delegate_error_payload("codex", "error", str(e), resolved_cwd)
    except FileNotFoundError as e:
        return _build_delegate_error_payload("codex", "error", f"CLI not found: {e}", resolved_cwd)


@mcp.tool()
async def delegate_to_claude(
    task: str,
    timeout_seconds: int = 0,
    cwd: str = "",
    ctx: Context = None,
) -> dict:
    """
    Delegate a task to the locally installed Claude CLI (claude --print).

    IMPORTANT: This tool forwards ONLY the `task` argument to Claude.
    It does NOT receive the user's conversation history, reasoning, or metadata.
    The caller must compose a self-contained, complete task string.

    Args:
        task:            A complete, standalone instruction for Claude to execute.
                         Must be non-empty and under DELEGATE_MAX_TASK_CHARS characters.
        timeout_seconds: Override the default timeout for this call only.
                         Use for long-running tasks (e.g. 600 for analysis, 900 for audits).
                         0 means use the global DELEGATE_TIMEOUT_SECONDS default.

    Returns:
        Formatted string with [model], [status], and [response] or [error] sections.
    """
    error = _check_delegate("delegate_to_claude", "claude") or _validate_task(task, "delegate_to_claude")
    if error:
        return _build_delegate_error_payload("claude", "error", error)

    try:
        resolved_cwd = _resolve_workdir(cwd)
        previous = load_history(resolved_cwd, HISTORY_DIR_NAME, "claude", HISTORY_FOOTER_ENTRIES)
        start = time.monotonic()
        result = await run_claude(task, resolved_cwd, timeout=timeout_seconds or None, ctx=ctx)
        duration = time.monotonic() - start
        save_history_entry(resolved_cwd, HISTORY_DIR_NAME, "claude", task, result, duration)
        return _build_delegate_success_payload("claude", result, previous, duration, resolved_cwd)
    except ValueError as e:
        return _build_delegate_error_payload("claude", "error", str(e))
    except TimeoutError as e:
        return _build_delegate_error_payload("claude", "timeout", str(e), resolved_cwd)
    except RuntimeError as e:
        return _build_delegate_error_payload("claude", "error", str(e), resolved_cwd)
    except FileNotFoundError as e:
        return _build_delegate_error_payload("claude", "error", f"CLI not found: {e}", resolved_cwd)


@mcp.tool()
async def delegate_to_gemini(
    task: str,
    timeout_seconds: int = 0,
    cwd: str = "",
    ctx: Context = None,
) -> dict:
    """
    Delegate a task to the locally installed Gemini CLI (gemini --prompt).

    IMPORTANT: This tool forwards ONLY the `task` argument to Gemini.
    It does NOT receive the user's conversation history, reasoning, or metadata.
    The caller must compose a self-contained, complete task string.

    Args:
        task:            A complete, standalone instruction for Gemini to execute.
                         Must be non-empty and under DELEGATE_MAX_TASK_CHARS characters.
        timeout_seconds: Override the default timeout for this call only.
                         Use for long-running tasks (e.g. 600 for analysis, 900 for audits).
                         0 means use the global DELEGATE_TIMEOUT_SECONDS default.

    Returns:
        Formatted string with [model], [status], and [response] or [error] sections.
    """
    error = _check_delegate("delegate_to_gemini", "gemini") or _validate_task(task, "delegate_to_gemini")
    if error:
        return _build_delegate_error_payload("gemini", "error", error)

    try:
        resolved_cwd = _resolve_workdir(cwd)
        previous = load_history(resolved_cwd, HISTORY_DIR_NAME, "gemini", HISTORY_FOOTER_ENTRIES)
        start = time.monotonic()
        result = await run_gemini(task, resolved_cwd, timeout=timeout_seconds or None, ctx=ctx)
        duration = time.monotonic() - start
        save_history_entry(resolved_cwd, HISTORY_DIR_NAME, "gemini", task, result, duration)
        return _build_delegate_success_payload("gemini", result, previous, duration, resolved_cwd)
    except ValueError as e:
        return _build_delegate_error_payload("gemini", "error", str(e))
    except TimeoutError as e:
        return _build_delegate_error_payload("gemini", "timeout", str(e), resolved_cwd)
    except RuntimeError as e:
        return _build_delegate_error_payload("gemini", "error", str(e), resolved_cwd)
    except FileNotFoundError as e:
        return _build_delegate_error_payload("gemini", "error", f"CLI not found: {e}", resolved_cwd)


def main() -> None:
    """Run the FastMCP server over stdio."""
    mcp.run()


if __name__ == "__main__":
    main()
