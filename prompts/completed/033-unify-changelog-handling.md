---
status: completed
container: updater-033-unify-changelog-handling
dark-factory-version: v0.107.5
created: "2026-04-08T06:40:35Z"
queued: "2026-04-08T06:40:35Z"
started: "2026-04-08T06:40:41Z"
completed: "2026-04-08T06:46:07Z"
---

<summary>
- All `updater` subcommands should treat CHANGELOG.md the same way: present → update it and tag a version; absent → skip both, still run precommit + commit + push
- Today the behavior is inconsistent: `go`, `python`, `all`, `fix` rely on `ChangelogStep` Case 3 (which already handles missing CHANGELOG.md), but `release` hard-fails at discovery in two places with "No modules with CHANGELOG.md found"
- After this change, `updater release` works in repos without CHANGELOG.md (same precommit + commit + push flow), and `go` / `python` are verified end-to-end to also work without CHANGELOG.md
- No CHANGELOG.md is ever created automatically — missing means skip
- `docker` subcommand is NOT in scope here (handled by separate prompt `docker-full-pipeline.md`)
- The end state: every subcommand that reaches `ChangelogStep` handles "no changelog" identically via Case 3, and no discovery gate filters modules by CHANGELOG.md presence
</summary>

<objective>
Unify CHANGELOG.md handling across all subcommands so they behave identically: with CHANGELOG.md → update + tag; without → skip changelog + skip tag, still run precommit + commit + push. Remove the two CHANGELOG.md discovery gates in the release paths, and verify (with tests) that `go`, `python`, and `release` all succeed on a repo without CHANGELOG.md.
</objective>

<context>
Read `CLAUDE.md` for project conventions.
Read `src/updater/pipeline.py` class `ChangelogStep` around line 289, especially Case 3 at line 353 — this is the canonical "no CHANGELOG.md" handler and must NOT be modified. It sets `context["no_tag"] = True` and returns `StepResult(StepStatus.SUCCESS)`.
Read `src/updater/pipeline.py` classes `GitCommitStep` (around line 406) and `GitPushStep` (around line 435) — these must already respect `context["no_tag"]`. Verify they do not crash or skip commit/push when `new_version` is absent.
Read `src/updater/cli.py` function `main_release_async` (around line 1364). The discovery gate at lines 1439 and 1453 must be removed.
Read `src/updater/cli.py` function `_run_release_modules` (around line 1636). The duplicate discovery gate at lines 1657 and 1669 must be removed.
Read `src/updater/cli.py` function `process_single_python_module` (around line 237) and `process_single_go_module` (around line 69) — confirm both pipelines include `ChangelogStep` and that no other step between `ChangelogStep` and the end of the pipeline assumes `new_version` is set.
Read `src/updater/pipeline.py` class `ReleaseStep` (around line 448). If it requires CHANGELOG.md, make it skip gracefully like `ChangelogStep` Case 3.
Read `src/updater/cli.py` function `print_commit_summary` (referenced from `ChangelogStep`) — confirm it handles the "no new_version" branch without crashing.
</context>

<requirements>
1. **Remove discovery gate in `main_release_async`** (`src/updater/cli.py` around lines 1438-1455). Currently only modules with CHANGELOG.md are appended to `module_paths`, and the function fails with "No modules with CHANGELOG.md found" if none match. New behavior: discover all modules of any supported type (go.mod, pyproject.toml+uv.lock, Dockerfile) using `discover_all_modules`. A module without CHANGELOG.md is a valid release target. Still fail with a clear message ("✗ No modules found") only if no modules of any type exist.

2. **Remove discovery gate in `_run_release_modules`** (`src/updater/cli.py` around lines 1657-1671). Apply the exact same fix as requirement 1 — this is the unified subcommand entry point and has duplicated logic. Deduplicate if possible by extracting a helper `_discover_release_modules(paths: list[Path]) -> list[Path]`, but only if it does not force large refactors in `main_release_async`.

3. **Audit `ReleaseStep`** in `src/updater/pipeline.py` (around line 448). If it reads from CHANGELOG.md (e.g. to determine version bump or parse unreleased entries), add a missing-CHANGELOG.md branch at the start of `run()` that:
   - Logs `→ No CHANGELOG.md found, skipping release step (no tag will be created)`
   - Sets `context["no_tag"] = True`
   - Returns `StepResult(StepStatus.SUCCESS)`
   If `ReleaseStep` does not depend on CHANGELOG.md, leave it alone and document this in a code comment.

4. **Verify downstream steps after `ChangelogStep`** handle `new_version=None` / `no_tag=True`. Prior inspection suggests `GitCommitStep` already reads `analysis.get("commit_message", "Update")` (around L415) and gates tag creation on `"new_version" in context` (around L423), so no change is likely needed. Tasks:
   - Read `GitCommitStep`, `GitPushStep`, `GitConfirmStep`, and `print_commit_summary`
   - Confirm each handles the `new_version=None` / `no_tag=True` path without crashing
   - Only patch a step if you find an actual bug — do not refactor working code
   - Do not modify `ChangelogStep` itself under any circumstances

5. **Add pytest tests** in a new file `tests/test_no_changelog.py` covering the uniform behavior. Mock `verify_claude_auth`, `analyze_changes_with_claude`, and `play_completion_sound` as needed. For each test, create a temp git repo with the appropriate module file and NO CHANGELOG.md:
   - `test_go_without_changelog` — temp repo with `go.mod` + a trivial change; call `process_single_go_module(tmp_path)`; assert it returns `(True, "updated")`, a new commit exists in git log, and NO new tag was created
   - `test_python_without_changelog` — same structure with `pyproject.toml` + `uv.lock`; call `process_single_python_module(tmp_path)`
   - `test_release_without_changelog_via_run_release_modules` — call `_run_release_modules([str(tmp_path)])` on a repo without CHANGELOG.md but with pending uncommitted changes; assert exit code 0, commit was made, no tag was created
   - `test_release_without_changelog_via_main_release_async` — same for the legacy `main_release_async` entry point. `main_release_async` takes no arguments and parses `sys.argv` via its own `argparse.ArgumentParser`, so use `monkeypatch.setattr("sys.argv", ["updater-release", str(tmp_path)])` before calling it
   - All four tests must be marked `@pytest.mark.asyncio` (or use the project's existing async test helper — check `tests/` for the established pattern)

6. **Add regression test** `test_release_with_changelog_still_tags` in the same file: same setup but WITH a valid CHANGELOG.md (containing `## v0.1.0` as a prior version and `## Unreleased` bullets). Assert exit code 0, commit was made, AND a new version tag exists.

7. **Do NOT create CHANGELOG.md anywhere automatically.** Missing means skip.

8. **Do NOT touch the `docker` subcommand** (`_run_docker_modules`, `process_module_with_retry` docker branch, `DockerUpdateStep`, `DockerCommitStep`). That is handled by a separate prompt `docker-full-pipeline.md` and must stay independent.
</requirements>

<constraints>
- Do NOT commit — dark-factory handles git
- Existing tests must still pass
- Do not modify `ChangelogStep` — Case 3 already handles missing CHANGELOG.md correctly
- Do not create `CHANGELOG.md` automatically, ever
- Do not touch the docker subcommand — separate prompt
- Use existing helpers (`discover_all_modules`, `discover_python_modules`, `verify_claude_auth`, `play_completion_sound`) — do not reimplement
- Match the code style of nearby functions
- Keep each change minimal — the goal is uniform behavior, not refactoring
- Tests must mock Claude auth and analysis so they run offline in the dark-factory container
</constraints>

<verification>
Run `make precommit` — must pass.
</verification>
