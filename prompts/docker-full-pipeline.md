---
status: draft
created: "2026-04-08T06:40:41Z"
---

<summary>
- `updater docker` currently only edits the Dockerfile and prints "review and commit manually" — it does not run precommit, does not commit, does not push, does not tag
- After this change, `updater docker` behaves like `updater go` and `updater python`: sync → update Dockerfile → precommit → analyze → update changelog (if present) → commit → tag (if changelog) → push
- Repos with CHANGELOG.md get a changelog entry + version tag like other subcommands
- Repos without CHANGELOG.md still get precommit + commit + push (no changelog, no tag) — matches the existing behavior of `ChangelogStep` Case 3
- `updater docker` no longer leaves Dockerfile changes stranded in the working tree
- Behavior of other subcommands (`go`, `python`, `all`, `release`, `fix`) is unchanged
</summary>

<objective>
Replace the minimal 2-step docker pipeline (`DockerUpdateStep → DockerCommitStep`) with a full pipeline that mirrors `process_single_python_module`: git sync → docker update → check changes → precommit → check changes → changelog → git confirm → git commit (with push). The Dockerfile edit must be followed through to a pushed commit, with tagging happening only when CHANGELOG.md exists.
</objective>

<context>
Read `CLAUDE.md` for project conventions and the Architecture table showing the intended step composition per subcommand.
Read `src/updater/cli.py` function `process_single_python_module` (around line 237) — this is the template to copy.
Read `src/updater/cli.py` function `process_module_with_retry` (around line 315) — the `elif project_type == "docker":` branch (around line 341) is what needs to be replaced.
Read `src/updater/pipeline.py` classes `DockerUpdateStep` (line 192), `ChangelogStep` (line 289, noting Case 3 at line 353 handles missing CHANGELOG.md), `PrecommitStep` (line 267), `GitSyncStep`, `GitConfirmStep`, `GitCommitStep`, `CheckChangesStep`.
Read `src/updater/cli.py` function `_run_docker_modules` (around line 1603) — this discovers docker modules and calls into the retry/pipeline layer.
</context>

<requirements>
1. Create a new function `process_single_docker_module(module_path: Path) -> tuple[bool, str]` in `src/updater/cli.py`, modeled directly on `process_single_python_module` (line 237). It must:
   - Set up module logging, ensure `.update-logs/` is in `.gitignore`, find the git repo, fail cleanly if no git repo
   - Build a `Pipeline` with these steps in order:
     1. `GitSyncStep()`
     2. `DockerUpdateStep()`
     3. `CheckChangesStep(phase="update")`
     4. `PrecommitStep(project_type="docker")`
     5. `CheckChangesStep(phase="precommit")`
     6. `ChangelogStep()`
     7. `GitConfirmStep()`
     8. `GitCommitStep()`
   - Return `(True, "up-to-date")` / `(True, "skipped")` / `(True, "updated")` on the same `StepStatus` values as the Python function, and `(False, "failed")` on exceptions
   - Close logging and clean up old logs in a `finally` block, same as the Python function
2. In `PrecommitStep.run` (`src/updater/pipeline.py` around line 273), add a `project_type == "docker"` branch. Docker repos may not have a go/python toolchain. Use the simplest portable approach: run `make precommit` via `run_command("make precommit", cwd=module_path, quiet=True, log_func=log_message)`. If `config.CHECK_COMMAND` is set, keep respecting that (the existing first branch already does). Fall through to the current go branch only for go project types.
3. In `src/updater/cli.py` function `process_module_with_retry` (around line 341), replace the entire `elif project_type == "docker":` block that currently constructs a 2-step `Pipeline([DockerUpdateStep(), DockerCommitStep()])` with a single call: `success, status = await process_single_docker_module(module_path)`. The imports `DockerCommitStep, DockerUpdateStep, Pipeline, StepStatus` inside that branch become unused — remove them.
4. In `src/updater/cli.py` function `_run_docker_modules` (around line 1603), replace the current logic (which calls `update_dockerfile_images` directly and prints "review and commit manually") with the same structure as `_run_python_modules` (around line 1557): for each discovered docker module path, call `process_module_with_retry(mod, project_type="docker")`. Discovery of Dockerfile-containing directories stays as today (walk for `Dockerfile`, skip `.venv`).
5. The old `DockerCommitStep` class in `src/updater/pipeline.py` (around line 640) is now unused. If nothing else references it, remove it. If it is referenced by tests or other code, leave it in place and add a `# TODO: remove after full-pipeline migration` comment.
6. Add a pytest test in `tests/` that:
   - Creates a temp git repo with a `Dockerfile` containing an outdated base image (e.g. `FROM golang:1.20.0`) and NO `CHANGELOG.md`
   - Mocks Claude analysis
   - Invokes `process_single_docker_module(tmp_path)` (or the equivalent path through `process_module_with_retry`)
   - Asserts the Dockerfile was updated AND asserts the resulting git log contains a new commit (i.e. the change was committed, not left in the working tree)
   - Asserts no tag was created (no CHANGELOG.md → no tag)
7. Add a second pytest test for the WITH-changelog case: same setup plus a valid `CHANGELOG.md` with a prior version. Assert a new version tag was created and the CHANGELOG.md now contains an entry.
8. Update the Architecture table in `CLAUDE.md` so the `updater docker` row reads: `DockerUpdate pipeline (GitSync → DockerUpdate → Precommit → Changelog → Commit)` — matching the other rows' level of detail.
</requirements>

<constraints>
- Do NOT commit — dark-factory handles git
- Existing tests must still pass
- Do not modify `ChangelogStep` — Case 3 already handles missing CHANGELOG.md correctly
- Do not create `CHANGELOG.md` anywhere automatically. Missing means skip the changelog + skip the tag, not create.
- Do not touch `_run_release_modules`, `ReleaseStep`, or CHANGELOG.md gating for the `release` subcommand — that is handled by a separate prompt (`release-allow-missing-changelog.md`) and must remain independent
- Keep changes scoped: `process_single_docker_module` (new), `process_module_with_retry` docker branch, `_run_docker_modules`, `PrecommitStep`, CLAUDE.md architecture row, new tests
- Use existing utilities (`setup_module_logging`, `ensure_gitignore_entry`, `find_git_repo`, `close_module_logging`, `cleanup_old_logs`, `run_command`) — do not reimplement them
- Match the code style of `process_single_python_module` closely — this is a deliberate copy-with-substitution
</constraints>

<verification>
Run `make precommit` — must pass.
</verification>
