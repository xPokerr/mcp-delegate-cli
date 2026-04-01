import importlib
import tomllib
from pathlib import Path


def test_pyproject_declares_console_script():
    data = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    assert data["project"]["scripts"]["mcp-delegate-cli"] == "mcp_delegate_cli.__main__:main"
    assert data["project"]["requires-python"] == ">=3.11"


def test_module_main_delegates_to_server_main(monkeypatch):
    module = importlib.import_module("mcp_delegate_cli.__main__")
    calls = []
    monkeypatch.setattr(module, "run_server", lambda: calls.append("called"))
    module.main()
    assert calls == ["called"]


def test_server_main_runs_fastmcp(monkeypatch):
    import server

    calls = []
    monkeypatch.setattr(server.mcp, "run", lambda: calls.append("run"))
    server.main()
    assert calls == ["run"]
