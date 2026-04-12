---
status: ""
created: "2026-04-12T07:50:21Z"
---
<summary>
- `updater release` ignores uncommitted/unstaged changes in the working tree
- `ReleaseStep` checks `get_commits_since_tag()` which only sees committed changes
- If Dockerfile or other files were edited but not committed, release reports "Nothing to release (no commits since last tag)"
- The fix adds a pre-commit step to the release pipeline that detects dirty working tree, analyzes changes with Claude, commits them, then proceeds with normal release flow
</summary>

<objective>
Make `updater release` detect uncommitted changes (staged + unstaged + untracked) and commit them before the `ReleaseStep` checks for commits since last tag. This ensures manually edited files (e.g. Dockerfile version bumps) get included in the release.
</objective>

<context>
Read `CLAUDE.md` for project conventions and pipeline architecture.
Read `src/updater/cli.py` function `process_release_module` (line 1252) — current pipeline is `ReleaseStep → GitCommitStep → GitPushStep`.
Read `src/updater/pipeline.py` class `ReleaseStep` (line 448) — at line 520-525 it calls `get_commits_since_tag()` and returns UP_TO_DATE if empty.
Read `src/updater/pipeline.py` class `ChangelogStep` (line 289) — this is how the `all` pipeline handles changelog + commit, for reference on the pattern.
Read `src/updater/git_operations.py` function `git_commit` (line 235) — does `git add . && git commit`.
Read `src/updater/git_operations.py` function `get_commits_since_tag` (line 407) — only sees committed changes.
Read `src/updater/pipeline.py` class `CheckChangesStep` (line 211) — detects file changes in working tree.

Bug scenario:
1. User manually edits Dockerfile (e.g. bumps golang version)
2. Runs `updater release`
3. `ReleaseStep` calls `get_commits_since_tag()` → empty (edit is uncommitted)
4. Returns "Nothing to release" — edit is silently ignored
</context>

<requirements>
1. Create a new pipeline step `CommitUncommittedStep` in `src/updater/pipeline.py`:
   - Check for uncommitted changes using `git status --porcelain` via `subprocess.run`
   - If working tree is clean, return `StepResult(StepStatus.UP_TO_DATE)` (continue pipeline, not skip)
   - If dirty, log the changed files
   - Run `git add .` and `git commit -m "update files"` via the existing `run_command` utility (import from `.log_manager`)
   - Log what was committed (e.g. "→ Committed uncommitted changes")
   - Return `StepResult(StepStatus.SUCCESS)`
   - Follow the existing Step base class pattern (async run, return StepResult)

2. In `process_release_module` (line 1294 of `src/updater/cli.py`), insert `CommitUncommittedStep()` as the FIRST step in the pipeline, before `ReleaseStep()`. The pipeline becomes:
   ```
   CommitUncommittedStep → ReleaseStep → GitCommitStep → GitPushStep
   ```

3. Add tests in `tests/test_commit_uncommitted_step.py`:
   - Test clean working tree: step returns UP_TO_DATE, no commit created
   - Test dirty working tree (modified file): step commits changes, new commit exists in log
   - Test untracked file: step commits it
   - Use `tmp_path`, init a real git repo with `subprocess.run` (git init, initial commit), then modify files and run step
   - Mark tests `@pytest.mark.asyncio`

4. Update `CLAUDE.md` pipeline table: `updater release` row should read `CommitUncommitted → Release → GitCommit → GitPush`.
</requirements>

<constraints>
- Do NOT commit or push changes
- Do NOT modify `ReleaseStep` — it correctly handles the "no commits" case; the fix is ensuring uncommitted changes become commits before `ReleaseStep` runs
- Do NOT modify `GitCommitStep` — it handles the release commit (changelog promotion)
- The commit message for uncommitted changes should be simple ("update files") — the `ReleaseStep` + `ChangelogStep` in the release flow will analyze all commits including this one
- Use `subprocess.run` for `git status --porcelain` check (consistent with `get_commits_since_tag` pattern)
- Use `run_command` from `.log_manager` for `git add` and `git commit` (consistent with `git_commit` in `git_operations.py`)
</constraints>

<verification>
Run `make precommit` — must pass.
</verification>
