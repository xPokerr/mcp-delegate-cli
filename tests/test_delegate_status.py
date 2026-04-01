import pytest


def test_get_delegate_status_reports_missing_optional_binary(monkeypatch):
    import adapters

    monkeypatch.setattr(adapters, "_resolve_delegate_binary", lambda name: None)
    monkeypatch.setattr(adapters, "DISABLED_DELEGATES", set())

    status = adapters.get_delegate_status("gemini")

    assert status["name"] == "gemini"
    assert status["enabled"] is True
    assert status["available"] is False
    assert status["binary_path"] is None
    assert status["disabled_reason"] is None


def test_get_delegate_status_reports_disabled_delegate(monkeypatch):
    import adapters

    monkeypatch.setattr(adapters, "_resolve_delegate_binary", lambda name: "/usr/bin/codex")
    monkeypatch.setattr(adapters, "DISABLED_DELEGATES", {"codex"})

    status = adapters.get_delegate_status("codex")

    assert status["enabled"] is False
    assert status["available"] is True
    assert status["disabled_reason"] == "disabled by config"
