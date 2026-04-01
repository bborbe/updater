---
status: created
spec: [002-subcommand-cli-refactor]
created: "2026-04-01T08:00:00Z"
branch: dark-factory/subcommand-cli-refactor
---

<summary>
- Test coverage exists for the new `updater` subcommand entry point
- `updater` with no subcommand is verified to print usage and return exit code 1
- `updater go`, `updater all`, `updater python`, `updater docker`, `updater release`, `updater fix` dispatch correctly
- Global flags (`--yes`, `--check-command`) set config correctly across subcommands
- `updater --help` and `updater go --help` produce non-empty help output
- All existing tests still pass
</summary>

<objective>
Add test coverage for `main_updater_async` and `main_updater` (added in the previous prompt) so the new subcommand dispatch is regression-protected. Tests verify routing, global flag propagation, and error cases for missing/unknown subcommands.
</objective>

<context>
Read CLAUDE.md for project conventions.
Read `src/updater/cli.py` — focus on `main_updater_async` and `main_updater` added in the prior prompt. Understand how the dispatcher calls `process_module_with_retry` for each subcommand.
Read `tests/test_cli.py` — understand the existing test patterns:
  - async tests use `pytest.mark.asyncio` (asyncio_mode = "auto" so the decorator may not be needed)
  - mocking uses `unittest.mock.patch` and `AsyncMock`
  - `subprocess.run` is mocked for git commands
  - Pipeline steps are mocked via `patch` on the relevant step classes or on `process_module_with_retry`
Read `src/updater/config.py` — the global config vars (`YES_MODE`, `CHECK_COMMAND`, etc.) that need to be verified in tests.
</context>

<requirements>
Add tests to `tests/test_cli.py` for `main_updater_async`. Follow existing test style exactly.

1. **No subcommand → exits 1**
   - Patch `sys.argv` to `["updater"]`
   - Call `main_updater_async()` and assert return value is `1`
   - Assert something was printed (capture stdout or just verify exit code)

2. **Subcommand dispatch — `go`**
   - Patch `sys.argv` to `["updater", "go", "/some/path"]`
   - Mock `process_module_with_retry` to return `(True, "ok")`
   - Mock module discovery (`discover_go_modules` or check `(path / "go.mod").exists()`)
   - Call `main_updater_async()` and assert it returns `0`
   - Assert `process_module_with_retry` was called with `project_type="go"`

3. **Subcommand dispatch — `python`**
   - Same pattern as above but `sys.argv = ["updater", "python", "/some/path"]`
   - Assert `process_module_with_retry` called with `project_type="python"`

4. **Subcommand dispatch — `release`**
   - `sys.argv = ["updater", "release", "/some/path"]`
   - Assert `process_module_with_retry` called with `project_type="release"`

5. **Subcommand dispatch — `fix`**
   - `sys.argv = ["updater", "fix", "/some/path"]`
   - Assert `process_module_with_retry` called with `project_type="go-fix"`

6. **Subcommand dispatch — `docker`**
   - `sys.argv = ["updater", "docker", "/some/path"]`
   - Assert `process_module_with_retry` called with `project_type="docker"` (or that the docker update logic runs)

7. **Global flag `--yes` propagates**
   - `sys.argv = ["updater", "--yes", "go", "/some/path"]`
   - Mock `process_module_with_retry` to return `(True, "ok")`
   - Call `main_updater_async()` and assert `config.YES_MODE is True`

8. **Global flag `--check-command` propagates**
   - `sys.argv = ["updater", "--check-command", "make ensure test", "go", "/some/path"]`
   - Mock `process_module_with_retry` to return `(True, "ok")`
   - Call `main_updater_async()` and assert `config.CHECK_COMMAND == "make ensure test"`

9. **`main_updater` sync wrapper**
   - Patch `asyncio.run` to return `0`
   - Call `main_updater()` and assert it returns `0`

Use `tmp_path` fixture when a real path is needed. Mock `Path.exists` or create a fake `go.mod` in `tmp_path` to satisfy module discovery.

Reset `config.*` globals between tests using a fixture or teardown to avoid cross-test pollution.
</requirements>

<constraints>
- Do NOT modify source code — only add/modify tests
- Do NOT commit — dark-factory handles git
- All existing tests must still pass
- Mock external dependencies (subprocess, pipeline steps, claude_analyzer) — no real subprocess or network calls
- Follow existing test file conventions (imports, class structure, fixture style)
</constraints>

<verification>
Run `make precommit` — must pass with exit code 0.
Run `uv run --with pytest-cov pytest --cov=updater.cli --cov-report=term-missing tests/test_cli.py` — `main_updater_async` lines should be covered.
</verification>
