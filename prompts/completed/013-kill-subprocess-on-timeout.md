---
status: completed
summary: Added subprocess cleanup on timeout in _run_claude() with proc.kill()/proc.wait(), added test verifying kill is called, and updated CHANGELOG.md
container: updater-013-kill-subprocess-on-timeout
dark-factory-version: v0.30.17-dirty
created: "2026-03-09T20:55:36Z"
queued: "2026-03-09T20:55:36Z"
started: "2026-03-09T20:57:01Z"
completed: "2026-03-09T20:59:46Z"
---

<summary>
- Claude subprocesses no longer run indefinitely after a timeout
- Timeout failures are reported as a clear error rather than a hang
- System resource footprint is bounded even when Claude is slow to respond
- No orphaned processes left behind after timeout errors
- No change to non-timeout behavior — successful calls work identically
</summary>

<objective>
When a Claude invocation exceeds its timeout, the subprocess is left running in the background, leaking system resources. The subprocess should be terminated cleanly on timeout so long-running update jobs don't accumulate zombie processes.
</objective>

<context>
Read CLAUDE.md for project conventions.
Read `src/updater/claude_analyzer.py`, specifically the `_run_claude()` function (~line 85-131).

`ClaudeError` is imported from `src/updater/exceptions.py` (already imported at top of file).

Current code at line 126:
```python
stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
```

When `asyncio.wait_for` raises `asyncio.TimeoutError`, it cancels the coroutine but does NOT terminate the subprocess. The `claude` process keeps running in the background.
</context>

<requirements>
1. Wrap the `asyncio.wait_for` call in a try/except for `asyncio.TimeoutError`
2. In the except block: call `proc.kill()` and `await proc.wait()` to clean up
3. Re-raise as `ClaudeError(f"Claude timed out after {timeout}s")`
4. Add a test in `tests/test_claude_analyzer.py` that verifies `proc.kill()` is called on timeout (follow the pattern in existing `test_auth_times_out_after_30_seconds` which patches `asyncio.wait_for`)
</requirements>

<constraints>
- Do NOT change any other function
- Do NOT change the function signature
- Do NOT commit — dark-factory handles git
</constraints>

<verification>
Run `make precommit` — must pass with exit code 0.
</verification>
