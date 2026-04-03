# mcp-delegate-cli

> An MCP server that lets your AI orchestrator delegate tasks to locally installed **Codex**, **Claude**, and **Gemini** CLIs — using your existing subscriptions, no API keys needed.

## Community

Want to discuss the project, ask questions, or report an issue? [Join the Discord server](https://discord.gg/fQpAaQs72q)

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

The delegated CLI receives **only** the task string you pass into the delegate tool — no conversation history, no user messages, no hidden metadata.

---

## Tools

| Tool | Description |
|------|-------------|
| `prepare_task(action, target, context, output_format)` | Build a compact, structured task string. Automatically offloads large context blocks to a temp file and returns a structured payload with `task` and `suggested_timeout_seconds`. |
| `delegate_to_codex(task, timeout_seconds, cwd)` | Forward `task` to `codex exec`. Returns structured JSON-like data including `response`, `history_preview`, and effective `cwd`. |
| `delegate_to_claude(task, timeout_seconds, cwd)` | Forward `task` to `claude --print`. |
| `delegate_to_gemini(task, timeout_seconds, cwd)` | Forward `task` to `gemini --prompt`. |
| `get_history(delegate, last_n)` | Retrieve structured full history for a delegate. |
| `list_delegates()` | Report whether each delegate is enabled, available on PATH, and which binary path will be used. |

### Typical orchestrator flow

```
1. prepare_task(action="refactor", target="src/auth.py", context="...", output_format="unified diff")
   → returns `{status, task, suggested_timeout_seconds, context_file}`

2. delegate_to_codex(task=<above>.task, timeout_seconds=<above>.suggested_timeout_seconds)
   → returns `{model, status, response, history_preview, duration_seconds, cwd}`

3. (optional) get_history("codex", last_n=3)
   → returns `{delegate, count, entries, formatted}`
```

### Structured responses

Successful delegate calls now return structured data instead of an appended text footer:

```json
{
  "model": "codex",
  "status": "success",
  "response": "refactor complete",
  "history_preview": [
    {
      "task_summary": "review src/auth.py",
      "response_summary": "found 2 issues"
    }
  ],
  "duration_seconds": 12.4,
  "cwd": "/absolute/project/path"
}
```

This keeps machine-readable outputs clean, including cases like `OUTPUT: json` or `OUTPUT: unified diff only`.

History is saved under `.mcp_history/<delegate>.jsonl` inside the effective working directory used for that delegate call. It persists across restarts.

---

## Requirements

- Python 3.11+
- [`codex`](https://github.com/openai/codex) CLI installed and authenticated
- [`claude`](https://docs.anthropic.com/en/docs/claude-code) CLI installed and authenticated
- [`gemini`](https://github.com/google-gemini/gemini-cli) CLI installed and authenticated *(optional — only needed for `delegate_to_gemini`)*

---

## Quickstart

If you just want to install the server and make it work, do this:

### 1. Install the server

With `pipx`:

```bash
pipx install git+https://github.com/xPokerr/mcp-delegate-cli.git
```

Or with `uv`:

```bash
uv tool install git+https://github.com/xPokerr/mcp-delegate-cli.git
```

### 2. Add it to your MCP client

Gemini CLI:

```json
{
  "mcpServers": {
    "delegate-cli": {
      "command": "mcp-delegate-cli",
      "env": { "DISABLED_DELEGATES": "gemini" }
    }
  }
}
```

Claude Code:

```json
{
  "mcpServers": {
    "delegate-cli": {
      "command": "mcp-delegate-cli",
      "env": { "DISABLED_DELEGATES": "claude" }
    }
  }
}
```

Windows fallback if the command is not on PATH:

```json
{
  "mcpServers": {
    "delegate-cli": {
      "command": "py",
      "args": ["-m", "mcp_delegate_cli"],
      "env": { "DISABLED_DELEGATES": "gemini" }
    }
  }
}
```

### 3. Restart your MCP client

Restart Gemini or Claude Code so it picks up the new MCP server.

### 4. Verify it works

Call:

- `list_delegates()`
- then one of `delegate_to_codex(...)`, `delegate_to_claude(...)`, or `delegate_to_gemini(...)`

If `list_delegates()` shows an installed CLI as available, the server is ready to use.

---

## Installation

### Recommended: install as a tool

This is the easiest path on both macOS and Windows.

With `pipx`:

```bash
pipx install git+https://github.com/xPokerr/mcp-delegate-cli.git
```

With `uv`:

```bash
uv tool install git+https://github.com/xPokerr/mcp-delegate-cli.git
```

After install, the MCP server command is simply:

```bash
mcp-delegate-cli
```

### Fallback: install from a local clone

```bash
git clone https://github.com/xPokerr/mcp-delegate-cli.git
cd mcp-delegate-cli
python -m pip install -e .
cp .env.example .env   # optional: adjust defaults
```

### Fallback: module entrypoint

If your environment does not expose the `mcp-delegate-cli` command on PATH, you can always run:

```bash
python -m mcp_delegate_cli
```

On Windows, `py -m mcp_delegate_cli` usually works as well.

---

## Configuration

All settings are optional — defaults work out of the box.

| Variable | Default | Description |
|---|---|---|
| `CODEX_CMD` | `codex` | Path or name of the Codex binary |
| `CLAUDE_CMD` | `claude` | Path or name of the Claude binary |
| `GEMINI_CMD` | `gemini` | Path or name of the Gemini CLI binary |
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
| `MAX_DELEGATE_DEPTH` | `1` | Max delegate chain depth. `1` means subprocesses cannot re-delegate (prevents loops) |
| `DISABLED_DELEGATES` | `` | Comma-separated delegates to disable. Set to your orchestrator name to prevent self-calls (e.g. `gemini`) |

---

## Connecting to Gemini CLI

### macOS / Linux

Add the server to Gemini's global MCP config at `~/.gemini/settings.json`:

```json
{
  "mcpServers": {
    "delegate-cli": {
      "command": "mcp-delegate-cli",
      "env": { "DISABLED_DELEGATES": "gemini" }
    }
  }
}
```

### Windows

If `mcp-delegate-cli` is on PATH, use the same config as above. If not, use the Python module fallback:

```json
{
  "mcpServers": {
    "delegate-cli": {
      "command": "py",
      "args": ["-m", "mcp_delegate_cli"],
      "env": { "DISABLED_DELEGATES": "gemini" }
    }
  }
}
```

> `DISABLED_DELEGATES=gemini` prevents Gemini from accidentally calling `delegate_to_gemini` on itself.

`cwd` is optional. Most users should leave it out of the global config.

Only set `cwd` if you want to force the server to always work inside one specific directory. If you omit it, the server uses the working directory of the MCP client process, and individual delegate calls can still pass `cwd` when needed.

The tools are available in every new Gemini session automatically. For an existing session, restart or use `/resume` to pick them up.

---

## Connecting to Claude Code

### macOS / Linux

Create or edit `.mcp.json` in your project's working directory:

```json
{
  "mcpServers": {
    "delegate-cli": {
      "command": "mcp-delegate-cli",
      "env": { "DISABLED_DELEGATES": "claude" }
    }
  }
}
```

### Windows

If the console script is not visible on PATH, use the Python module fallback:

```json
{
  "mcpServers": {
    "delegate-cli": {
      "command": "py",
      "args": ["-m", "mcp_delegate_cli"],
      "env": { "DISABLED_DELEGATES": "claude" }
    }
  }
}
```

> `DISABLED_DELEGATES=claude` prevents Claude from calling `delegate_to_claude` on itself.

`cwd` is optional here as well and usually does not need to be set.

---

## Notes

- Packaging is now cross-platform: `pipx`, `uv tool install`, `python -m pip install`, and `python -m mcp_delegate_cli` all work with the same codebase.
- `cwd` is optional in MCP config. Leave it out unless you want to pin the server to a single directory.
- Delegate binaries are resolved lazily. The server can start even if one of the CLIs is not installed yet.
- `list_delegates()` lets the orchestrator inspect availability before trying a call.
- Delegate calls now accept an optional `cwd` override. Relative paths are resolved from the server startup directory.
- Subprocess output drains both `stdout` and `stderr` concurrently, which avoids deadlocks when a CLI emits heavy stderr output.

---

## Running tests

```bash
python -m pytest tests/ -v
```

76 tests covering config, packaging, utils, history, and adapter behavior.

---

## Project structure

```
mcp-delegate-cli/
├── pyproject.toml      # package metadata + console script entrypoint
├── mcp_delegate_cli/   # module entrypoint for `python -m mcp_delegate_cli`
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
