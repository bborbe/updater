---
status: completed
summary: 'Added extra_args={"strict-mcp-config": None} to all 4 ClaudeCodeOptions calls in claude_analyzer.py, added a test verifying the flag is set, and added an Unreleased CHANGELOG entry.'
container: updater-002-disable-mcp-in-claude-sdk-calls
dark-factory-version: v0.17.12
created: "2026-03-06T09:00:00Z"
queued: "2026-03-06T08:03:46Z"
started: "2026-03-06T08:03:46Z"
completed: "2026-03-06T08:06:13Z"
---

<objective>
Prevent Claude SDK calls from loading project-level MCP servers by adding `--strict-mcp-config` to all `ClaudeCodeOptions` instances.
</objective>

<context>
Read src/updater/claude_analyzer.py for all ClaudeCodeOptions usages.

Bug: When the updater runs Claude via the SDK, the subprocess inherits the parent process's cwd. If that directory contains a `.mcp.json` file, Claude Code loads those MCP servers and triggers auth prompts — breaking non-interactive execution.

The updater already sets `CLAUDE_CONFIG_DIR=~/.claude-clean` (which has no MCP configs), but Claude Code also loads MCP from project-level `.mcp.json` in the working directory.

The `--strict-mcp-config` CLI flag tells Claude to only use MCP servers from `--mcp-config`, ignoring all other MCP configurations (including project `.mcp.json`). When used without `--mcp-config`, it means zero MCP servers.

In the Python SDK, CLI flags are passed via `extra_args` on `ClaudeCodeOptions`. A key with `None` value becomes a boolean flag:
```python
ClaudeCodeOptions(
    extra_args={"strict-mcp-config": None}  # adds --strict-mcp-config
)
```
</context>

<requirements>
1. Add `extra_args={"strict-mcp-config": None}` to ALL `ClaudeCodeOptions(...)` calls in `src/updater/claude_analyzer.py`:
   - `verify_claude_auth` / `_verify_claude_auth_impl` (~line 184)
   - `analyze_changes_with_claude` (~line 315)
   - `analyze_changelog_bump` (~line 461)
   - `generate_changelog_entries` (~line 589)
2. Add a test that verifies `--strict-mcp-config` is present in the constructed CLI command for at least one of the functions.
3. Update CHANGELOG.md: add entry under `## Unreleased` section (create if missing):
   ```
   - Disable project-level MCP server loading in Claude SDK calls
   ```
</requirements>

<constraints>
- Do NOT change the `cwd` behavior — Claude needs access to project files
- Do NOT remove the existing `CLAUDE_CONFIG_DIR` / `_get_clean_config_dir()` logic
- Do NOT add any new dependencies
- Keep the fix minimal — only add `extra_args` to existing `ClaudeCodeOptions` calls
</constraints>

<verification>
Run `make precommit` — must pass with exit code 0.
Run `uv run pytest` — all tests must pass.
</verification>
