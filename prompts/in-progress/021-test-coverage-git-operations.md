---
status: approved
created: "2026-03-09T21:19:37Z"
queued: "2026-03-09T21:19:37Z"
---

<summary>
- Git branch update with fetch, pull, and merge operations is tested with mocked subprocess
- Failure paths for each git command (fetch, pull, merge, commit, push) are covered
- The tracking branch detection logic is exercised for both tracked and untracked branches
- Tag creation from CHANGELOG version is tested including skip conditions
- Coverage target: git_operations.py goes from 61% to at least 80%
</summary>

<objective>
Coverage for `git_operations.py` rises from 61% to at least 80%, with all git mutation functions exercised by automated tests. This ensures incorrect commits, tags, or push failures are caught by CI.
</objective>

<context>
Read CLAUDE.md for project conventions.
Read `src/updater/git_operations.py` — focus on uncovered functions: `update_git_branch()` (line 147), `git_commit()` (line 235), `git_tag_from_changelog()` (line 321).
Read `tests/test_git_operations.py` — understand existing patterns.

Important: `git_commit()` and `git_tag_from_changelog()` use `run_command()` from `log_manager` (not `subprocess.run` directly). Mock `updater.log_manager.run_command` for these. `update_git_branch()` uses `subprocess.run` directly — mock `subprocess.run` for that function.
</context>

<requirements>
1. Add tests for `update_git_branch()`:
   - Success path: fetch, pull, merge all succeed
   - Fetch failure → returns False
   - No tracking branch → skips pull, still merges
   - Merge failure → returns False
   - With and without log_func parameter

2. Add tests for `git_commit()`:
   - Success path: git add + git commit succeed
   - Commit failure → raises RuntimeError

3. Add tests for `git_tag_from_changelog()`:
   - Success path: no uncommitted changes, HEAD not tagged, CHANGELOG has version → creates tag
   - Uncommitted changes → skips tag
   - HEAD already tagged → skips tag
   - No CHANGELOG.md → skips tag

4. Mock `subprocess.run` for `update_git_branch` tests. Mock `updater.log_manager.run_command` for `git_commit` and `git_tag_from_changelog` tests.

5. Target: raise `git_operations.py` coverage from 61% to at least 80%
</requirements>

<constraints>
- Do NOT modify source code — only add/modify tests
- Do NOT commit — dark-factory handles git
- Existing tests must still pass
</constraints>

<verification>
Run `make precommit` — must pass with exit code 0.
Run `uv run --with pytest-cov pytest --cov=updater.git_operations --cov-report=term-missing tests/test_git_operations.py` — coverage should be >= 80%.
</verification>
