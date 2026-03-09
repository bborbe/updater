---
status: approved
created: "2026-03-09T21:19:38Z"
queued: "2026-03-09T21:19:38Z"
---

<summary>
- The CLI module has test coverage for its main processing paths and error handlers
- Module processing with retries, verbose mode, and model selection are tested
- Git update failures and uncommitted change handling are covered
- Multi-module processing and auth failure paths are exercised
- Coverage target: cli.py goes from 39% to at least 70%
</summary>

<objective>
Coverage for `cli.py` rises from 39% to at least 70%, with the main async entry points and module processing functions exercised by automated tests. This ensures the primary orchestration paths are verified and regressions caught by CI.
</objective>

<context>
Read CLAUDE.md for project conventions.
Read `src/updater/cli.py` — focus on uncovered lines: 168-230, 258-274, 381-383, 410-455, 474-475, 506-508, 539-542, 570-611, 629-1142, 1155-1324.
Read `tests/test_cli.py` — understand existing test patterns, mocking style, and fixtures.

The test file uses `pytest` with `unittest.mock` (`from unittest.mock import AsyncMock, patch`). Functions are async — use `pytest.mark.asyncio` and `AsyncMock`. Mock `subprocess.run` for git commands, mock pipeline steps, mock `verify_claude_auth`.
</context>

<requirements>
1. Add tests to `tests/test_cli.py` for the uncovered paths:
   - `process_single_go_module()` and `process_single_python_module()`: success path, failure with retry, up-to-date result
   - `process_release_module()`: success path, failure path
   - Auth failure handling (Claude auth fails at startup)
   - `--yes` mode auto-skip after max retries
   - Multi-module summary output
   - Recursive directory discovery path

2. Mock external dependencies (subprocess, pipeline steps, claude_analyzer) — never make real subprocess or network calls

3. Each test should be focused: one behavior per test, descriptive name

4. Target: raise `cli.py` coverage from 39% to at least 70%
</requirements>

<constraints>
- Do NOT modify source code — only add/modify tests
- Do NOT commit — dark-factory handles git
- Existing tests must still pass
</constraints>

<verification>
Run `make precommit` — must pass with exit code 0.
Run `uv run --with pytest-cov pytest --cov=updater.cli --cov-report=term-missing tests/test_cli.py` — coverage should be >= 70%.
</verification>
