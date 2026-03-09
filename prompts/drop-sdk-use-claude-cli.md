---
status: created
---

<summary>
- Claude integration no longer crashes on unknown backend message types (rate_limit_event)
- Claude integration no longer returns empty responses when Claude uses tools
- One fewer Python dependency to maintain and keep compatible
- All four Claude-powered features (auth check, change analysis, release analysis, changelog generation) continue to work identically
- Retry logic, metrics tracking, and error handling behavior are unchanged
- JSON response parsing (version bump, changelog, commit message) is unchanged
</summary>

<objective>
Replace the claude-code-sdk Python library with direct `claude --print -p` subprocess calls. The SDK has unresolved bugs (crashes on unknown message types like `rate_limit_event`, returns empty responses when Claude uses tools). The CLI handles all of this internally and returns the final text response to stdout — simpler and more reliable.
</objective>

<context>
Read CLAUDE.md for project conventions.

Key files:
- `src/updater/claude_analyzer.py` — all Claude integration. 4 async functions to change:
  - `verify_claude_auth()` / `_verify_claude_auth_impl()` — auth check
  - `analyze_changes_with_claude()` — main per-module analysis
  - `analyze_unreleased_for_release()` — release version bump analysis
  - `generate_changelog_from_commits()` — changelog from commits

- `tests/test_claude_analyzer.py` — tests that mock `ClaudeSDKClient`
- `pyproject.toml` — has `claude-code-sdk>=0.0.25` in dependencies

**Reference implementation:** The claude-yolo project uses `claude --print -p` for headless execution. The relevant flags for the updater (do NOT use `--dangerously-skip-permissions` — that's container-only):
```bash
claude --print -p "${PROMPT}" --model "${MODEL}" --verbose
```

**Current SDK pattern** (same in all 4 functions):
```python
async with ClaudeSDKClient(options=options) as client:
    await client.query(prompt)
    async for message in _safe_receive(client.receive_response()):
        if isinstance(message, AssistantMessage):
            for block in message.content:
                if isinstance(block, TextBlock):
                    response_text += block.text
```

**New pattern** (subprocess):
```python
cmd = ["claude", "--print", "-p", prompt, "--model", model, "--output-format", "text"]
if verbose:
    cmd.append("--verbose")
proc = await asyncio.create_subprocess_exec(
    *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    cwd=cwd, env=env
)
stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
response_text = stdout.decode()
```

**What to keep:**
- `_without_claudecode()` context manager — still needed to prevent nested Claude detection
- `_get_clean_config_dir()` — still needed, pass via `CLAUDE_CONFIG_DIR` in env
- `_run_git_command()` — used elsewhere
- JSON extraction logic (code block parsing) — Claude CLI may still wrap JSON in markdown
- Retry logic with rate limit detection — check stderr/exit code for retryable errors
- Metrics recording via `metrics.record_call()` and `metrics.record_rate_limit_wait()`
- `config.MODEL`, `config.VERBOSE_MODE`, `config.CLAUDE_SESSION_DELAY`

**What to remove:**
- All `claude_code_sdk` imports (`AssistantMessage`, `ClaudeCodeOptions`, `ClaudeSDKClient`, `TextBlock`, `MessageParseError`)
- `_safe_receive()` async generator wrapper
- `suppress_sdk_cleanup_errors` exception handler in `verify_claude_auth()`
- `claude-code-sdk` from `pyproject.toml` dependencies
- `AsyncIterator` import (only used by `_safe_receive`)

**Callers** (all use `await`, keep functions async):
- `cli.py`: `await verify_claude_auth()`
- `pipeline.py`: `await analyze_changes_with_claude(...)`, `await analyze_unreleased_for_release(...)`, `await generate_changelog_from_commits(...)`
</context>

<requirements>
1. Create a helper function `_run_claude()` in `claude_analyzer.py` that wraps the subprocess call:
   ```python
   async def _run_claude(prompt: str, model: str | None = None, cwd: Path | None = None,
                          timeout: int = 120) -> str:
       """Run claude --print -p and return stdout text.

       Args:
           prompt: The prompt to send
           model: Model name (sonnet, haiku, opus). Uses config.MODEL if None.
           cwd: Working directory for Claude. None = current directory.
           timeout: Timeout in seconds.

       Returns:
           Claude's text response (stdout).

       Raises:
           ClaudeError: If Claude exits non-zero or times out.
       """
   ```
   Implementation:
   - Build command: `["claude", "--print", "-p", prompt, "--model", model or config.MODEL, "--output-format", "text"]`
   - Add `"--verbose"` if `config.VERBOSE_MODE`
   - Use `_without_claudecode()` context manager
   - Set `CLAUDE_CONFIG_DIR` from `_get_clean_config_dir()` in env
   - Use `asyncio.create_subprocess_exec` with `stdout=PIPE, stderr=PIPE`
   - `await asyncio.wait_for(proc.communicate(), timeout=timeout)`
   - If non-zero exit code, raise `ClaudeError` with stderr content
   - Return `stdout.decode().strip()`

2. Rewrite `_verify_claude_auth_impl()`:
   - Call `_run_claude("Reply with exactly: ok", timeout=30)`
   - If it returns without error, auth is good
   - Remove the `suppress_sdk_cleanup_errors` wrapper in `verify_claude_auth()` — no longer needed since there's no SDK subprocess to clean up. Simplify `verify_claude_auth()` to directly call the retry logic without the exception handler wrapping.

3. Rewrite `analyze_changes_with_claude()`:
   - Keep the same prompt text (tool-based analysis with `cwd=module_path`)
   - Call `_run_claude(prompt, cwd=module_path, timeout=120)`
   - Keep the JSON extraction logic (code block parsing) unchanged
   - Keep the retry loop with rate limit detection — detect retryable errors from stderr content or `ClaudeError` message

4. Rewrite `analyze_unreleased_for_release()`:
   - Keep the same prompt text
   - Call `_run_claude(prompt, timeout=60)`
   - Keep JSON extraction and retry logic

5. Rewrite `generate_changelog_from_commits()`:
   - Keep the same prompt text
   - Call `_run_claude(prompt, timeout=60)`
   - Keep JSON extraction and retry logic

6. Remove SDK imports and artifacts:
   - Remove `from claude_code_sdk import ...` block
   - Remove `from claude_code_sdk._errors import MessageParseError`
   - Remove `_safe_receive()` function
   - Remove `AsyncIterator` from imports (check it's not used elsewhere)
   - Keep `asyncio`, `json`, `os`, `shutil`, `subprocess`, `time` imports
   - Add `import asyncio.subprocess` if needed (or use `asyncio.create_subprocess_exec` directly)

7. Remove `claude-code-sdk` from `pyproject.toml` dependencies list.

8. Update `tests/test_claude_analyzer.py`:
   - Remove `from claude_code_sdk` imports
   - Remove `create_mock_client()` helper
   - Remove `TestSafeReceive` class entirely
   - Replace all `patch("updater.claude_analyzer.ClaudeSDKClient", ...)` with `patch("updater.claude_analyzer._run_claude", new_callable=AsyncMock)` that returns the expected response text
   - Update `test_uses_configured_model` and `test_strict_mcp_config_flag` — these tested SDK options. Replace with tests that verify `_run_claude` is called with correct arguments (model, cwd)
   - `test_multiple_text_blocks` — no longer relevant (CLI returns one text), remove it
   - Keep all JSON parsing tests (code block, surrounding text, invalid JSON, missing fields, defaults)

9. Update `CHANGELOG.md` under `## Unreleased`:
   ```
   - Replace claude-code-sdk with direct CLI subprocess calls (fixes rate_limit_event crashes)
   ```
</requirements>

<constraints>
- Do NOT commit — dark-factory handles git
- Do NOT change the prompt text content sent to Claude in any function
- Do NOT change the JSON response format or parsing logic
- Do NOT change the retry delays or retry count
- Do NOT remove `_without_claudecode()` or `_get_clean_config_dir()`
- Do NOT change `_run_git_command()`
- Do NOT remove metrics recording — keep all `metrics.record_call()` and `metrics.record_rate_limit_wait()` calls
- Functions must remain async (callers use `await`)
- Existing tests that are NOT SDK-specific must still pass
- Do NOT use `--dangerously-skip-permissions` — the updater runs on the user's machine, not in a container
</constraints>

<verification>
Run `make precommit` — must pass with exit code 0.
Run `uv run pytest` — all tests must pass.
Verify `claude_code_sdk` does not appear anywhere in `src/` or `tests/`.
Verify `claude-code-sdk` is not in `pyproject.toml` dependencies.
</verification>
