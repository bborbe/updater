---
status: completed
summary: Added --version flag to all 7 CLI entry points in src/updater/cli.py using importlib.metadata for runtime version lookup from installed package metadata.
container: updater-005-add-version-flag
dark-factory-version: v0.20.6
created: "2026-03-07T10:45:42Z"
queued: "2026-03-07T10:45:42Z"
started: "2026-03-07T10:45:42Z"
completed: "2026-03-07T10:47:58Z"
---
<objective>
Add `--version` flag to all CLI entry points in src/updater/cli.py so users can check the installed version without running an update.
</objective>

<context>
Read src/updater/cli.py — all argument parsers are defined here.
Read src/updater/__init__.py — contains `__version__ = "0.1.0"`.
Read pyproject.toml — project name is "dependency-updater".

There are 7 async functions with argument parsers:
- main_async() — update-deps / update-all
- main_go_async() — update-go
- main_go_only_async() — update-go-only
- main_go_with_deps_async() — update-go-with-deps
- main_python_async() — update-python
- main_docker_async() — update-docker
- main_release_async() — release-only
</context>

<requirements>
1. In src/updater/cli.py, import the version at the top of the file:
   ```python
   from importlib.metadata import version as pkg_version
   ```
   Use `pkg_version("dependency-updater")` to get the version at runtime (reads from installed package metadata, stays in sync with pyproject.toml automatically).

2. Add `--version` to ALL 7 argument parsers using argparse's built-in action:
   ```python
   parser.add_argument(
       "--version",
       action="version",
       version=f"%(prog)s {pkg_version('dependency-updater')}",
   )
   ```
   Place it after `--verbose` in each parser (consistent position).

3. Do NOT add `--version` to `main_go_async`, `main_go_only_async`, `main_go_with_deps_async` separately if they share a parser — check each function; they are all separate parsers so all need it.

4. Do NOT change __init__.py — `importlib.metadata` is the correct approach for installed packages.
</requirements>

<constraints>
- Do NOT modify any other argument or behavior
- Do NOT change the existing argument order except inserting --version after --verbose
- argparse's `action="version"` handles the `--version` flag automatically (prints and exits) — no manual handling needed
- Do NOT add tests — argparse's version action is stdlib behavior
</constraints>

<verification>
Run `make precommit` — must pass with exit code 0.
Run `uv run update-deps --version` — must print version string like `update-deps 0.1.0`.
Run `uv run update-go --version` — must print version string.
Run `uv run release-only --version` — must print version string.
</verification>
