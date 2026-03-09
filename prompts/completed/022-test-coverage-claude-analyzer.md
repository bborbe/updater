---
status: completed
summary: Added tests for _get_clean_config_dir, _verify_claude_auth_impl, analyze_unreleased_for_release, and generate_changelog_from_commits, raising claude_analyzer.py coverage from 65% to 85%
container: updater-022-test-coverage-claude-analyzer
dark-factory-version: v0.30.17-dirty
created: "2026-03-09T21:19:37Z"
queued: "2026-03-09T21:19:37Z"
started: "2026-03-09T21:33:25Z"
completed: "2026-03-09T21:36:03Z"
---

<summary>
- Claude analyzer retry loops and error classification paths are tested
- Rate limit detection, timeout handling, and max retry exhaustion are covered
- The clean config directory setup and teardown logic is exercised
- All three analysis functions have tests for both success and failure paths
- Coverage target: claude_analyzer.py goes from 65% to at least 80%
</summary>

<objective>
Coverage for `claude_analyzer.py` rises from 65% to at least 80%, with retry loops, error classification, and config directory management exercised by automated tests. This ensures transient-error recovery paths are verified and regressions caught by CI.
</objective>

<context>
Read CLAUDE.md for project conventions.
Read `src/updater/claude_analyzer.py` — focus on uncovered functions: `_get_clean_config_dir()` (line 82), `_verify_claude_auth_impl()` (line 178), `analyze_unreleased_for_release()` (line 374), `generate_changelog_from_commits()` (line 541).
Read `tests/test_claude_analyzer.py` — understand existing patterns. Tests mock `_run_claude` with `AsyncMock`. Note: `analyze_unreleased_for_release` is not yet imported in the test file — add the import.

Key uncovered paths:
- `_get_clean_config_dir()`: lines 69-79, plugin directory cleanup
- `_verify_claude_auth_impl()`: retry on timeout, error classification
- `analyze_unreleased_for_release()`: lines 390-496, entire retry loop
- `generate_changelog_from_commits()`: lines 569-605, entire retry loop
</context>

<requirements>
1. Add tests for `_get_clean_config_dir()`:
   - Config dir exists with plugins → removes plugins dir
   - Config dir doesn't exist → returns None

2. Add tests for `_verify_claude_auth_impl()`:
   - Timeout error → retries, eventually fails
   - Non-retryable error → fails immediately

3. Add tests for `analyze_unreleased_for_release()`:
   - Success path → returns version bump dict
   - Rate limit error → retries with delay
   - Max retries exhausted → raises ClaudeError

4. Add tests for `generate_changelog_from_commits()`:
   - Success path → returns list of entries
   - Retry on transient error → succeeds on second attempt

5. Mock `_run_claude` with `AsyncMock`. For config dir tests, use `tmp_path` to create real directories (follow existing `test_clean_config_dir_used_if_exists` pattern) rather than mocking `Path.exists`

6. Target: raise `claude_analyzer.py` coverage from 65% to at least 80%
</requirements>

<constraints>
- Do NOT modify source code — only add/modify tests
- Do NOT commit — dark-factory handles git
- Existing tests must still pass
</constraints>

<verification>
Run `make precommit` — must pass with exit code 0.
Run `uv run --with pytest-cov pytest --cov=updater.claude_analyzer --cov-report=term-missing tests/test_claude_analyzer.py` — coverage should be >= 80%.
</verification>
