# Definition of Done

After completing your implementation, review your own changes against each criterion below. These are quality checks you perform by inspecting your work — not commands to run (linting and tests already ran via `validationCommand`). Report any unmet criterion as a blocker.

## Code Quality

- Functions have doc comments (Google-style docstrings)
- No debug output (print statements) — use `log_message()` or `log_func()`
- Pipeline steps follow the Step base class pattern (async run, return StepResult)
- `run_command()` used for all shell operations — no direct `subprocess` calls (except `subprocess.run` in specific cases like `fix_osv_vulnerabilities`)

## Testing

- New code has tests covering the changed behavior
- Tests use pytest with `mocker` fixture for mocking
- Tests use `tmp_path` for filesystem operations
- No real subprocess, network, or filesystem calls in tests

## Install

- `uv pip install -e .` works
- No broken imports or circular dependencies

## Documentation

- CLAUDE.md pipeline table updated if pipelines changed
- CHANGELOG.md has an entry under `## Unreleased` (or dark-factory handles via ChangelogStep)
