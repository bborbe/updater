---
status: created
created: "2026-03-09T10:00:00Z"
---

<summary>
- A new `--check-command` flag allows overriding the validation command run before committing
- Default behavior is unchanged: `make precommit` runs as before
- When set (e.g. `--check-command "make ensure test"`), that command runs instead of `make precommit`
- Useful for bulk updates across many services where `make precommit` is slow or broken
- `make ensure test` is a good lighter alternative: fixes the vendor dir and validates tests, skips vulncheck/format/lint
- Generic flag name — works with any build tool, not tied to `make`
- The override is stored globally so it applies consistently to every module processed in one run
- Five update commands gain the flag; the docker and release commands are unaffected
</summary>

<objective>
Add a `--check-command` flag to all update commands so the validation gate before committing can be overridden. Default is `make precommit`. When set to e.g. `make ensure test`, it fixes the vendor dir and validates tests without running slow/broken checks like vulncheck.
</objective>

<context>
Read CLAUDE.md for project conventions.

Key files:
- `src/updater/config.py` — global flags (add `CHECK_COMMAND: str = ""` here, empty string means use default `make precommit`)
- `src/updater/pipeline.py` — `PrecommitStep.run()` (~line 241) — if `config.CHECK_COMMAND` is set, run that command instead of the default
- `src/updater/cli.py` — argument parsers where the flag is added, and helper functions where `PrecommitStep` is instantiated

Architecture note: the 5 `main_*_async()` parsers do NOT instantiate `PrecommitStep` directly. They call `process_module_with_retry()`, which dispatches to:
- `process_single_go_module()` — builds the pipeline with `PrecommitStep(project_type="go")` (~line 126)
- `process_single_python_module()` — builds the pipeline with `PrecommitStep(project_type="python")` (~line 204)

The flag goes on the 5 parsers (where args are parsed); the step reads `config.CHECK_COMMAND` at execution time. You do not need to touch the helper functions or pipeline building code.

Parsers that need the flag:
- `main_async()` — line ~300 (main `update-deps` command)
- `main_go_async()` — line ~618 (`update-go`)
- `main_go_only_async()` — line ~705 (`update-go-only`)
- `main_go_with_deps_async()` — line ~790 (`update-go-with-deps`)
- `main_python_async()` — line ~875 (`update-python`)

Do NOT add to `main_docker_async()` or `main_release_async()` — they don't use `PrecommitStep`.

How `PrecommitStep` currently runs the precommit (in `src/updater/pipeline.py` ~line 241):
```python
if self._project_type == "python":
    run_python_precommit(module_path, log_func=log_message)
else:
    run_go_precommit(module_path, log_func=log_message)
```

`run_go_precommit` (in `src/updater/go_updater.py` line ~166) uses `run_command("make precommit", cwd=module_path, ...)`. Use the same `run_command()` wrapper for the custom command — do not use `subprocess.run` directly.

Existing pattern for a flag with global config — `--no-tag` and `--yes` in `main_async()`:
```python
parser.add_argument(
    "--no-tag",
    action="store_true",
    help="Add changes to ## Unreleased instead of creating version/tag (useful for PRs)",
)
parser.add_argument(
    "--yes", "-y",
    action="store_true",
    help="Auto-accept all prompts (non-interactive mode, for CI/containers)",
)
# then after args = parser.parse_args():
config.NO_TAG = args.no_tag
config.YES_MODE = args.yes
```

Note: `main_async()` has both `--no-tag` and `--yes`; `main_go_async()`, `main_go_only_async()`, `main_go_with_deps_async()` only have `--yes` (no `--no-tag`). In all cases, place `--check-command` after `--yes` and set `config.CHECK_COMMAND = args.check_command` immediately after `config.YES_MODE = args.yes`.
</context>

<requirements>
1. Add to `src/updater/config.py`:
   ```python
   CHECK_COMMAND: str = ""  # Override precommit command (empty = use default "make precommit")
   ```
   Place after `YES_MODE`.

2. Update `PrecommitStep.run()` in `src/updater/pipeline.py` (~line 241):
   - If `config.CHECK_COMMAND` is non-empty, run that command instead of the default
   - Use `run_command(config.CHECK_COMMAND, cwd=module_path, quiet=True, log_func=log_message)` — the same `run_command()` wrapper that `run_go_precommit` uses in `src/updater/go_updater.py` line ~176
   - Log clearly which command is running (e.g. `"→ Running custom check: {config.CHECK_COMMAND}"`)
   - `run_command` already raises on non-zero exit — no extra handling needed

3. Add `--check-command` argument to the 5 parsers in `src/updater/cli.py`:
   ```python
   parser.add_argument(
       "--check-command",
       default="",
       metavar="CMD",
       help='Override validation command (default: "make precommit"). Example: "make ensure test"',
   )
   ```
   Add after the `--yes` argument in each of the 5 parsers listed in context.

4. In each updated parser, set the config after args are parsed:
   ```python
   config.CHECK_COMMAND = args.check_command
   ```
   Place after `config.YES_MODE = args.yes`.

5. Add tests in `tests/test_pipeline.py` following the existing `PrecommitStep` test patterns in that file:
   - `test_custom_check_command_is_used`: set `config.CHECK_COMMAND = "make ensure test"`, run `PrecommitStep`, assert the custom command was executed (not the default)
   - `test_default_precommit_runs_when_no_override`: `config.CHECK_COMMAND = ""`, assert default precommit runs
   - `test_check_command_failure_raises`: set a command that fails (exit 1), assert exception is raised

6. Update `CHANGELOG.md` — add under `## Unreleased` (section already exists):
   ```
   - Add `--check-command` flag to override validation command (e.g. `make ensure test` for faster bulk updates)
   ```
</requirements>

<constraints>
- Do NOT commit — dark-factory handles git
- Default behavior must be unchanged: empty `CHECK_COMMAND` runs `make precommit` as before
- Do NOT add the flag to `main_docker_async()` or `main_release_async()`
- Custom command runs in the same `module_path` working directory as the default precommit
- Use `run_command()` — do not call `subprocess.run` directly
- Existing tests must still pass
- Follow existing config/flag patterns in the codebase
</constraints>

<verification>
Run `make precommit` — must pass with exit code 0.
Run `uv run pytest` — all tests must pass.
</verification>
