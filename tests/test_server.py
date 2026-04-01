from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest


def test_prepare_task_returns_structured_payload(tmp_path, monkeypatch):
    import server

    monkeypatch.setattr(server, "_WORKDIR", str(tmp_path))

    result = server.prepare_task(
        action="review",
        target="src/auth.py",
        context="print('hello')",
        output_format="json",
    )

    assert result["task"] == (
        "ACTION: review\n"
        "TARGET: src/auth.py\n"
        "CONTEXT: print('hello')\n"
        "OUTPUT: json"
    )
    assert result["suggested_timeout_seconds"] == 300
    assert result["context_file"] is None


@pytest.mark.asyncio
async def test_delegate_to_codex_returns_structured_payload(monkeypatch):
    import server

    monkeypatch.setattr(server, "_check_delegate", lambda *args, **kwargs: None)
    monkeypatch.setattr(server, "run_codex", AsyncMock(return_value="delegate output"))
    monkeypatch.setattr(server, "load_history", lambda *args, **kwargs: [
        {"task": "previous task", "response": "previous response"}
    ])
    saved = []
    monkeypatch.setattr(server, "save_history_entry", lambda *args, **kwargs: saved.append(args))

    result = await server.delegate_to_codex("current task")

    assert result["model"] == "codex"
    assert result["status"] == "success"
    assert result["response"] == "delegate output"
    assert result["history_preview"] == [
        {
            "task_summary": "previous task",
            "response_summary": "previous response",
        }
    ]
    assert saved


def test_list_delegates_reports_status(monkeypatch):
    import server

    monkeypatch.setattr(server, "get_delegate_statuses", lambda: [
        {
            "name": "codex",
            "enabled": True,
            "available": True,
            "binary_path": "/usr/local/bin/codex",
            "disabled_reason": None,
        },
        {
            "name": "gemini",
            "enabled": False,
            "available": False,
            "binary_path": None,
            "disabled_reason": "disabled by config",
        },
    ])

    result = server.list_delegates()

    assert result["delegates"][0]["name"] == "codex"
    assert result["delegates"][0]["available"] is True
    assert result["delegates"][1]["name"] == "gemini"
    assert result["delegates"][1]["enabled"] is False
    assert result["delegates"][1]["disabled_reason"] == "disabled by config"


@pytest.mark.asyncio
async def test_delegate_to_codex_uses_override_cwd(tmp_path, monkeypatch):
    import server

    override = tmp_path / "nested"
    override.mkdir()

    calls = []

    async def fake_run(task, cwd, timeout=None, ctx=None):
        calls.append((task, cwd))
        return "ok"

    monkeypatch.setattr(server, "_check_delegate", lambda *args, **kwargs: None)
    monkeypatch.setattr(server, "run_codex", fake_run)
    monkeypatch.setattr(server, "load_history", lambda *args, **kwargs: [])
    monkeypatch.setattr(server, "save_history_entry", lambda *args, **kwargs: None)
    monkeypatch.setattr(server, "_WORKDIR", str(tmp_path))

    result = await server.delegate_to_codex("current task", cwd="nested")

    assert result["status"] == "success"
    assert calls == [("current task", str(override))]


@pytest.mark.asyncio
async def test_delegate_to_codex_reads_history_from_override_cwd(tmp_path, monkeypatch):
    import server

    override = tmp_path / "nested"
    override.mkdir()

    history_calls = []

    async def fake_run(task, cwd, timeout=None, ctx=None):
        return "ok"

    def fake_load_history(workdir, dir_name, delegate, last_n):
        history_calls.append(workdir)
        return []

    monkeypatch.setattr(server, "_check_delegate", lambda *args, **kwargs: None)
    monkeypatch.setattr(server, "run_codex", fake_run)
    monkeypatch.setattr(server, "load_history", fake_load_history)
    monkeypatch.setattr(server, "save_history_entry", lambda *args, **kwargs: None)
    monkeypatch.setattr(server, "_WORKDIR", str(tmp_path))

    await server.delegate_to_codex("current task", cwd="nested")

    assert history_calls == [str(override)]
