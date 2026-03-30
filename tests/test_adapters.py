import asyncio
import json
import pytest
from unittest.mock import AsyncMock, patch, MagicMock, call


def make_process(stdout: bytes, stderr: bytes = b"", returncode: int = 0):
    """
    Build a mock subprocess whose stdout is readable line-by-line.
    Mirrors the asyncio.StreamReader API used by _run_subprocess.
    """
    proc = MagicMock()

    lines = stdout.splitlines(keepends=True)
    lines.append(b"")  # EOF sentinel

    call_count = 0

    async def mock_readline():
        nonlocal call_count
        if call_count < len(lines):
            result = lines[call_count]
            call_count += 1
            return result
        return b""

    proc.stdout = MagicMock()
    proc.stdout.readline = mock_readline
    proc.stderr = MagicMock()
    proc.stderr.read = AsyncMock(return_value=stderr)
    proc.wait = AsyncMock(return_value=returncode)
    proc.returncode = returncode
    proc.kill = MagicMock()
    return proc


# ---- _extract_text_from_line ----

def test_extract_plain_text():
    from adapters import _extract_text_from_line
    assert _extract_text_from_line("hello world\n") == "hello world"


def test_extract_claude_assistant_event():
    from adapters import _extract_text_from_line
    line = json.dumps({
        "type": "assistant",
        "message": {"content": [{"type": "text", "text": "thinking..."}]},
    })
    assert _extract_text_from_line(line) == "thinking..."


def test_extract_codex_item_completed():
    from adapters import _extract_text_from_line
    line = json.dumps({"type": "item.completed", "item": {"text": "def foo(): pass"}})
    assert _extract_text_from_line(line) == "def foo(): pass"


def test_extract_unknown_json_returns_empty():
    from adapters import _extract_text_from_line
    line = json.dumps({"type": "system", "subtype": "init", "session_id": "abc"})
    assert _extract_text_from_line(line) == ""


def test_extract_empty_line():
    from adapters import _extract_text_from_line
    assert _extract_text_from_line("   \n") == ""


# ---- _parse_claude_stream_json ----

def test_parse_claude_stream_json_success():
    from adapters import _parse_claude_stream_json
    text = (
        '{"type":"system","subtype":"init"}\n'
        '{"type":"assistant","message":{"content":[{"type":"text","text":"thinking"}]}}\n'
        '{"type":"result","subtype":"success","result":"great answer","is_error":false}\n'
    )
    assert _parse_claude_stream_json(text) == "great answer"


def test_parse_claude_stream_json_no_result():
    from adapters import _parse_claude_stream_json
    text = '{"type":"system","subtype":"init"}\n'
    assert _parse_claude_stream_json(text) is None


def test_parse_claude_stream_json_returns_last_result():
    from adapters import _parse_claude_stream_json
    text = (
        '{"type":"result","result":"first"}\n'
        '{"type":"result","result":"second"}\n'
    )
    assert _parse_claude_stream_json(text) == "second"


# ---- codex ----

@pytest.mark.asyncio
async def test_run_codex_success_jsonl_role_based():
    jsonl = b'{"role":"assistant","content":"hello from codex"}\n'
    proc = make_process(jsonl)
    with patch("adapters.asyncio.create_subprocess_exec", return_value=proc):
        from adapters import run_codex
        result = await run_codex("do something", "/tmp")
    assert result == "hello from codex"


@pytest.mark.asyncio
async def test_run_codex_success_jsonl_item_completed():
    jsonl = (
        b'{"type":"thread.started","thread_id":"abc"}\n'
        b'{"type":"turn.started"}\n'
        b'{"type":"item.completed","item":{"id":"item_0","type":"agent_message","text":"def hello(): pass"}}\n'
        b'{"type":"turn.completed"}\n'
    )
    proc = make_process(jsonl)
    with patch("adapters.asyncio.create_subprocess_exec", return_value=proc):
        from adapters import run_codex
        result = await run_codex("do something", "/tmp")
    assert result == "def hello(): pass"


@pytest.mark.asyncio
async def test_run_codex_fallback_plain_text():
    proc = make_process(b"plain output\n")
    with patch("adapters.asyncio.create_subprocess_exec", return_value=proc):
        from adapters import run_codex
        result = await run_codex("do something", "/tmp")
    assert "plain output" in result


@pytest.mark.asyncio
async def test_run_codex_nonzero_exit():
    proc = make_process(b"", b"some error", returncode=1)
    with patch("adapters.asyncio.create_subprocess_exec", return_value=proc):
        from adapters import run_codex
        with pytest.raises(RuntimeError, match="exit code 1"):
            await run_codex("do something", "/tmp")


# ---- claude ----

@pytest.mark.asyncio
async def test_run_claude_success_stream_json():
    # Primary format: JSONL events, one per line (--output-format stream-json)
    payload = (
        b'{"type":"system","subtype":"init","session_id":"abc"}\n'
        b'{"type":"assistant","message":{"content":[{"type":"text","text":"thinking..."}]}}\n'
        b'{"type":"result","subtype":"success","result":"great answer","is_error":false}\n'
    )
    proc = make_process(payload)
    with patch("adapters.asyncio.create_subprocess_exec", return_value=proc):
        from adapters import run_claude
        result = await run_claude("do something", "/tmp")
    assert result == "great answer"


@pytest.mark.asyncio
async def test_run_claude_fallback_json_array():
    # Fallback: older claude --output-format json produces a JSON array
    payload = json.dumps([
        {"type": "system", "subtype": "init"},
        {"type": "assistant", "message": {"content": [{"type": "text", "text": "thinking..."}]}},
        {"type": "result", "subtype": "success", "result": "great answer", "is_error": False},
    ]).encode() + b"\n"
    proc = make_process(payload)
    with patch("adapters.asyncio.create_subprocess_exec", return_value=proc):
        from adapters import run_claude
        result = await run_claude("do something", "/tmp")
    assert result == "great answer"


@pytest.mark.asyncio
async def test_run_claude_fallback_plain():
    proc = make_process(b"plain claude output\n")
    with patch("adapters.asyncio.create_subprocess_exec", return_value=proc):
        from adapters import run_claude
        result = await run_claude("do something", "/tmp")
    assert "plain claude output" in result


@pytest.mark.asyncio
async def test_run_claude_nonzero_exit():
    proc = make_process(b"", b"auth error", returncode=1)
    with patch("adapters.asyncio.create_subprocess_exec", return_value=proc):
        from adapters import run_claude
        with pytest.raises(RuntimeError, match="exit code 1"):
            await run_claude("do something", "/tmp")


# ---- progress notifications ----

@pytest.mark.asyncio
async def test_run_subprocess_sends_progress_on_slow_process():
    """Progress callback fires when readline() takes longer than the interval."""
    call_count = 0

    async def slow_readline():
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            # First call: slow — will be cancelled by wait_for(timeout=0.02)
            await asyncio.sleep(0.05)
            return b"unreachable\n"
        elif call_count == 2:
            return b"done\n"
        return b""

    proc = MagicMock()
    proc.stdout = MagicMock()
    proc.stdout.readline = slow_readline
    proc.stderr = MagicMock()
    proc.stderr.read = AsyncMock(return_value=b"")
    proc.wait = AsyncMock(return_value=0)
    proc.returncode = 0
    proc.kill = MagicMock()

    progress_calls = []

    async def fake_progress(elapsed, total, message=None):
        progress_calls.append(message)

    with patch("adapters.asyncio.create_subprocess_exec", return_value=proc):
        from adapters import _run_subprocess
        stdout, stderr, rc = await _run_subprocess(
            ["echo", "hi"], "/tmp",
            timeout=10,
            progress_interval=0.02,
            report_progress=fake_progress,
        )

    assert "done" in stdout
    assert rc == 0
    assert len(progress_calls) >= 1
    assert progress_calls[0] is not None
    assert "running" in progress_calls[0].lower()


@pytest.mark.asyncio
async def test_run_subprocess_progress_includes_snippet():
    """Progress message includes a snippet of the last output lines."""
    call_count = 0

    async def readline_with_output():
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return b"def hello_world():\n"
        elif call_count == 2:
            # Slow — triggers progress with snippet from line 1
            await asyncio.sleep(0.05)
            return b"unreachable\n"
        return b""

    proc = MagicMock()
    proc.stdout = MagicMock()
    proc.stdout.readline = readline_with_output
    proc.stderr = MagicMock()
    proc.stderr.read = AsyncMock(return_value=b"")
    proc.wait = AsyncMock(return_value=0)
    proc.returncode = 0
    proc.kill = MagicMock()

    progress_calls = []

    async def fake_progress(elapsed, total, message=None):
        progress_calls.append(message)

    with patch("adapters.asyncio.create_subprocess_exec", return_value=proc):
        from adapters import _run_subprocess
        await _run_subprocess(
            ["echo", "hi"], "/tmp",
            timeout=10,
            progress_interval=0.02,
            report_progress=fake_progress,
        )

    assert len(progress_calls) >= 1
    assert "> def hello_world():" in progress_calls[0]


# ---- gemini ----

@pytest.mark.asyncio
async def test_run_gemini_success():
    proc = make_process(b"Gemini response text\n")
    with patch("adapters.asyncio.create_subprocess_exec", return_value=proc), \
         patch("adapters._GEMINI_BIN", "/usr/bin/gemini"):
        from adapters import run_gemini
        result = await run_gemini("do something", "/tmp")
    assert "Gemini response text" in result


@pytest.mark.asyncio
async def test_run_gemini_not_installed():
    with patch("adapters._GEMINI_BIN", None):
        from adapters import run_gemini
        with pytest.raises(FileNotFoundError, match="not found in PATH"):
            await run_gemini("do something", "/tmp")


@pytest.mark.asyncio
async def test_run_gemini_nonzero_exit():
    proc = make_process(b"", b"auth error", returncode=1)
    with patch("adapters.asyncio.create_subprocess_exec", return_value=proc), \
         patch("adapters._GEMINI_BIN", "/usr/bin/gemini"):
        from adapters import run_gemini
        with pytest.raises(RuntimeError, match="exit code 1"):
            await run_gemini("do something", "/tmp")


# ---- depth env injection ----

@pytest.mark.asyncio
async def test_run_subprocess_injects_depth_env():
    """_run_subprocess passes MCP_DELEGATE_DEPTH+1 to the child process env."""
    proc = make_process(b"output\n")
    captured_kwargs = {}

    async def fake_exec(*args, **kwargs):
        captured_kwargs.update(kwargs)
        return proc

    with patch("adapters.asyncio.create_subprocess_exec", side_effect=fake_exec), \
         patch("adapters.CURRENT_DELEGATE_DEPTH", 0):
        from adapters import _run_subprocess
        await _run_subprocess(["echo", "hi"], "/tmp", timeout=10)

    assert "env" in captured_kwargs
    assert captured_kwargs["env"]["MCP_DELEGATE_DEPTH"] == "1"


@pytest.mark.asyncio
async def test_run_subprocess_depth_increments():
    """Depth in child env is always CURRENT_DELEGATE_DEPTH + 1."""
    proc = make_process(b"output\n")
    captured_kwargs = {}

    async def fake_exec(*args, **kwargs):
        captured_kwargs.update(kwargs)
        return proc

    with patch("adapters.asyncio.create_subprocess_exec", side_effect=fake_exec), \
         patch("adapters.CURRENT_DELEGATE_DEPTH", 2):
        from adapters import _run_subprocess
        await _run_subprocess(["echo", "hi"], "/tmp", timeout=10)

    assert captured_kwargs["env"]["MCP_DELEGATE_DEPTH"] == "3"


@pytest.mark.asyncio
async def test_run_subprocess_timeout_with_progress():
    """TimeoutError raised after effective_timeout even with progress callbacks."""
    async def never_readline():
        await asyncio.sleep(999)
        return b"output\n"

    proc = MagicMock()
    proc.stdout = MagicMock()
    proc.stdout.readline = never_readline
    proc.stderr = MagicMock()
    proc.stderr.read = AsyncMock(return_value=b"")
    proc.wait = AsyncMock(return_value=0)
    proc.returncode = 0
    proc.kill = MagicMock()

    with patch("adapters.asyncio.create_subprocess_exec", return_value=proc):
        from adapters import _run_subprocess
        with pytest.raises(TimeoutError, match="timed out after 0.1s"):
            await _run_subprocess(
                ["echo", "hi"], "/tmp",
                timeout=0.1,
                progress_interval=0.04,
                report_progress=None,
            )
    proc.kill.assert_called_once()
