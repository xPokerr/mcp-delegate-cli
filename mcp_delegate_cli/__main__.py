"""Module entrypoint for ``python -m mcp_delegate_cli``."""

from server import main as run_server


def main() -> None:
    """Run the MCP server over stdio."""
    run_server()


if __name__ == "__main__":
    main()
