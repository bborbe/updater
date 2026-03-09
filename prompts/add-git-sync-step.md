---
status: created
created: "2026-03-09T10:00:00Z"
---

<summary>
- Add a `GitSyncStep` to `pipeline.py` that syncs the git repo with `origin/master` before any updates
- The function `update_git_branch()` already exists in `git_operations.py` (line 147) — just needs a pipeline wrapper
- Insert as the first step in both Go and Python pipelines (`process_single_go_module` and `process_single_python_module` in `cli.py`)
- If fetch or merge fails (conflict, no network), the step returns `StepStatus.FAILED` and the pipeline aborts — no partial updates
- `update-docker` and `release-only` pipelines are unaffected
</summary>

<objective>
Add a `GitSyncStep` that runs `update_git_branch()` as the first pipeline step for all Go and Python update commands, so every update always starts from a repo that is current with `origin/master`.
</objective>

<context>
Read CLAUDE.md for project conventions.

Key files:
- `src/updater/git_operations.py` line 147 — `update_git_branch(repo_path, log_func)` — already does `git fetch origin` + `git pull` (if tracking branch) + `git merge origin/master`. Returns `True` on success, `False` on failure.
- `src/updater/pipeline.py` line 62 — `Step` ABC with `async def run(self, module_path, context) -> StepResult`. Line 90 — `GoVersionUpdateStep` is the simplest example of a step wrapping a single function call.
- `src/updater/cli.py` line 68 — `process_single_go_module()` builds the Go pipeline. Line 153 — `process_single_python_module()` builds the Python pipeline. Both use `find_git_repo(module_path)` to get the repo path before building the pipeline.

Existing step pattern (from `pipeline.py` ~line 90):
```python
class GoVersionUpdateStep(Step):
    """Update Go/Alpine versions in go.mod, Dockerfile, CI configs."""

    async def run(self, module_path: Path, context: dict[str, Any]) -> StepResult:
        updates = update_versions(module_path, log_func=log_message)
        context.setdefault("updates_made", False)
        context["updates_made"] = context["updates_made"] or updates
        return StepResult(StepStatus.SUCCESS, {"changes": updates})
```

Current Go pipeline in `process_single_go_module()` (cli.py line 119):
```python
pipeline = Pipeline(
    [
        GoVersionUpdateStep(),   # ← insert GitSyncStep before this
        GoExcludesStep(),
        ...
    ]
)
```

Current Python pipeline in `process_single_python_module()` (cli.py line 199):
```python
pipeline = Pipeline(
    [
        PythonVersionUpdateStep(),   # ← insert GitSyncStep before this
        ...
    ]
)
```

`git_repo` (the repo path) is already resolved via `find_git_repo(module_path)` before the pipeline is built in both functions — but `GitSyncStep` receives `module_path`, not `git_repo`. Use `find_git_repo(module_path)` inside the step (it's already imported in `cli.py`), or pass `module_path` directly since `update_git_branch` accepts any path within the repo.
</context>

<requirements>
1. Add `GitSyncStep` to `src/updater/pipeline.py` in the "git steps" section (near `GitCommitStep`, `GitPushStep`):
   ```python
   class GitSyncStep(Step):
       """Sync repo with origin/master before updating."""

       async def run(self, module_path: Path, context: dict[str, Any]) -> StepResult:
           log_message("=== Phase 0: Sync with origin/master ===", to_console=True)
           success = update_git_branch(module_path, log_func=log_message)
           if not success:
               return StepResult(StepStatus.FAILED, {"error": "git sync failed"})
           return StepResult(StepStatus.SUCCESS, {})
   ```
   Import `update_git_branch` from `git_operations` at the top of `pipeline.py` (check if already imported).

2. Insert `GitSyncStep()` as the first step in `process_single_go_module()` pipeline (cli.py line ~121):
   ```python
   pipeline = Pipeline(
       [
           GitSyncStep(),
           GoVersionUpdateStep(),
           ...
       ]
   )
   ```
   Add `GitSyncStep` to the import from `.pipeline` at line ~82.

3. Insert `GitSyncStep()` as the first step in `process_single_python_module()` pipeline (cli.py line ~200):
   ```python
   pipeline = Pipeline(
       [
           GitSyncStep(),
           PythonVersionUpdateStep(),
           ...
       ]
   )
   ```
   Add `GitSyncStep` to the import from `.pipeline` at line ~166.

4. Add tests in `tests/test_pipeline.py` following existing step test patterns:
   - `test_git_sync_step_success`: mock `update_git_branch` returning `True`, assert `StepStatus.SUCCESS`
   - `test_git_sync_step_failure`: mock `update_git_branch` returning `False`, assert `StepStatus.FAILED`

5. Update `CHANGELOG.md` under `## Unreleased`:
   ```
   - Sync with origin/master before updating (git fetch -p + merge) for all go/python update commands
   ```
</requirements>

<constraints>
- Do NOT commit — dark-factory handles git
- Do NOT modify `update_git_branch()` in `git_operations.py`
- Do NOT add `GitSyncStep` to docker or release pipelines
- `update-deps` / `update-all` (`main_async`) already syncs git separately — do not add `GitSyncStep` there to avoid double-sync
- All existing pipeline step order must be preserved after `GitSyncStep`
- Existing tests must still pass
</constraints>

<verification>
Run `make precommit` — must pass with exit code 0.
Run `uv run pytest` — all tests must pass.
</verification>
