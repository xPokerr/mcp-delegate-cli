"""
CLI adapters for delegating tasks to local AI tools.

To add a new adapter (e.g. Gemini):
1. Add a resolve call in the module-level block below
2. Write a run_gemini() function following the same pattern as run_codex/run_claude
3. Expose it in server.py as a new MCP tool
"""
import asyncio
import collections
import json
import logging
import os
import time

from config import (
    CODEX_CMD, CLAUDE_CMD, GEMINI_CMD, TIMEOUT, STRIP_ANSI, CODEX_JSON_MODE,
    PROGRESS_INTERVAL, CURRENT_DELEGATE_DEPTH, resolve_binary, resolve_binary_optional,
)
from utils import strip_ansi

logger = logging.getLogger(__name__)

# Resolve binaries once at import time — fails fast if a required CLI is missing
_CODEX_BIN = resolve_binary(CODEX_CMD)
_CLAUDE_BIN = resolve_binary(CLAUDE_CMD)
# Gemini is optional — server starts fine without it; delegate_to_gemini will error if None
_GEMINI_BIN: str | None = resolve_binary_optional(GEMINI_CMD)


def _extract_text_from_line(raw: str) -> str:
    """
    Given a raw output line (may be JSON or plain text), return a short readable snippet.
    - JSON with known text fields → extract text content
    - Unknown JSON → return empty (avoid noisy event metadata)
    - Plain text → strip ANSI and return
    """
    stripped = raw.strip()
    if not stripped:
        return ""

    try:
        obj = json.loads(stripped)
    except (json.JSONDecodeError, ValueError):
        return strip_ansi(stripped)

    if not isinstance(obj, dict):
        return strip_ansi(stripped)

    # Claude stream-json: assistant message with text content blocks
    if obj.get("type") == "assistant":
        for block in obj.get("message", {}).get("content", []):
            if isinstance(block, dict) and block.get("type") == "text":
                text = block.get("text", "").strip()
                if text:
                    return text

    # Codex: item.completed event
    if obj.get("type") == "item.completed":
        text = obj.get("item", {}).get("text", "").strip()
        if text:
            return text

    # Codex/generic: role-based assistant message
    if obj.get("role") == "assistant":
        content = obj.get("content", "")
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    return block.get("text", "").strip()

    # Unknown JSON event — return nothing (avoids noisy metadata in snippet)
    return ""


def _parse_claude_stream_json(text: str) -> str | None:
    """
    Parse JSONL output from `claude --output-format stream-json`.
    Each line is a separate JSON event. Finds the last {type: "result", result: "..."} event.
    """
    last_result = None
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and obj.get("type") == "result":
            result = obj.get("result", "")
            if result:
                last_result = result
    return last_result


def _parse_codex_jsonl(text: str) -> str | None:
    """
    Parse JSONL output from `codex exec --json`.
    Handles two known event shapes:
      - {role: "assistant", content: str | list}
      - {type: "item.completed", item: {text: str}}
    Returns the last meaningful content found, or None if parsing fails.
    """
    last_content = None
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue

        # Shape 1: role-based message
        if obj.get("role") == "assistant":
            content = obj.get("content", "")
            if isinstance(content, str) and content:
                last_content = content
            elif isinstance(content, list):
                texts = [
                    block.get("text", "")
                    for block in content
                    if isinstance(block, dict) and block.get("type") == "text"
                ]
                joined = "\n".join(t for t in texts if t)
                if joined:
                    last_content = joined

        # Shape 2: item.completed event (actual codex exec --json format)
        elif obj.get("type") == "item.completed":
            item = obj.get("item", {})
            text = item.get("text", "")
            if text:
                last_content = text

    return last_content


def _parse_claude_json(text: str) -> str | None:
    """
    Parse JSON output from `claude --output-format json` (backwards compat fallback).

    Claude Code outputs a JSON array of session events. The final result is
    in the last element with {"type": "result", "result": "..."}.
    Falls back to a plain JSON object with a "result" key for forward compatibility.
    """
    try:
        parsed = json.loads(text.strip())
    except json.JSONDecodeError:
        return None

    # Array of events (actual claude --output-format json format)
    if isinstance(parsed, list):
        for event in reversed(parsed):
            if isinstance(event, dict) and event.get("type") == "result":
                result = event.get("result", "")
                return result if result else None
        return None

    # Single object fallback
    if isinstance(parsed, dict):
        result = parsed.get("result", "")
        return result if result else None

    return None


async def _run_subprocess(
    cmd: list[str],
    cwd: str,
    timeout: int | None = None,
    progress_interval: float | None = None,
    report_progress=None,
) -> tuple[str, str, int]:
    """Run a subprocess and return (stdout, stderr, returncode).

    Reads stdout line by line. If report_progress is provided it is called every
    progress_interval seconds with a snippet of the last 2 non-empty output lines:
        await report_progress(elapsed, effective_timeout, message=str)
    """
    effective_timeout = timeout if (timeout and timeout > 0) else TIMEOUT
    interval = progress_interval if progress_interval is not None else PROGRESS_INTERVAL

    start = time.monotonic()
    child_env = {**os.environ, "MCP_DELEGATE_DEPTH": str(CURRENT_DELEGATE_DEPTH + 1)}
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=cwd,
        env=child_env,
    )

    stdout_lines: list[str] = []
    snippet: collections.deque[str] = collections.deque(maxlen=2)

    try:
        while True:
            elapsed = time.monotonic() - start
            if elapsed >= effective_timeout:
                proc.kill()
                raise TimeoutError(f"Process timed out after {effective_timeout}s")

            try:
                line_bytes = await asyncio.wait_for(
                    proc.stdout.readline(), timeout=interval
                )
            except asyncio.TimeoutError:
                elapsed = time.monotonic() - start
                if elapsed >= effective_timeout:
                    proc.kill()
                    raise TimeoutError(f"Process timed out after {effective_timeout}s")
                if report_progress is not None:
                    mins, secs = divmod(int(elapsed), 60)
                    time_str = (
                        f"{mins}m {secs}s elapsed" if mins else f"{secs}s elapsed"
                    )
                    msg = f"Still running: {time_str}"
                    if snippet:
                        msg += "\n" + "\n".join(f"> {ln}" for ln in snippet)
                    await report_progress(elapsed, effective_timeout, message=msg)
                continue

            if not line_bytes:
                break  # EOF

            line_str = line_bytes.decode("utf-8", errors="replace")
            stdout_lines.append(line_str)
            readable = _extract_text_from_line(line_str)
            if readable:
                # Keep only the first line of extracted text for a compact snippet
                first_line = readable.split("\n")[0].strip()
                if first_line:
                    snippet.append(first_line)

    except asyncio.CancelledError:
        proc.kill()
        raise

    await proc.wait()
    stderr_bytes = await proc.stderr.read()
    elapsed = time.monotonic() - start

    stdout = "".join(stdout_lines)
    stderr = stderr_bytes.decode("utf-8", errors="replace")
    if STRIP_ANSI:
        stdout = strip_ansi(stdout)
        stderr = strip_ansi(stderr)

    logger.info("cmd=%s exit=%d elapsed=%.1fs", cmd[0], proc.returncode, elapsed)
    return stdout, stderr, proc.returncode


async def run_codex(task: str, cwd: str, timeout: int | None = None, ctx=None) -> str:
    """
    Invoke `codex exec` non-interactively with the given task.
    Returns cleaned output text. Raises RuntimeError or TimeoutError on failure.
    """
    cmd = [_CODEX_BIN, "exec", "--skip-git-repo-check"]
    if CODEX_JSON_MODE:
        cmd.append("--json")
    cmd.append(task)

    logger.info("delegate_to_codex task=%r timeout=%s", task[:80], timeout or TIMEOUT)
    stdout, stderr, rc = await _run_subprocess(
        cmd, cwd, timeout=timeout,
        report_progress=ctx.report_progress if ctx else None,
    )

    if rc != 0:
        detail = stderr.strip() or stdout.strip() or f"exit code {rc}"
        raise RuntimeError(f"codex exit code {rc}: {detail}")

    if CODEX_JSON_MODE:
        parsed = _parse_codex_jsonl(stdout)
        if parsed:
            return parsed

    return stdout.strip() or stderr.strip() or "(no output)"


async def run_gemini(task: str, cwd: str, timeout: int | None = None, ctx=None) -> str:
    """
    Invoke `gemini --prompt` non-interactively with the given task.
    Returns cleaned output text. Raises RuntimeError or TimeoutError on failure.

    # ADAPTER NOTE: If your Gemini CLI version uses different flags, edit here.
    # Current flags:
    #   --prompt         non-interactive (headless) mode
    #   --yolo           auto-approve all tool actions (no confirmation prompts)
    #   --output-format  text output (plain text response)
    """
    if _GEMINI_BIN is None:
        raise FileNotFoundError(
            f"Gemini CLI '{GEMINI_CMD}' not found in PATH. "
            "Install it or set GEMINI_CMD to the correct path."
        )
    cmd = [
        _GEMINI_BIN,
        "--prompt", task,
        "--yolo",
        "--output-format", "text",
    ]

    logger.info("delegate_to_gemini task=%r timeout=%s", task[:80], timeout or TIMEOUT)
    stdout, stderr, rc = await _run_subprocess(
        cmd, cwd, timeout=timeout,
        report_progress=ctx.report_progress if ctx else None,
    )

    if rc != 0:
        detail = stderr.strip() or stdout.strip() or f"exit code {rc}"
        raise RuntimeError(f"gemini exit code {rc}: {detail}")

    return stdout.strip() or stderr.strip() or "(no output)"


async def run_claude(task: str, cwd: str, timeout: int | None = None, ctx=None) -> str:
    """
    Invoke `claude --print` non-interactively with the given task.
    Returns cleaned output text. Raises RuntimeError or TimeoutError on failure.

    # ADAPTER NOTE: If your Claude CLI version uses different flags, edit here.
    # Current flags:
    #   --print                         non-interactive mode
    #   --verbose                       required by some versions (e.g. Windows) for stream-json
    #   --dangerously-skip-permissions  no tool permission prompts
    #   --output-format stream-json     real-time JSONL events (one per line)
    #   --no-session-persistence        don't save this session to disk
    """
    cmd = [
        _CLAUDE_BIN,
        "--print",
        "--verbose",
        "--dangerously-skip-permissions",
        "--output-format", "stream-json",
        "--no-session-persistence",
        task,
    ]

    logger.info("delegate_to_claude task=%r timeout=%s", task[:80], timeout or TIMEOUT)
    stdout, stderr, rc = await _run_subprocess(
        cmd, cwd, timeout=timeout,
        report_progress=ctx.report_progress if ctx else None,
    )

    if rc != 0:
        detail = stderr.strip() or stdout.strip() or f"exit code {rc}"
        raise RuntimeError(f"claude exit code {rc}: {detail}")

    parsed = _parse_claude_stream_json(stdout)
    if parsed:
        return parsed

    # Fallback: older claude versions may output a JSON array
    parsed = _parse_claude_json(stdout)
    if parsed:
        return parsed

    return stdout.strip() or stderr.strip() or "(no output)"
