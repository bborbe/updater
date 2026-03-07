---
status: completed
summary: Added 30-second asyncio.wait_for timeout to Claude auth verification and moved setup_module_logging before auth in main_async, with two new tests covering timeout handling and logging order
container: updater-004-fix-auth-timeout-and-early-logging
dark-factory-version: v0.20.6
created: "2026-03-07T10:45:00Z"
queued: "2026-03-07T10:31:28Z"
started: "2026-03-07T10:31:41Z"
completed: "2026-03-07T10:41:21Z"
---
<summary>
- Adds a 30-second hard timeout to the Claude auth verification call so it can never hang indefinitely
- `asyncio.wait_for(..., timeout=30)` wraps the SDK call — TimeoutError is caught by existing retry logic
- Moves `setup_logging` to before `verify_claude_auth` so a log file always exists, even if auth hangs or fails
- Total worst-case auth time becomes bounded: 3 retries × 30s + backoff = ~107s instead of forever
- Two tests: auth times out after 30s, log file exists before auth runs
</summary>

<objective>
Prevent `update-all` from hanging indefinitely during Claude auth verification, and ensure a log file always exists so failures are diagnosable. Both fixes are in `src/updater/claude_analyzer.py` and `src/updater/cli.py`.
</objective>

<context>
Read CLAUDE.md for project conventions.
Read `src/updater/claude_analyzer.py` — `verify_claude_auth()` and `_verify_claude_auth_impl()` are the functions to change. The retry loop is at line ~195. The SDK call is `await client.query("Reply with exactly: ok")` with no timeout.
Read `src/updater/cli.py` — `verify_claude_auth()` is called at line ~359 (Step 0), after `config.RUN_TIMESTAMP` is set but before `setup_logging`. Find where `setup_logging` is first called and move it above the auth check.
Read `src/updater/log_manager.py` — `setup_logging(module_path)` opens the log file and writes the header.
</context>

<requirements>
1. In `src/updater/claude_analyzer.py`, wrap the auth attempt with `asyncio.wait_for`:

   Replace:
   ```python
   async with ClaudeSDKClient(options=options) as client:
       await client.query("Reply with exactly: ok")

       async for message in client.receive_response():
           if isinstance(message, AssistantMessage):
               for block in message.content:
                   if isinstance(block, TextBlock):
                       return True, ""
   ```

   With:
   ```python
   async def _do_auth_check() -> bool:
       async with ClaudeSDKClient(options=options) as client:
           await client.query("Reply with exactly: ok")
           async for message in client.receive_response():
               if isinstance(message, AssistantMessage):
                   for block in message.content:
                       if isinstance(block, TextBlock):
                           return True
       return True

   await asyncio.wait_for(_do_auth_check(), timeout=30)
   ```

   `asyncio.TimeoutError` is a subclass of `Exception` so it will be caught by the existing `except Exception as e` block. Add `"timeout"` is already in the retryable keywords list — so it will retry automatically.

2. In `src/updater/cli.py`, move `setup_logging` to run before `verify_claude_auth`.

   Find the first module path that setup_logging would use. If no modules are provided yet at that point, use the current working directory as a fallback log location (`Path.cwd()`). Check how `setup_logging` is currently called to understand its signature.

   The goal: a log file exists on disk before the auth check runs, so if auth hangs or fails, the log captures it.

3. Add or extend tests in `tests/` to cover:
   - Auth check times out after 30 seconds (`asyncio.TimeoutError` is raised and treated as retryable)
   - Log file is created before `verify_claude_auth` is called (mock auth to verify ordering)

<constraints>
- Do NOT change the retry count (3) or backoff delays (2, 5, 10s)
- Do NOT change the auth error messages
- Timeout value 30 seconds — do not make it configurable (keep it simple)
- Do NOT commit — dark-factory handles git
- `make precommit` must pass
- Existing tests must still pass
</constraints>

<verification>
Run `make precommit` — must pass.
Run `python -m pytest tests/ -v` — all tests pass.
</verification>
