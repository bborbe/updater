---
status: completed
summary: Added 17 new tests for GoDepSkipStep, PythonVersionUpdateStep, PythonDepUpdateStep, DockerUpdateStep, GitPushStep, and GitCommitStep (tag_only) to raise pipeline.py coverage from 78% to 85%
container: updater-019-test-coverage-pipeline
dark-factory-version: v0.30.17-dirty
created: "2026-03-09T21:19:37Z"
queued: "2026-03-09T21:19:37Z"
started: "2026-03-09T21:25:53Z"
completed: "2026-03-09T21:29:03Z"
---

<summary>
- Pipeline step execution including release, docker commit, and git sync steps are tested
- Step failure handling and skip logic are covered for all step types
- When a custom check command is configured, the precommit step uses it
- Steps that return SKIP are handled differently depending on step type
- Coverage target: pipeline.py goes from 78% to at least 85%
</summary>

<objective>
Coverage for `pipeline.py` rises from 78% to at least 85%, with specific step implementations and pipeline skip logic exercised by automated tests. This ensures step behavior and pipeline control flow are verified and regressions caught by CI.
</objective>

<context>
Read CLAUDE.md for project conventions.
Read `src/updater/pipeline.py` — focus on uncovered lines: 69, 126-128, 145-169, 247, 291-309, 385, 398-434, 438-456, 493, 516-534, 573-587, 618, 663, 667.
Read `tests/test_pipeline.py` — understand existing patterns. Tests mock `run_command`, `git_operations`, and `changelog` functions.

Note: `ReleaseStep` does NOT create git tags itself — it sets `context["new_version"]` and `context["commit_message"]`. The tag is created by `GitCommitStep`.
</context>

<requirements>
1. Add tests for uncovered step paths:
   - `PrecommitStep`: custom check command used when configured
   - `ReleaseStep`: full success path with changelog update — verify it sets context values (not git tag)
   - `DockerCommitStep`: changes detected → commits; no changes → skips
   - `GitSyncStep`: success and failure paths

2. Add tests for pipeline skip/continue logic:
   - `GoDepSkipStep` returns SKIP → pipeline continues to next step
   - `GitConfirmStep` returns SKIP → pipeline returns early

3. Mock all external calls (subprocess, git operations, changelog)

4. Target: raise `pipeline.py` coverage from 78% to at least 85%
</requirements>

<constraints>
- Do NOT modify source code — only add/modify tests
- Do NOT commit — dark-factory handles git
- Existing tests must still pass
</constraints>

<verification>
Run `make precommit` — must pass with exit code 0.
Run `uv run --with pytest-cov pytest --cov=updater.pipeline --cov-report=term-missing tests/test_pipeline.py` — coverage should be >= 85%.
</verification>
