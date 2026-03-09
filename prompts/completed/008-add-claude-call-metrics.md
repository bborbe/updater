---
status: completed
summary: Added Claude API call metrics tracking with instrumentation in all 4 SDK functions, metrics summary printed in cli.py, tests, and CHANGELOG updated
container: updater-008-add-claude-call-metrics
dark-factory-version: dev
created: "2026-03-09T18:08:39Z"
queued: "2026-03-09T18:08:39Z"
started: "2026-03-09T18:10:15Z"
completed: "2026-03-09T18:13:45Z"
---

<summary>
- New `claude_metrics.py` module tracks every Claude SDK call automatically
- Each call records success, rate limit, or failure with duration
- Rate limit wait time (30/60/90s sleeps) is tracked separately
- End-of-run summary shows call count, rate limit hits, total wait time, avg call duration
- No output when no Claude calls were made (e.g. all modules up-to-date)
- Existing retry logic and error handling unchanged — metrics are observability only
</summary>

<objective>
Add Claude API call metrics so operators can diagnose rate limit saturation when processing large module sets (20+ modules). The metrics summary prints at end of run showing how many calls were made, how many hit rate limits, and how much time was lost to rate limit backoff.
</objective>

<context>
Read CLAUDE.md for project conventions.

Key files:
- `src/updater/claude_analyzer.py` — all Claude calls go through here. 4 async functions call the SDK:
  - `_verify_claude_auth_impl()` (line 195) — auth check
  - `analyze_changes_with_claude()` (line 277) — main analysis per module
  - `analyze_unreleased_for_release()` (line 445) — release analysis
  - `generate_changelog_from_commits()` (line 594) — changelog from commits

  Each has a retry loop with `rate_limit_delays = [30, 60, 90]` and catches rate limit errors.

- `src/updater/config.py` — global state module for CLI settings (single-threaded, module-level vars). Follow this same singleton pattern for metrics.
- `src/updater/cli.py` — `main_async()` function:
  - Multi-module SUMMARY block: after the `if failed:` print block, before the closing `print("\n" + "=" * 70)`
  - Single-module path: before `return 0 if success else 1`
- `CHANGELOG.md` — no `## Unreleased` section exists; versions start at `## v0.17.2`. Add `## Unreleased` above it.

All 4 Claude functions follow the same pattern:
```python
for attempt in range(max_retries):
    try:
        # ... make SDK call ...
        return result
    except Exception as e:
        is_rate_limit = "rate_limit" in str(e).lower()
        if is_retryable and attempt < max_retries - 1:
            delay = rate_limit_delays[attempt] if is_rate_limit else retry_delays[attempt]
            await asyncio.sleep(delay)
            continue
        else:
            raise ClaudeError(...)
```
</context>

<requirements>
1. Create `src/updater/claude_metrics.py` with a simple module-level metrics tracker:
   ```python
   import time
   from dataclasses import dataclass, field

   @dataclass
   class CallRecord:
       function: str
       timestamp: float
       duration_s: float
       success: bool
       rate_limited: bool

   @dataclass
   class ClaudeMetrics:
       calls: list[CallRecord] = field(default_factory=list)
       rate_limit_wait_s: float = 0.0

       def record_call(self, function: str, duration_s: float, success: bool, rate_limited: bool) -> None:
           self.calls.append(CallRecord(
               function=function,
               timestamp=time.time(),
               duration_s=duration_s,
               success=success,
               rate_limited=rate_limited,
           ))

       def record_rate_limit_wait(self, seconds: float) -> None:
           self.rate_limit_wait_s += seconds

       @property
       def total_calls(self) -> int:
           return len(self.calls)

       @property
       def successful_calls(self) -> int:
           return sum(1 for c in self.calls if c.success)

       @property
       def rate_limited_calls(self) -> int:
           return sum(1 for c in self.calls if c.rate_limited)

       @property
       def failed_calls(self) -> int:
           return sum(1 for c in self.calls if not c.success and not c.rate_limited)

       @property
       def total_duration_s(self) -> float:
           return sum(c.duration_s for c in self.calls)

       def format_summary(self) -> str:
           if not self.calls:
               return ""
           lines = ["Claude API Metrics:"]
           lines.append(f"  Calls: {self.total_calls} ({self.successful_calls} ok, {self.rate_limited_calls} rate-limited, {self.failed_calls} failed)")
           lines.append(f"  Call time: {self.total_duration_s:.1f}s (avg {self.total_duration_s / self.total_calls:.1f}s)")
           if self.rate_limit_wait_s > 0:
               lines.append(f"  Rate limit wait: {self.rate_limit_wait_s:.0f}s")
           return "\n".join(lines)

       def reset(self) -> None:
           self.calls.clear()
           self.rate_limit_wait_s = 0.0

   # Module-level singleton (same pattern as config.py)
   metrics = ClaudeMetrics()
   ```

2. Instrument all 4 Claude functions in `claude_analyzer.py`:
   - Import: `from .claude_metrics import metrics`
   - Wrap each SDK call attempt with timing. Record on success and on rate limit.
   - On rate limit sleep, also call `metrics.record_rate_limit_wait(delay)`.

   Example for `analyze_changes_with_claude()` (apply same pattern to all 4):
   ```python
   for attempt in range(max_retries):
       call_start = time.monotonic()
       try:
           # ... existing SDK call ...
           duration = time.monotonic() - call_start
           metrics.record_call("analyze_changes", duration, success=True, rate_limited=False)
           return result
       except Exception as e:
           duration = time.monotonic() - call_start
           is_rate_limit = "rate_limit" in str(e).lower()
           metrics.record_call("analyze_changes", duration, success=False, rate_limited=is_rate_limit)
           if is_retryable and attempt < max_retries - 1:
               delay = ...
               metrics.record_rate_limit_wait(delay) if is_rate_limit else None
               await asyncio.sleep(delay)
               continue
           else:
               raise ...
   ```

   Function name labels:
   - `_verify_claude_auth_impl` → `"auth_check"`
   - `analyze_changes_with_claude` → `"analyze_changes"`
   - `analyze_unreleased_for_release` → `"analyze_unreleased"`
   - `generate_changelog_from_commits` → `"generate_changelog"`

3. Print metrics in `cli.py` `main_async()`:
   - Import: `from .claude_metrics import metrics`
   - Multi-module path: after the `if failed:` print block, before the closing separator `print("\n" + "=" * 70)`, add:
     ```python
     summary = metrics.format_summary()
     if summary:
         print(f"\n{summary}")
     ```
   - Single-module path: before `return 0 if success else 1`, add:
     ```python
     summary = metrics.format_summary()
     if summary:
         print(f"\n{summary}")
     ```

4. Add `import time` to `claude_analyzer.py` if not already present.

5. Add tests in `tests/test_claude_metrics.py`:
   - `test_record_call` — record a call, check total_calls == 1
   - `test_rate_limit_tracking` — record rate-limited call + wait, check rate_limited_calls and rate_limit_wait_s
   - `test_format_summary_empty` — no calls returns empty string
   - `test_format_summary` — record mix of calls, verify format_summary output contains expected strings
   - `test_reset` — record calls, reset, check total_calls == 0

6. Update `CHANGELOG.md` — read the file first, then add a new `## Unreleased` section above the first existing version (`## v0.17.2`):
   ```
   ## Unreleased

   - Add Claude API call metrics (call count, rate limits, durations) printed in run summary
   ```
</requirements>

<constraints>
- Do NOT commit — dark-factory handles git
- Do NOT change retry logic, delays, or error handling behavior
- Do NOT add any external dependencies
- Module-level singleton pattern (same as `config.py`) — no DI needed
- `time.monotonic()` for durations, `time.time()` for timestamps
- Existing tests must still pass
</constraints>

<verification>
Run `make precommit` — must pass with exit code 0.
Run `uv run pytest` — all tests must pass.
</verification>
