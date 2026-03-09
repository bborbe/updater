---
status: created
---

<summary>
- Python version fetching from the Python.org API is tested with mocked HTTP
- pyproject.toml version extraction and update are covered
- HTTP error and timeout scenarios are handled in tests
- Version comparison detects when updates are needed vs already current
- Coverage target: python_version_updater.py goes from 76% to at least 85%
</summary>

<objective>
Coverage for `python_version_updater.py` rises from 76% to at least 85%, with the HTTP fetch path and the orchestrating `update_python_versions()` exercised by automated tests. This ensures version detection and error handling work correctly and regressions are caught by CI.
</objective>

<context>
Read CLAUDE.md for project conventions.
Read `src/updater/python_version_updater.py` — focus on uncovered lines: 21-51 (HTTP fetch and version parsing), 194-195.
Read `tests/test_python_version_updater.py` — understand existing patterns.

The module uses `httpx.get()` to fetch from `https://www.python.org/api/v2/downloads/release/`. Mock `httpx.get` using `unittest.mock.patch` to return controlled responses. Use `unittest.mock.MagicMock` for the response object with `.json()`, `.raise_for_status()`, etc.
</context>

<requirements>
1. Add tests for `get_latest_python_version()`:
   - Valid API response → returns correct version string
   - HTTP error → returns None gracefully
   - Timeout → returns None gracefully
   - Malformed JSON → returns None gracefully

2. Add tests for any uncovered update paths (lines 194-195)

3. Mock `httpx.get` — never make real HTTP calls

4. Target: raise `python_version_updater.py` coverage from 76% to at least 85%
</requirements>

<constraints>
- Do NOT modify source code — only add/modify tests
- Do NOT commit — dark-factory handles git
- Existing tests must still pass
</constraints>

<verification>
Run `make precommit` — must pass with exit code 0.
Run `uv run --with pytest-cov pytest --cov=updater.python_version_updater --cov-report=term-missing tests/test_python_version_updater.py` — coverage should be >= 85%.
</verification>
