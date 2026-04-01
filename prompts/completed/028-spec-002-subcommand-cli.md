---
status: completed
spec: [002-subcommand-cli-refactor]
summary: Replaced 8 separate CLI entry points with a single `updater <subcommand>` binary, updating pyproject.toml, CLAUDE.md, and CHANGELOG.md
container: updater-028-spec-002-subcommand-cli
dark-factory-version: v0.80.0-1-g2b37ac1
created: "2026-04-01T08:00:00Z"
queued: "2026-04-01T07:49:00Z"
started: "2026-04-01T07:49:02Z"
completed: "2026-04-01T07:52:27Z"
branch: dark-factory/subcommand-cli-refactor
---

<summary>
- A new `updater` binary replaces the 8 separate `update-*` / `release-only` / `fix-only` commands
- `updater go`, `updater all`, `updater go-only`, `updater go-with-deps`, `updater python`, `updater docker`, `updater release`, `updater fix` each run identically to their predecessor
- Global flags (`--yes`, `--check-command`, `--verbose`, `--model`, `--version`, `--require-commit-confirm`) are defined once on the root parser and apply to every subcommand
- `updater` with no subcommand prints usage and exits 1
- `updater unknown-subcmd` exits 1 with a clear error listing valid subcommands
- `pyproject.toml` is updated to expose a single `updater` entry point and removes the 8 old ones
- All existing pipeline logic, step order, and module-discovery behavior remain unchanged
</summary>

<objective>
Replace 8 separate CLI entry points with a single `updater <subcommand>` binary. Global flags are defined once on the root parser; each subcommand delegates to the same pipeline-processing logic that exists today.
</objective>

<context>
Read CLAUDE.md for project conventions.
Read `src/updater/cli.py` in full — understand every `main_*_async` function: how they parse arguments, set `config.*` globals, discover modules, and call `process_module_with_retry`.
Read `pyproject.toml` — understand current `[project.scripts]` entries.
Read `src/updater/config.py` — understand the global config variables that are set from args.
Read `tests/test_cli.py` — understand test patterns so you don't break existing tests.

Key observations from the current code:
- Every `main_*_async` function calls `parser.parse_args()` and sets `config.VERBOSE_MODE`, `config.MODEL`, `config.REQUIRE_CONFIRM`, `config.YES_MODE`, `config.CHECK_COMMAND`, `config.RUN_TIMESTAMP`
- Each then discovers modules (Go, Python, or Docker) and calls `process_module_with_retry(mod, project_type=...)`
- The processing logic itself is unchanged — we are only refactoring how arguments are parsed and how the entry point dispatches
</context>

<requirements>
1. Add `main_updater_async` in `src/updater/cli.py`:

   a. Create a root `ArgumentParser` with:
      - `description`: "Dependency updater — manages Go, Python, and Docker dependencies"
      - `--verbose` (`action="store_true"`)
      - `--version` (`action="version"`, same pkg_version call as existing parsers)
      - `--model` (choices `["sonnet", "opus", "haiku"]`, default `"sonnet"`)
      - `--require-commit-confirm` (`action="store_true"`)
      - `--yes` / `-y` (`action="store_true"`)
      - `--check-command` (default `""`, metavar `"CMD"`)

   b. Add subparsers via `parser.add_subparsers(dest="subcommand", metavar="SUBCOMMAND")`. Set `required=False` so argparse doesn't error before you can print custom usage.

   c. Register these 8 subcommands with a `modules` positional (same `nargs="*"`, `default=["."]` as existing parsers). Use the same help text as each existing parser's `description`:
      - `go`: "Update Go module dependencies, CHANGELOG, and create git tags"
      - `all`: "Update all dependencies (Go modules + other languages), CHANGELOG, and create git tags"
      - `go-only`: "Update Go version without updating module dependencies"
      - `go-with-deps`: "Update Go module dependencies including all sub-dependencies"
      - `python`: "Update Python package dependencies, CHANGELOG, and create git commits"
      - `docker`: "Update Docker base images in Dockerfiles"
      - `release`: "Create a new release (tag + changelog + push)"
      - `fix`: "Apply go.mod fixes (excludes/replaces + OSV) without version or dependency updates"

   d. Call `args = parser.parse_args()`. If `args.subcommand is None`, print the parser's help and return 1.

   e. Set global config from root-level args (same block used in every existing `main_*_async`):
      ```python
      config.VERBOSE_MODE = args.verbose
      config.MODEL = args.model
      config.REQUIRE_CONFIRM = args.require_commit_confirm
      config.YES_MODE = args.yes
      config.CHECK_COMMAND = args.check_command
      config.RUN_TIMESTAMP = datetime.now().strftime("%Y-%m-%d-%H%M%S")
      ```

   f. Dispatch to the existing module-discovery + processing logic extracted from each corresponding `main_*_async`:
      - `"go"` → same logic as `main_go_async` (Go module discovery, `project_type="go"`)
      - `"all"` → same logic as `main_async` (all-module discovery via `discover_all_modules`, `project_type` per module)
      - `"go-only"` → same logic as `main_go_only_async` (Go module discovery, `project_type="go-only"`)
      - `"go-with-deps"` → same logic as `main_go_with_deps_async` (Go module discovery, `project_type="go-with-deps"`)
      - `"python"` → same logic as `main_python_async` (Python module discovery, `project_type="python"`)
      - `"docker"` → same logic as `main_docker_async` (Docker discovery, `project_type="docker"`)
      - `"release"` → same logic as `main_release_async` (Go module discovery, `project_type="release"`)
      - `"fix"` → same logic as `main_go_fix_async` (Go module discovery, `project_type="go-fix"`)

      Do NOT duplicate the processing logic. Extract it into helper coroutines `_run_go_modules`, `_run_all_modules`, `_run_python_modules`, `_run_docker_modules`, `_run_release_modules` (or inline with a dispatch dict/if-elif chain — whichever keeps it readable and non-duplicated). The existing `main_*_async` functions must remain intact and continue to work — do NOT remove or modify them.

2. Add `main_updater` (sync wrapper) in `src/updater/cli.py`:
   ```python
   def main_updater() -> int:
       return asyncio.run(main_updater_async())
   ```

3. Update `pyproject.toml` `[project.scripts]`:
   - Remove all 9 existing entries (`update-deps`, `update-all`, `update-go`, `update-go-only`, `update-go-with-deps`, `update-python`, `update-docker`, `release-only`, `fix-only`)
   - Add single entry: `updater = "updater.cli:main_updater"`

4. Keep all existing `main_*` and `main_*_async` functions intact — do not modify or delete them. They remain callable and tested.

5. Update `CLAUDE.md` — in the Architecture section, update the "CLI Entry Points → Pipelines" table to replace all old command names with `updater <subcommand>` equivalents.
</requirements>

<constraints>
- Do NOT commit — dark-factory handles git
- Do NOT change any pipeline logic, step order, or module-discovery logic
- Do NOT remove or modify existing `main_*` / `main_*_async` functions
- All existing tests must still pass unchanged
- Global flags must behave identically to current per-parser flags
- `updater` with no subcommand must print usage and return exit code 1
- `--yes` and `--check-command` must be on the root parser (not per-subcommand)
</constraints>

<verification>
Run `make precommit` — must pass with exit code 0.
Run `uv run updater --help` — must list all 8 subcommands.
Run `uv run updater go --help` — must show subcommand-specific help.
Run `uv run updater 2>&1; echo "exit: $?"` — must print usage and exit 1.
</verification>
