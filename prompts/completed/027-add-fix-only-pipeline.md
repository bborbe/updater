---
status: completed
summary: Added fix-only CLI entry point with process_single_go_fix_module, main_go_fix_async/main_go_fix, go-fix branch in process_module_with_retry, pyproject.toml registration, CLAUDE.md pipeline table update, and tests
container: updater-027-add-fix-only-pipeline
dark-factory-version: v0.80.0-1-g2b37ac1
created: "2026-04-01T07:21:31Z"
queued: "2026-04-01T07:21:31Z"
started: "2026-04-01T07:22:17Z"
completed: "2026-04-01T07:24:51Z"
---
<summary>
- New `fix-only` CLI command available via `uv run fix-only [paths]`
- Applies go.mod standard excludes/replaces (from STANDARD_REPLACES) without updating Go version or dependencies
- Runs OSV vulnerability fixes
- Runs `make precommit` and commits changes with changelog entry
- CLAUDE.md pipeline table updated with new entry
</summary>

<objective>
Add a new `fix-only` CLI entry point that applies standard go.mod excludes/replaces and OSV fixes without updating Go version or dependencies.

Pipeline: GitSync → GoExcludes → Osv → CheckChanges → Precommit → CheckChanges → Changelog → GitConfirm → GitCommit
</objective>

<context>
Read src/updater/cli.py — all entry points and pipelines are defined here.
Read src/updater/pipeline.py — all pipeline steps are defined here.
Read pyproject.toml — entry points are registered under [project.scripts].
Read CLAUDE.md — pipeline table in Architecture section needs updating.

Existing pipelines for reference:
- Full update (process_single_go_module): GitSync → GoVersion → GoExcludes → GoDep → Osv → CheckChanges(update) → Precommit → CheckChanges(precommit) → Changelog → GitConfirm → GitCommit
- Go-only (update_deps=False): Same but with GoDepSkipStep instead of GoDepUpdateStep
- Release-only (process_release_module): Release → GitCommit → GitPush

The new pipeline is a subset: no GoVersion, no GoDep — just applies fixes from STANDARD_REPLACES/STANDARD_EXCLUDES and OSV, then commits.

Use case: when STANDARD_REPLACES gets new entries (like go-header v0.5.0), run `fix-only` across all projects to apply them without touching Go version or deps.
</context>

<requirements>
1. Add `process_single_go_fix_module` function in cli.py that builds this pipeline:
   ```python
   pipeline = Pipeline([
       GitSyncStep(),
       GoExcludesStep(),
       OsvFixStep(),
       CheckChangesStep(phase="update"),
       PrecommitStep(project_type="go"),
       CheckChangesStep(phase="precommit"),
       ChangelogStep(),
       GitConfirmStep(),
       GitCommitStep(),
   ])
   ```
   Follow the same pattern as `process_single_go_module` (logging setup, git repo check, error handling, cleanup).

2. Add `main_go_fix_async` and `main_go_fix` entry points in cli.py following the exact pattern of `main_go_only_async`/`main_go_only`:
   - Same arguments: modules, --verbose, --version, --model, --require-commit-confirm, --yes, --check-command
   - Description: "Apply go.mod fixes (excludes/replaces + OSV) without version or dependency updates"
   - Discovery: same Go module discovery logic as main_go_only_async

3. In `process_module_with_retry`, add a `project_type="go-fix"` branch. Insert before the existing `else` (Go) branch:
   ```python
   elif project_type == "go-fix":
       success, status = await process_single_go_fix_module(module_path)
   ```

4. Register entry point in pyproject.toml under `[project.scripts]`:
   ```toml
   fix-only = "updater.cli:main_go_fix"
   ```
   Place it after `release-only`.

5. Update CLAUDE.md pipeline table in the Architecture section — add row:
   ```
   | `fix-only` | `main_go_fix_async` | GitSync → Excludes → Osv → Precommit → Changelog → Commit |
   ```

6. Add test in tests/test_cli.py for the new entry point if similar tests exist for other entry points.
</requirements>

<constraints>
- Do NOT modify any existing pipeline or entry point
- Do NOT add new pipeline steps — reuse existing steps only
- Follow the exact same argument parser pattern as main_go_only_async
- Do NOT rename or refactor existing code
</constraints>

<verification>
Run `make precommit` — must pass with exit code 0.
Run `uv run fix-only --version` — must print version string.
Run `uv run fix-only --help` — must show help with correct description.
</verification>
