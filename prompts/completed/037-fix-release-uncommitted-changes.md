---
status: completed
summary: Added CommitUncommittedStep to updater release pipeline so uncommitted changes are auto-committed before ReleaseStep checks for new releases
container: updater-037-fix-release-uncommitted-changes
dark-factory-version: v0.108.0-dirty
created: "2026-04-12T07:50:21Z"
queued: "2026-04-12T07:53:32Z"
started: "2026-04-12T07:53:35Z"
completed: "2026-04-12T07:54:56Z"
---
<summary>
- Running `updater release` with uncommitted file edits silently ignores them and reports "Nothing to release"
- Only committed changes are detected — staged, unstaged, and untracked files are invisible to the release check
- After the fix, uncommitted changes are auto-committed before checking for new releases
- Existing release behavior for already-committed changes is unchanged
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
Read `docs/dod.md` for quality standards (especially test conventions: no real subprocess/filesystem calls in tests).
Read `docs/architecture.md` for pipeline step contracts.

Bug scenario:
1. User manually edits Dockerfile (e.g. bumps golang version)
2. Runs `updater release`
3. `ReleaseStep` calls `get_commits_since_tag()` → empty (edit is uncommitted)
4. Returns "Nothing to release" — edit is silently ignored
</context>

<requirements>
1. Create a new pipeline step `CommitUncommittedStep` in `src/updater/pipeline.py`:
   - Check for uncommitted changes using `run_command("git status --porcelain", ...)` and inspect stdout
   - If working tree is clean (empty output), return `StepResult(StepStatus.UP_TO_DATE)` (continue pipeline, not skip)
   - If dirty, log the changed files
   - Run `git add .` and `git commit -m "update files"` via `run_command` (import from `.log_manager`)
   - Log what was committed (e.g. "→ Committed uncommitted changes")
   - Return `StepResult(StepStatus.SUCCESS)`
   - Follow the existing Step base class pattern (async run, return StepResult)
   - Let exceptions propagate (consistent with other steps — no extra error handling)

2. In `process_release_module` (~line 1294 of `src/updater/cli.py`), insert `CommitUncommittedStep()` as the FIRST step in the pipeline, before `ReleaseStep()`. Update the import block (~line 1266) to include `CommitUncommittedStep`. The pipeline becomes:
   ```
   CommitUncommittedStep → ReleaseStep → GitCommitStep → GitPushStep
   ```

3. Add tests in `tests/test_commit_uncommitted_step.py`:
   - Test clean working tree: mock `run_command` for `git status --porcelain` returning empty stdout → step returns UP_TO_DATE, `git add`/`git commit` NOT called
   - Test dirty working tree: mock `run_command` for `git status --porcelain` returning " M Dockerfile\n" → step calls `git add .` and `git commit`, returns SUCCESS
   - Test untracked file: mock returning "?? newfile.txt\n" → same commit behavior
   - Use `mocker` fixture for mocking `run_command`, `tmp_path` for module path
   - Follow existing test patterns in `tests/test_pipeline.py` — no real subprocess or filesystem calls
   - Mark tests `@pytest.mark.asyncio`

4. Update `CLAUDE.md` pipeline table: `updater release` row should read `CommitUncommitted → Release → GitCommit → GitPush`.
</requirements>

<constraints>
- Do NOT commit or push changes
- Do NOT modify `ReleaseStep` — it correctly handles the "no commits" case; the fix is ensuring uncommitted changes become commits before `ReleaseStep` runs
- Do NOT modify `GitCommitStep` — it handles the release commit (changelog promotion)
- The commit message for uncommitted changes should be simple ("update files") — the `ReleaseStep` + `ChangelogStep` in the release flow will analyze all commits including this one
- Use `run_command` for all shell operations (consistent with project DoD — no direct `subprocess` calls)
</constraints>

<verification>
Run `make precommit` — must pass.
</verification>
