---
status: created
---

<summary>
- Refactor `analyze_changes_with_claude()` to let Claude use built-in tools (Read, Bash, Grep) instead of stuffing diffs into the prompt
- Remove `_collect_diffs()`, `_truncate_diff()`, `_get_diff_base()` — no longer needed
- Remove `MAX_DIFF_PER_FILE` and `MAX_TOTAL_DIFF` constants — no longer needed
- Prompt becomes a task description: "you are in {path}, analyze git changes, return JSON"
- Claude runs `git diff`, reads files as needed — smarter analysis with full context
- Dramatically reduces prompt size — fixes rate_limit_event issues on large modules
- `analyze_unreleased_for_release()` and `generate_changelog_from_commits()` unchanged — they pass small data inline (changelog bullets, commit messages)
</summary>

<objective>
Replace the prompt-stuffed-with-diffs approach in `analyze_changes_with_claude()` with a task-based prompt that lets Claude use its built-in filesystem and shell tools to analyze changes. This eliminates prompt bloat (up to 200KB of diffs), removes the need for diff collection/truncation code, and gives Claude full context to make better decisions.
</objective>

<context>
Read CLAUDE.md for project conventions.

Key file: `src/updater/claude_analyzer.py`

**Current approach** (`analyze_changes_with_claude()` starting at line 313):
1. `_collect_diffs(module_path)` (line 103) runs `git diff` for each file type, truncates to 50KB/file and 200KB total
2. Embeds all diffs into a single prompt string (can be 200KB+)
3. Sends prompt via `ClaudeSDKClient` with `extra_args={"strict-mcp-config": None}`
4. Collects response text, parses JSON

`strict-mcp-config` only disables MCP servers. Built-in Claude Code tools (Read, Bash, Grep, Glob, Edit, Write) remain available. Claude can already use them — the updater just never asks it to.

**Functions to remove** (only used by `analyze_changes_with_claude`):
- `_truncate_diff()` (line 84) — truncates diff strings
- `_get_diff_base()` (line 97) — gets latest tag for diff base
- `_collect_diffs()` (line 103) — collects and truncates all diffs
- Constants `MAX_DIFF_PER_FILE` (line 25) and `MAX_TOTAL_DIFF` (line 26)

Verify these are not used elsewhere before removing. `_get_diff_base` is called from `_collect_diffs` only. `_truncate_diff` is called from `_collect_diffs` only. `_collect_diffs` is called from `analyze_changes_with_claude` only.

**Functions to NOT change:**
- `analyze_unreleased_for_release()` (line 493) — takes a small list of changelog bullet strings, prompt is tiny
- `generate_changelog_from_commits()` (line 657) — takes a small list of commit messages, prompt is tiny
- `_verify_claude_auth_impl()` — auth check, unrelated

**The `ClaudeCodeOptions` setup** (line 395-398):
```python
options = ClaudeCodeOptions(
    model=config.MODEL,
    env=env,
    extra_args={"strict-mcp-config": None},
)
```
Keep `strict-mcp-config` — it only disables MCP, built-in tools still work.

**Current JSON output format** (line 373-378) — keep this exact format:
```json
{
  "version_bump": "patch|minor|major|none",
  "changelog": ["bullet 1", "bullet 2"],
  "commit_message": "short message"
}
```
</context>

<requirements>
1. Replace the prompt in `analyze_changes_with_claude()` with a task-based prompt. The new prompt should:
   - Tell Claude its working directory is `{module_path}`
   - Set `cwd` on `ClaudeCodeOptions` to `str(module_path)` so Claude starts in the right directory
   - Instruct Claude to run `git diff` itself to understand changes (it can choose what to diff)
   - Include the same version bump decision rules
   - Request the same JSON output format
   - Explicitly tell Claude to exclude `go.sum`, `vendor/`, `node_modules/`, generated files from analysis
   - Tell Claude to use `git describe --tags --abbrev=0` to find the comparison base tag

   Example prompt (adapt as needed):
   ```
   You are in {module_path}. Analyze the git changes in this module and determine the appropriate version bump.

   Steps:
   1. Find the latest git tag: git describe --tags --abbrev=0
   2. Run git diff against that tag to see what changed (exclude go.sum, vendor/, node_modules/, mocks/, *_mock.go, *.gen.go)
   3. Focus on go.mod for dependency changes and source code for logic changes
   4. Determine version bump and generate changelog

   Version Bump Decision Rules:
   [same rules as current prompt]

   Return ONLY this JSON format (no markdown, no code blocks):
   {{"version_bump": "patch|minor|major|none", "changelog": ["bullet 1", "bullet 2"], "commit_message": "short message"}}
   ```

2. Remove the diff collection code that is no longer needed:
   - Remove `_collect_diffs()` function
   - Remove `_truncate_diff()` function
   - Remove `_get_diff_base()` function
   - Remove `MAX_DIFF_PER_FILE` and `MAX_TOTAL_DIFF` constants
   - Remove the "Collecting diffs..." log line
   - Remove the diff assembly code (lines 335-343)

   Before removing, verify with grep that these are not used elsewhere.

3. Set `cwd` on `ClaudeCodeOptions`:
   ```python
   options = ClaudeCodeOptions(
       model=config.MODEL,
       env=env,
       cwd=str(module_path),
       extra_args={"strict-mcp-config": None},
   )
   ```
   Check that `ClaudeCodeOptions` accepts a `cwd` parameter — read the SDK types at `claude_code_sdk/types.py`.

4. Update existing tests that mock `_collect_diffs` or test diff collection — they should be removed or updated to match the new approach.

5. Update `CHANGELOG.md` under `## Unreleased`:
   ```
   - Refactor Claude analysis to use built-in tools instead of embedding diffs in prompt
   ```
</requirements>

<constraints>
- Do NOT commit — dark-factory handles git
- Do NOT change `analyze_unreleased_for_release()` or `generate_changelog_from_commits()`
- Do NOT change `_verify_claude_auth_impl()`
- Do NOT remove `strict-mcp-config` — it correctly disables MCP while keeping built-in tools
- Do NOT change the JSON output format — downstream code depends on it
- Do NOT change retry logic or error handling
- Keep the `_without_claudecode()` context manager — it prevents nested Claude detection
- Existing tests must still pass (update/remove tests for removed functions)
</constraints>

<verification>
Run `make precommit` — must pass with exit code 0.
Run `uv run pytest` — all tests must pass.
Verify `_collect_diffs`, `_truncate_diff`, `_get_diff_base`, `MAX_DIFF_PER_FILE`, `MAX_TOTAL_DIFF` are no longer in the codebase.
</verification>
