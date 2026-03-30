import json
import os
import time
from pathlib import Path

from utils import strip_ansi, format_response, format_error, build_task_string, write_context_file, cleanup_old_tmp_files
from utils import save_history_entry, load_history
from utils import format_history_footer, format_history_full


def test_strip_ansi_removes_escape_codes():
    dirty = "\x1b[32mHello\x1b[0m World"
    assert strip_ansi(dirty) == "Hello World"


def test_strip_ansi_passthrough_clean():
    assert strip_ansi("Hello World") == "Hello World"


def test_format_response_success():
    result = format_response("codex", "success", "Some output here")
    assert "[model]\ncodex" in result
    assert "[status]\nsuccess" in result
    assert "[response]\nSome output here" in result


def test_format_error():
    result = format_error("claude", "timeout", "Process timed out after 120s")
    assert "[model]\nclaude" in result
    assert "[status]\ntimeout" in result
    assert "[error]\nProcess timed out after 120s" in result


def test_format_response_strips_whitespace():
    result = format_response("codex", "success", "  output  \n\n")
    assert "[response]\noutput" in result


def test_build_task_string_all_fields():
    result = build_task_string(
        action="refactor",
        target="src/auth.py:45-80",
        context="def foo(): pass",
        output_format="unified diff only",
        context_is_file=False,
    )
    assert "ACTION: refactor" in result
    assert "TARGET: src/auth.py:45-80" in result
    assert "CONTEXT: def foo(): pass" in result
    assert "OUTPUT: unified diff only" in result


def test_build_task_string_file_context():
    result = build_task_string(
        action="explain",
        target=None,
        context="/tmp/ctx_abc.txt",
        output_format=None,
        context_is_file=True,
    )
    assert "ACTION: explain" in result
    assert "CONTEXT_FILE: /tmp/ctx_abc.txt" in result
    assert "TARGET" not in result
    assert "OUTPUT" not in result


def test_build_task_string_action_only():
    result = build_task_string(action="review", target=None, context=None,
                               output_format=None, context_is_file=False)
    assert result.strip() == "ACTION: review"


def test_write_context_file_creates_file(tmp_path):
    path = write_context_file("hello context", str(tmp_path), ".mcp_tmp")
    assert Path(path).exists()
    assert Path(path).read_text() == "hello context"


def test_cleanup_old_tmp_files_removes_old(tmp_path):
    tmp_dir = tmp_path / ".mcp_tmp"
    tmp_dir.mkdir()
    old_file = tmp_dir / "ctx_old.txt"
    old_file.write_text("old")
    old_mtime = time.time() - 300
    os.utime(old_file, (old_mtime, old_mtime))
    cleanup_old_tmp_files(str(tmp_path), ".mcp_tmp", max_age_seconds=60)
    assert not old_file.exists()


def test_cleanup_old_tmp_files_keeps_recent(tmp_path):
    tmp_dir = tmp_path / ".mcp_tmp"
    tmp_dir.mkdir()
    recent_file = tmp_dir / "ctx_recent.txt"
    recent_file.write_text("recent")
    cleanup_old_tmp_files(str(tmp_path), ".mcp_tmp", max_age_seconds=60)
    assert recent_file.exists()


def test_save_history_entry_creates_file(tmp_path):
    save_history_entry(str(tmp_path), ".mcp_history", "codex", "do X", "done X", 3.2)
    path = tmp_path / ".mcp_history" / "codex.jsonl"
    assert path.exists()
    entry = json.loads(path.read_text().strip())
    assert entry["task"] == "do X"
    assert entry["response"] == "done X"
    assert entry["duration_s"] == 3.2
    assert "timestamp" in entry


def test_save_history_entry_appends(tmp_path):
    save_history_entry(str(tmp_path), ".mcp_history", "claude", "task1", "resp1", 1.0)
    save_history_entry(str(tmp_path), ".mcp_history", "claude", "task2", "resp2", 2.0)
    path = tmp_path / ".mcp_history" / "claude.jsonl"
    lines = [l for l in path.read_text().splitlines() if l.strip()]
    assert len(lines) == 2
    assert json.loads(lines[0])["task"] == "task1"
    assert json.loads(lines[1])["task"] == "task2"


def test_load_history_returns_last_n(tmp_path):
    for i in range(5):
        save_history_entry(str(tmp_path), ".mcp_history", "codex", f"task{i}", f"resp{i}", 1.0)
    entries = load_history(str(tmp_path), ".mcp_history", "codex", last_n=3)
    assert len(entries) == 3
    assert entries[0]["task"] == "task2"
    assert entries[-1]["task"] == "task4"


def test_load_history_missing_file_returns_empty(tmp_path):
    entries = load_history(str(tmp_path), ".mcp_history", "codex", last_n=5)
    assert entries == []


def test_load_history_last_n_zero_returns_all(tmp_path):
    for i in range(4):
        save_history_entry(str(tmp_path), ".mcp_history", "codex", f"task{i}", f"resp{i}", 1.0)
    entries = load_history(str(tmp_path), ".mcp_history", "codex", last_n=0)
    assert len(entries) == 4


def test_format_history_footer_empty_returns_empty():
    assert format_history_footer("codex", [], 80) == ""


def test_format_history_footer_shows_entries():
    entries = [
        {"task": "explain auth module", "response": "The auth module does X"},
        {"task": "add tests for login", "response": "Here are the tests"},
    ]
    result = format_history_footer("codex", entries, 80)
    assert "History (codex, 2 previous)" in result
    assert "explain auth module" in result
    assert "add tests for login" in result
    assert 'get_history("codex")' in result


def test_format_history_footer_truncates_long_text():
    entries = [{"task": "a" * 200, "response": "b" * 200}]
    result = format_history_footer("codex", entries, 80)
    assert "..." in result
    assert "a" * 81 not in result


def test_format_history_footer_no_truncation_when_short():
    entries = [{"task": "short task", "response": "short response"}]
    result = format_history_footer("codex", entries, 80)
    assert "..." not in result


def test_format_history_full_empty():
    assert format_history_full([]) == "(no history)"


def test_format_history_full_shows_all_fields():
    entries = [
        {"timestamp": "2026-03-30T10:00:00+00:00", "task": "do X", "response": "done X", "duration_s": 5.1}
    ]
    result = format_history_full(entries)
    assert "2026-03-30T10:00:00+00:00" in result
    assert "do X" in result
    assert "done X" in result
    assert "5.1" in result
