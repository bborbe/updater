---
status: created
---

<summary>
- The run_command function is tested for success, failure, and output logging
- Log file setup, writing, and cleanup are covered
- Command output is verified to be logged correctly in both quiet and verbose modes
- Failed commands raise RuntimeError with the expected message
- Coverage target: log_manager.py goes from 68% to at least 85%
</summary>

<objective>
Coverage for `log_manager.py` rises from 68% to at least 85%, with `run_command()` and `cleanup_old_logs()` exercised by automated tests. This ensures the central command execution and log rotation work correctly and regressions are caught by CI.
</objective>

<context>
Read CLAUDE.md for project conventions.
Read `src/updater/log_manager.py` — focus on uncovered lines: 59, 66, 106-130 (`run_command`).
Read `tests/` for existing test patterns.

`run_command()` uses `subprocess.run(cmd, shell=True, ...)` and raises `RuntimeError` on non-zero exit codes.
</context>

<requirements>
1. Add tests for `run_command()`:
   - Success: command succeeds, returns CompletedProcess, logs output
   - Failure: command fails, raises RuntimeError with exit code in message
   - Quiet mode: command output only goes to log file, not console
   - Verbose mode: stdout/stderr logged to console
   - Stderr output on failure is logged

2. Add tests for `cleanup_old_logs()`:
   - More logs than keep_count → old ones deleted
   - Fewer logs than keep_count → nothing deleted
   - Log directory doesn't exist → returns without error

3. Mock `subprocess.run` — never execute real commands

4. Target: raise `log_manager.py` coverage from 68% to at least 85%
</requirements>

<constraints>
- Do NOT modify source code — only add/modify tests
- Do NOT commit — dark-factory handles git
- Existing tests must still pass
</constraints>

<verification>
Run `make precommit` — must pass with exit code 0.
Run `uv run --with pytest-cov pytest --cov=updater.log_manager --cov-report=term-missing` — coverage should be >= 85%.
</verification>
