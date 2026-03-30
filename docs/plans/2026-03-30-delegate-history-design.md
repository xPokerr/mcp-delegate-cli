# Delegate History — Design

**Date:** 2026-03-30
**Status:** Approved

## Problem

Each call to `delegate_to_codex` / `delegate_to_claude` spawns a fresh subprocess with no memory of previous interactions. The orchestrator (Gemini) has no visibility into what was asked before or what the delegate responded, unless it explicitly tracks this itself.

## Goal

Persist every successful delegate interaction to disk so that:
- Gemini can see a compact summary of recent interactions in every response (awareness without effort)
- Gemini can retrieve full history on demand when it wants to pass prior context to a new call
- History survives MCP server restarts and Gemini `/resume` sessions

## Non-Goals

- Auto-injecting history into delegate calls (Gemini decides when context is needed)
- Cleaning up history automatically
- Sharing history across projects / working directories

## Storage

**Location:** `.mcp_history/` inside the server's working directory (`_WORKDIR`)

**Files:**
- `.mcp_history/codex.jsonl` — one JSON object per line, codex interactions
- `.mcp_history/claude.jsonl` — one JSON object per line, claude interactions

**Entry schema:**
```json
{
  "timestamp": "2026-03-30T10:00:00",
  "task": "<full task string>",
  "response": "<full response string>",
  "duration_s": 12.3
}
```

**Rules:**
- Only successful calls are saved (errors and timeouts are not persisted)
- Files are append-only; never deleted automatically
- One file per delegate, per working directory

## Footer in Delegate Responses

Every successful `delegate_to_codex` / `delegate_to_claude` response appends a footer showing the last `HISTORY_FOOTER_ENTRIES` (default: 2) previous interactions, each truncated to `HISTORY_SUMMARY_CHARS` (default: 80) characters.

If no previous interactions exist, no footer is added.

## New Tool: `get_history`

```python
get_history(delegate: str, last_n: int = 5) -> str
```

- `delegate`: `"codex"` or `"claude"`
- `last_n`: how many recent entries to return (default 5)
- Returns the last `last_n` entries formatted with full task + response + timestamp
- Gemini calls this when it wants to pass prior context into a new `prepare_task` call
