---
status: approved
created: "2026-03-09T21:19:37Z"
queued: "2026-03-09T21:19:37Z"
---

<summary>
- Golang and Alpine version fetching are tested with mocked HTTP responses
- JSON and YAML parsing errors are handled gracefully in tests
- Network timeout and HTTP error scenarios are covered
- The orchestrating update function that calls all sub-updaters is tested
- Coverage target: version_updater.py goes from 73% to at least 85%
</summary>

<objective>
Coverage for `version_updater.py` rises from 73% to at least 85%, with HTTP fetch functions and the orchestrating `update_versions()` exercised by automated tests. This ensures version detection and file updates work correctly and regressions are caught by CI.
</objective>

<context>
Read CLAUDE.md for project conventions.
Read `src/updater/version_updater.py` — focus on uncovered functions: `get_latest_golang_version()` (line 14), `get_latest_alpine_version()` (line 40), `update_versions()` (line 249).
Read `tests/test_version_updater.py` — understand existing patterns.

The module uses `httpx.get()` for HTTP calls. Mock `httpx.get` to return controlled responses. Use `unittest.mock.patch` to mock the HTTP calls.
</context>

<requirements>
1. Add tests for the HTTP fetch paths:
   - `get_latest_golang_version()`: mock httpx.get with valid JSON response `[{"version": "go1.23.5"}]`, verify returns `"1.23.5"`
   - `get_latest_alpine_version()`: mock response with YAML containing `[{"flavor": "alpine-minirootfs", "version": "3.20.3"}]`
   - HTTP error → returns None
   - Timeout → returns None
   - JSON/YAML parse error → returns None

2. Add tests for `update_versions()`:
   - Both golang and alpine fetched successfully → calls sub-updaters, returns True if any updated
   - Fetch returns None → logs warning, continues with other versions
   - No updates needed → returns False

3. Mock `httpx.get` — never make real HTTP calls

4. Target: raise `version_updater.py` coverage from 73% to at least 85%
</requirements>

<constraints>
- Do NOT modify source code — only add/modify tests
- Do NOT commit — dark-factory handles git
- Existing tests must still pass
</constraints>

<verification>
Run `make precommit` — must pass with exit code 0.
Run `uv run --with pytest-cov pytest --cov=updater.version_updater --cov-report=term-missing tests/test_version_updater.py` — coverage should be >= 85%.
</verification>
