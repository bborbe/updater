---
status: completed
summary: Added 14 tests for add_to_unreleased() and update_changelog_with_suggestions() raising changelog.py coverage from 49% to 100%, and updated CHANGELOG.md with an Unreleased section.
container: updater-020-test-coverage-changelog
dark-factory-version: v0.30.17-dirty
created: "2026-03-09T21:19:37Z"
queued: "2026-03-09T21:19:37Z"
started: "2026-03-09T21:29:06Z"
completed: "2026-03-09T21:30:24Z"
---

<summary>
- Adding changes to the Unreleased section of a CHANGELOG is tested for all cases
- Updating CHANGELOG with a versioned release section is tested end-to-end
- Missing CHANGELOG files are handled gracefully in both workflows
- File content after write is verified against expected format
- Coverage target: changelog.py goes from 49% to at least 80%
</summary>

<objective>
Coverage for `changelog.py` rises from 49% to at least 80%, with the two main write functions exercised by automated tests. This ensures CHANGELOG file modifications produce correct output and regressions are caught by CI.
</objective>

<context>
Read CLAUDE.md for project conventions.
Read `src/updater/changelog.py` — focus on uncovered functions: `add_to_unreleased()` (line 161) and `update_changelog_with_suggestions()` (line 252).
Read `tests/test_changelog.py` — understand existing patterns. Tests use `tmp_path` fixture for file operations.

`add_to_unreleased()` takes `(module_path, analysis, log_func)` and adds bullets under `## Unreleased`.
`update_changelog_with_suggestions()` takes `(module_path, analysis, log_func)` and inserts a new versioned section.
</context>

<requirements>
1. Add tests for `add_to_unreleased()`:
   - No CHANGELOG.md exists → logs warning, returns
   - CHANGELOG.md with existing `## Unreleased` section → appends bullets
   - CHANGELOG.md without `## Unreleased` → creates section before first version header
   - CHANGELOG.md with no version headers → creates section at end of preamble
   - Verify file content after write matches expected format

2. Add tests for `update_changelog_with_suggestions()`:
   - No CHANGELOG.md exists → returns None
   - Normal version bump (patch, minor) → inserts new version section, returns version string
   - Verify correct version calculation and file content

3. Use `tmp_path` for all file operations — create real CHANGELOG.md files in temp dirs

4. Target: raise `changelog.py` coverage from 49% to at least 80%
</requirements>

<constraints>
- Do NOT modify source code — only add/modify tests
- Do NOT commit — dark-factory handles git
- Existing tests must still pass
</constraints>

<verification>
Run `make precommit` — must pass with exit code 0.
Run `uv run --with pytest-cov pytest --cov=updater.changelog --cov-report=term-missing tests/test_changelog.py` — coverage should be >= 80%.
</verification>
