"""
MCP server that exposes delegate_to_codex and delegate_to_claude tools.

Launch with:
    python server.py

The server communicates over stdio (standard MCP transport).
"""
import logging
import os
import time

from mcp.server.fastmcp import FastMCP, Context

from adapters import run_codex, run_claude, run_gemini
from config import (
    MAX_TASK_CHARS, TASK_CONTEXT_THRESHOLD_CHARS, TMP_DIR_NAME, TIMEOUT,
    HISTORY_DIR_NAME, HISTORY_FOOTER_ENTRIES, HISTORY_SUMMARY_CHARS,
    MAX_DELEGATE_DEPTH, CURRENT_DELEGATE_DEPTH, DISABLED_DELEGATES,
)
from utils import (
    format_response, format_error,
    build_task_string, write_context_file, cleanup_old_tmp_files,
    save_history_entry, load_history, format_history_footer, format_history_full,
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


@mcp.tool()
def prepare_task(
    action: str,
    target: str = "",
    context: str = "",
    output_format: str = "",
) -> str:
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
        return "[prepare_task] action cannot be empty."

    context_is_file = False
    context_value = context.strip() if context else None

    if context_value and len(context_value) > TASK_CONTEXT_THRESHOLD_CHARS:
        context_value = write_context_file(context_value, _WORKDIR, TMP_DIR_NAME)
        context_is_file = True

    task_str = build_task_string(
        action=action.strip(),
        target=target.strip() or None,
        context=context_value,
        output_format=output_format.strip() or None,
        context_is_file=context_is_file,
    )

    suggested_timeout = _estimate_timeout(context or "", target or "")
    return task_str + f"\nSUGGESTED_TIMEOUT: {suggested_timeout}"


@mcp.tool()
def get_history(delegate: str, last_n: int = 5) -> str:
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
        return f'[get_history] Unknown delegate "{delegate}". Use "codex", "claude", or "gemini".'
    entries = load_history(_WORKDIR, HISTORY_DIR_NAME, delegate, last_n)
    return format_history_full(entries)


@mcp.tool()
async def delegate_to_codex(task: str, timeout_seconds: int = 0, ctx: Context = None) -> str:
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
        return format_error("codex", "error", error)

    try:
        previous = load_history(_WORKDIR, HISTORY_DIR_NAME, "codex", HISTORY_FOOTER_ENTRIES)
        start = time.monotonic()
        result = await run_codex(task, _WORKDIR, timeout=timeout_seconds or None, ctx=ctx)
        duration = time.monotonic() - start
        save_history_entry(_WORKDIR, HISTORY_DIR_NAME, "codex", task, result, duration)
        response = format_response("codex", "success", result)
        footer = format_history_footer("codex", previous, HISTORY_SUMMARY_CHARS)
        return response + footer
    except TimeoutError as e:
        return format_error("codex", "timeout", str(e))
    except RuntimeError as e:
        return format_error("codex", "error", str(e))
    except FileNotFoundError as e:
        return format_error("codex", "error", f"CLI not found: {e}")


@mcp.tool()
async def delegate_to_claude(task: str, timeout_seconds: int = 0, ctx: Context = None) -> str:
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
        return format_error("claude", "error", error)

    try:
        previous = load_history(_WORKDIR, HISTORY_DIR_NAME, "claude", HISTORY_FOOTER_ENTRIES)
        start = time.monotonic()
        result = await run_claude(task, _WORKDIR, timeout=timeout_seconds or None, ctx=ctx)
        duration = time.monotonic() - start
        save_history_entry(_WORKDIR, HISTORY_DIR_NAME, "claude", task, result, duration)
        response = format_response("claude", "success", result)
        footer = format_history_footer("claude", previous, HISTORY_SUMMARY_CHARS)
        return response + footer
    except TimeoutError as e:
        return format_error("claude", "timeout", str(e))
    except RuntimeError as e:
        return format_error("claude", "error", str(e))
    except FileNotFoundError as e:
        return format_error("claude", "error", f"CLI not found: {e}")


@mcp.tool()
async def delegate_to_gemini(task: str, timeout_seconds: int = 0, ctx: Context = None) -> str:
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
        return format_error("gemini", "error", error)

    try:
        previous = load_history(_WORKDIR, HISTORY_DIR_NAME, "gemini", HISTORY_FOOTER_ENTRIES)
        start = time.monotonic()
        result = await run_gemini(task, _WORKDIR, timeout=timeout_seconds or None, ctx=ctx)
        duration = time.monotonic() - start
        save_history_entry(_WORKDIR, HISTORY_DIR_NAME, "gemini", task, result, duration)
        response = format_response("gemini", "success", result)
        footer = format_history_footer("gemini", previous, HISTORY_SUMMARY_CHARS)
        return response + footer
    except TimeoutError as e:
        return format_error("gemini", "timeout", str(e))
    except RuntimeError as e:
        return format_error("gemini", "error", str(e))
    except FileNotFoundError as e:
        return format_error("gemini", "error", f"CLI not found: {e}")


if __name__ == "__main__":
    mcp.run()
