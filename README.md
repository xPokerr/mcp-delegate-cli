# mcp-delegate-cli

> An MCP server that lets your AI orchestrator delegate tasks to locally installed **Codex** and **Claude** CLIs — using your existing subscriptions, no API keys needed.

---

## What it does

When you're working with an AI orchestrator (like Gemini CLI or Claude Code), it sometimes makes sense to hand off a specific task to a different model. This server exposes MCP tools that do exactly that: they take a task string and forward it to `codex exec` or `claude --print` running on your machine.

```
Orchestrator (e.g. Gemini)
        │
        │  delegate_to_codex("refactor src/auth.py to use async/await")
        ▼
  mcp-delegate-cli  ──►  codex exec "refactor src/auth.py..."
                    ◄──  response
        │
        │  [response] I've refactored...
        ▼
    Orchestrator
```

The delegated CLI receives **only** the task string — no conversation history, no user messages, no metadata.

---

## Tools

| Tool | Description |
|------|-------------|
| `prepare_task(action, target, context, output_format)` | Build a compact, structured task string. Automatically offloads large context blocks to a temp file. Returns a `SUGGESTED_TIMEOUT` value. |
| `delegate_to_codex(task, timeout_seconds)` | Forward `task` to `codex exec`. |
| `delegate_to_claude(task, timeout_seconds)` | Forward `task` to `claude --print`. |
| `get_history(delegate, last_n)` | Retrieve the last N recorded interactions with a delegate. Useful for passing prior context into a new call. |

### Typical orchestrator flow

```
1. prepare_task(action="refactor", target="src/auth.py", context="...", output_format="unified diff")
   → returns compact task string + SUGGESTED_TIMEOUT: 300

2. delegate_to_codex(task=<above>, timeout_seconds=300)
   → returns response + history footer showing last 2 interactions

3. (optional) get_history("codex", last_n=3)
   → returns full task + response for the last 3 calls
```

### History footer

Every successful delegate response includes a compact footer so the orchestrator always knows what was asked before:

```
─── History (codex, 2 previous) ───
  1. "refactor the auth module in src/auth.py..." → "I've refactored the auth mo..."
  2. "add unit tests for the login function..."   → "Here are the unit tests for..."
Call get_history("codex") for full content.
```

History is saved to `.mcp_history/codex.jsonl` and `.mcp_history/claude.jsonl` in the server's working directory. It persists across restarts.

---

## Requirements

- Python 3.11+
- [`codex`](https://github.com/openai/codex) CLI installed and authenticated
- [`claude`](https://docs.anthropic.com/en/docs/claude-code) CLI installed and authenticated

---

## Installation

```bash
git clone https://github.com/xPokerr/mcp-delegate-cli.git
cd mcp-delegate-cli
pip install -r requirements.txt
cp .env.example .env   # optional: adjust defaults
```

---

## Configuration

All settings are optional — defaults work out of the box.

| Variable | Default | Description |
|---|---|---|
| `CODEX_CMD` | `codex` | Path or name of the Codex binary |
| `CLAUDE_CMD` | `claude` | Path or name of the Claude binary |
| `DELEGATE_TIMEOUT_SECONDS` | `300` | Default max seconds per delegated call |
| `DELEGATE_MAX_TASK_CHARS` | `12000` | Max task string length |
| `STRIP_ANSI` | `true` | Strip ANSI codes from CLI output |
| `CODEX_JSON_MODE` | `true` | Use `--json` flag with `codex exec` |
| `TASK_CONTEXT_THRESHOLD_CHARS` | `2000` | Context longer than this is written to a temp file |
| `TMP_DIR_NAME` | `.mcp_tmp` | Subdirectory for temp context files |
| `PROGRESS_INTERVAL_SECONDS` | `15` | How often to send a progress heartbeat during long calls |
| `HISTORY_DIR_NAME` | `.mcp_history` | Subdirectory for interaction history files |
| `HISTORY_FOOTER_ENTRIES` | `2` | How many previous interactions to show in the footer |
| `HISTORY_SUMMARY_CHARS` | `80` | Max chars per entry in the history footer |

---

## Connecting to Gemini CLI

Add the server to Gemini's global MCP config at `~/.gemini/settings.json`:

```json
{
  "mcpServers": {
    "delegate-cli": {
      "command": "python3.11",
      "args": ["/absolute/path/to/mcp-delegate-cli/server.py"],
      "cwd": "/the/project/directory/where/gemini/is/working"
    }
  }
}
```

> The `cwd` field sets the working directory for the server process. All delegated CLI calls run in that directory, so set it to wherever your project lives.

The tools are available in every new Gemini session automatically. For an existing session, restart or use `/resume` to pick them up.

---

## Connecting to Claude Code

Create or edit `.mcp.json` in your project's working directory:

```json
{
  "mcpServers": {
    "delegate-cli": {
      "command": "python3.11",
      "args": ["/absolute/path/to/mcp-delegate-cli/server.py"]
    }
  }
}
```

---

## Running tests

```bash
python3.11 -m pytest tests/ -v
```

53 tests covering config, utils (history, formatting, task building), and adapter behavior (streaming, progress, parsers, timeout).

---

## Project structure

```
mcp-delegate-cli/
├── server.py          # FastMCP app — defines all 4 MCP tools
├── adapters.py        # subprocess logic, streaming, CLI parsers
├── config.py          # env-var config with defaults
├── utils.py           # formatting, task building, history I/O
├── requirements.txt
├── .env.example
└── tests/
    ├── test_adapters.py
    ├── test_config.py
    └── test_utils.py
```

---

## Security note

`claude --dangerously-skip-permissions` bypasses all tool permission prompts. Only run this server in trusted directories on your own machine. Never expose it over a network.

---

## License

MIT
