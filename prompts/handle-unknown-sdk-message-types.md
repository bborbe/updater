---
status: created
---

<summary>
- The `claude-code-sdk v0.0.25` raises `MessageParseError` for unknown message types like `rate_limit_event`
- The error propagates through all 4 Claude functions, causing every module to fail
- Fix: wrap the `async for message` loops to catch and skip `MessageParseError`
- This is a workaround until the SDK adds native `rate_limit_event` support
- No behavior change for recognized message types — only unknown types are silently skipped
- Existing retry logic unchanged — only the crash-on-unknown-type is fixed
</summary>

<objective>
Prevent `claude-code-sdk` `MessageParseError("Unknown message type: rate_limit_event")` from crashing the updater. The SDK doesn't handle `rate_limit_event` messages yet, so the updater must catch and skip them instead of treating them as fatal errors.
</objective>

<context>
Read CLAUDE.md for project conventions.

Key files:
- `src/updater/claude_analyzer.py` — all 4 Claude functions iterate over SDK messages with the same pattern:
  ```python
  async for message in client.receive_response():
      if isinstance(message, AssistantMessage):
          for block in message.content:
              if isinstance(block, TextBlock):
                  response_text += block.text
  ```
  The `client.receive_response()` internally calls `parse_message()` which raises `MessageParseError` for unknown types. This exception propagates out of the `async for` loop and into the retry `except Exception` handler, which treats it as a rate limit error (because "rate_limit" appears in the string "Unknown message type: rate_limit_event").

- The SDK source at `claude_code_sdk/_internal/message_parser.py` line 172:
  ```python
  case _:
      raise MessageParseError(f"Unknown message type: {message_type}", data)
  ```

- The SDK source at `claude_code_sdk/_internal/client.py` line 118:
  ```python
  async for data in query.receive_messages():
      yield parse_message(data)  # MessageParseError propagates here
  ```

The 4 functions to fix (all in `claude_analyzer.py`):
- `_verify_claude_auth_impl()` — `async for message in client.receive_response():` loop
- `analyze_changes_with_claude()` — same pattern
- `analyze_unreleased_for_release()` — same pattern
- `generate_changelog_from_commits()` — same pattern

The `client.receive_response()` is `ClaudeSDKClient.receive_response()` which yields from the internal client's `process_query()`.
</context>

<requirements>
1. Import `MessageParseError` at the top of `claude_analyzer.py`:
   ```python
   from claude_code_sdk._errors import MessageParseError
   ```
   Verify this import path exists — check `claude_code_sdk/_errors.py` exports `MessageParseError`.

2. Create a wrapper generator function in `claude_analyzer.py` that filters out unknown message types:
   ```python
   async def _safe_receive(response):
       """Yield messages from SDK response, skipping unknown message types."""
       try:
           async for message in response:
               yield message
       except MessageParseError:
           # SDK doesn't handle all message types (e.g. rate_limit_event)
           # Skip unknown types and continue
           pass
   ```
   Note: since `MessageParseError` breaks the async generator iteration, we need a different approach. The error comes from the generator itself, so we need to handle it by wrapping each iteration step. Use this pattern instead:
   ```python
   async def _safe_receive(response):
       """Yield messages from SDK response, skipping unknown message types.

       The claude-code-sdk raises MessageParseError for unrecognized message
       types (e.g. rate_limit_event). This wrapper catches those errors so
       the caller can process all recognized messages without crashing.
       """
       it = response.__aiter__()
       while True:
           try:
               message = await it.__anext__()
               yield message
           except StopAsyncIteration:
               break
           except MessageParseError:
               continue
   ```

3. Replace all 4 `async for message in client.receive_response():` with `async for message in _safe_receive(client.receive_response()):` in:
   - `_verify_claude_auth_impl()`
   - `analyze_changes_with_claude()`
   - `analyze_unreleased_for_release()`
   - `generate_changelog_from_commits()`

4. Add test in `tests/test_claude_analyzer.py` (or new `tests/test_safe_receive.py`):
   - `test_safe_receive_skips_parse_errors` — create an async generator that yields a value then raises `MessageParseError` then yields another value. Verify `_safe_receive` yields both values and skips the error.
   - `test_safe_receive_normal` — async generator with no errors yields all values.

5. Update `CHANGELOG.md` under `## Unreleased`:
   ```
   - Handle unknown SDK message types (e.g. rate_limit_event) without crashing
   ```
</requirements>

<constraints>
- Do NOT commit — dark-factory handles git
- Do NOT modify the SDK source — only change updater code
- Do NOT change retry logic, delays, or error handling
- Do NOT suppress errors other than `MessageParseError` in `_safe_receive`
- Existing tests must still pass
</constraints>

<verification>
Run `make precommit` — must pass with exit code 0.
Run `uv run pytest` — all tests must pass.
</verification>
