import importlib
import pytest


def test_defaults_without_env(monkeypatch):
    for key in ["CODEX_CMD", "CLAUDE_CMD", "GEMINI_CMD", "DELEGATE_TIMEOUT_SECONDS",
                "DELEGATE_MAX_TASK_CHARS", "STRIP_ANSI", "CODEX_JSON_MODE"]:
        monkeypatch.delenv(key, raising=False)

    import config
    importlib.reload(config)

    assert config.CODEX_CMD == "codex"
    assert config.CLAUDE_CMD == "claude"
    assert config.GEMINI_CMD == "gemini"
    assert config.TIMEOUT == 300
    assert config.MAX_TASK_CHARS == 12000
    assert config.STRIP_ANSI is True
    assert config.CODEX_JSON_MODE is True


def test_env_override(monkeypatch):
    monkeypatch.setenv("DELEGATE_TIMEOUT_SECONDS", "60")
    monkeypatch.setenv("DELEGATE_MAX_TASK_CHARS", "500")

    import config
    importlib.reload(config)

    assert config.TIMEOUT == 60
    assert config.MAX_TASK_CHARS == 500


def test_task_context_threshold_default(monkeypatch):
    monkeypatch.delenv("TASK_CONTEXT_THRESHOLD_CHARS", raising=False)
    monkeypatch.delenv("TMP_DIR_NAME", raising=False)

    import config
    importlib.reload(config)

    assert config.TASK_CONTEXT_THRESHOLD_CHARS == 2000
    assert config.TMP_DIR_NAME == ".mcp_tmp"


def test_task_context_threshold_override(monkeypatch):
    monkeypatch.setenv("TASK_CONTEXT_THRESHOLD_CHARS", "500")
    monkeypatch.setenv("TMP_DIR_NAME", ".custom_tmp")

    import config
    importlib.reload(config)

    assert config.TASK_CONTEXT_THRESHOLD_CHARS == 500
    assert config.TMP_DIR_NAME == ".custom_tmp"


def test_progress_interval_default(monkeypatch):
    monkeypatch.delenv("PROGRESS_INTERVAL_SECONDS", raising=False)

    import config
    importlib.reload(config)

    assert config.PROGRESS_INTERVAL == 15


def test_progress_interval_override(monkeypatch):
    monkeypatch.setenv("PROGRESS_INTERVAL_SECONDS", "30")

    import config
    importlib.reload(config)

    assert config.PROGRESS_INTERVAL == 30


def test_history_dir_name_default(monkeypatch):
    monkeypatch.delenv("HISTORY_DIR_NAME", raising=False)
    import config
    importlib.reload(config)
    assert config.HISTORY_DIR_NAME == ".mcp_history"


def test_history_footer_entries_default(monkeypatch):
    monkeypatch.delenv("HISTORY_FOOTER_ENTRIES", raising=False)
    import config
    importlib.reload(config)
    assert config.HISTORY_FOOTER_ENTRIES == 2


def test_history_summary_chars_default(monkeypatch):
    monkeypatch.delenv("HISTORY_SUMMARY_CHARS", raising=False)
    import config
    importlib.reload(config)
    assert config.HISTORY_SUMMARY_CHARS == 80


def test_history_dir_name_override(monkeypatch):
    monkeypatch.setenv("HISTORY_DIR_NAME", ".custom_history")
    import config
    importlib.reload(config)
    assert config.HISTORY_DIR_NAME == ".custom_history"


def test_history_footer_entries_override(monkeypatch):
    monkeypatch.setenv("HISTORY_FOOTER_ENTRIES", "5")
    import config
    importlib.reload(config)
    assert config.HISTORY_FOOTER_ENTRIES == 5


def test_history_summary_chars_override(monkeypatch):
    monkeypatch.setenv("HISTORY_SUMMARY_CHARS", "200")
    import config
    importlib.reload(config)
    assert config.HISTORY_SUMMARY_CHARS == 200


def test_gemini_cmd_default(monkeypatch):
    monkeypatch.delenv("GEMINI_CMD", raising=False)
    import config
    importlib.reload(config)
    assert config.GEMINI_CMD == "gemini"


def test_gemini_cmd_override(monkeypatch):
    monkeypatch.setenv("GEMINI_CMD", "/usr/local/bin/gemini")
    import config
    importlib.reload(config)
    assert config.GEMINI_CMD == "/usr/local/bin/gemini"


def test_max_delegate_depth_default(monkeypatch):
    monkeypatch.delenv("MAX_DELEGATE_DEPTH", raising=False)
    import config
    importlib.reload(config)
    assert config.MAX_DELEGATE_DEPTH == 1


def test_max_delegate_depth_override(monkeypatch):
    monkeypatch.setenv("MAX_DELEGATE_DEPTH", "2")
    import config
    importlib.reload(config)
    assert config.MAX_DELEGATE_DEPTH == 2


def test_disabled_delegates_default(monkeypatch):
    monkeypatch.delenv("DISABLED_DELEGATES", raising=False)
    import config
    importlib.reload(config)
    assert config.DISABLED_DELEGATES == set()


def test_disabled_delegates_single(monkeypatch):
    monkeypatch.setenv("DISABLED_DELEGATES", "gemini")
    import config
    importlib.reload(config)
    assert config.DISABLED_DELEGATES == {"gemini"}


def test_disabled_delegates_multiple(monkeypatch):
    monkeypatch.setenv("DISABLED_DELEGATES", "gemini,claude")
    import config
    importlib.reload(config)
    assert config.DISABLED_DELEGATES == {"gemini", "claude"}


def test_disabled_delegates_strips_whitespace(monkeypatch):
    monkeypatch.setenv("DISABLED_DELEGATES", " gemini , claude ")
    import config
    importlib.reload(config)
    assert config.DISABLED_DELEGATES == {"gemini", "claude"}


def test_current_delegate_depth_default(monkeypatch):
    monkeypatch.delenv("MCP_DELEGATE_DEPTH", raising=False)
    import config
    importlib.reload(config)
    assert config.CURRENT_DELEGATE_DEPTH == 0


def test_current_delegate_depth_override(monkeypatch):
    monkeypatch.setenv("MCP_DELEGATE_DEPTH", "1")
    import config
    importlib.reload(config)
    assert config.CURRENT_DELEGATE_DEPTH == 1
