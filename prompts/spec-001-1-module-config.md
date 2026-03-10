---
spec: ["001"]
status: created
created: "2026-03-10T09:00:00Z"
---

<summary>
- Projects can place a `.updater.yaml` in their module root to control updater behavior
- The config file supports a `disable` list to skip specific update phases
- Valid disable values: python-version, golang-version, alpine-version, go-dependencies, llm-analysis
- Missing or empty config file means all phases run (current default behavior)
- Malformed config or unknown disable values produce warnings but don't block updates
- Disabled phases are logged at the start of module processing
- Existing behavior for projects without config is completely unchanged
</summary>

<objective>
Add per-project `.updater.yaml` config file support so projects can disable specific update phases (e.g. skip Python version updates when latest Python breaks their dependencies). The config is loaded once per module at pipeline start and checked by each relevant step.
</objective>

<context>
Read CLAUDE.md for project conventions.
Read `src/updater/pipeline.py` — this contains all pipeline Step classes. Each step's `run()` method needs to check the config.
Read `src/updater/version_updater.py` — contains `update_versions()` which updates Go and Alpine versions.
Read `src/updater/python_version_updater.py` — contains `update_python_versions()`.
Read `src/updater/claude_analyzer.py` — contains `analyze_changes_with_claude()`.
Read `src/updater/config.py` — global config constants.
Read existing tests in `tests/` to understand patterns (pytest, unittest.mock, AsyncMock).
</context>

<requirements>
1. Create `src/updater/module_config.py` with:
   - A `ModuleConfig` dataclass with a `disable: list[str]` field (default empty list)
   - A `VALID_DISABLE_VALUES` set: `{"python-version", "golang-version", "alpine-version", "go-dependencies", "llm-analysis"}`
   - A `load_module_config(module_path: Path) -> ModuleConfig` function that:
     - Reads `.updater.yaml` from `module_path`
     - Returns default `ModuleConfig()` if file missing or empty
     - Uses `yaml.safe_load` to parse
     - Warns (via `log_message`) and returns defaults if YAML is malformed
     - Warns for unknown values in `disable` list but still processes known values
     - Warns and returns defaults if `disable` is not a list (e.g. scalar string)
     - Rejects files > 64KB with a warning
   - A `is_disabled(config: ModuleConfig, phase: str) -> bool` helper

2. Modify `src/updater/pipeline.py`:
   - Import `load_module_config` and `is_disabled` from `module_config`
   - In `Pipeline.run()`, load config at the start: `module_config = load_module_config(module_path)` and store it in `context["module_config"]`
   - Log active disables if any: `→ Config: disable=[python-version, golang-version]`

3. Add disable checks to these Step classes in `pipeline.py`:
   - `GoVersionUpdateStep.run()`: if `is_disabled(context["module_config"], "golang-version")`, log skip and return `StepResult(StepStatus.SKIP)`
   - `GoDepUpdateStep.run()`: check `"go-dependencies"`
   - `PythonVersionUpdateStep.run()`: check `"python-version"`
   - `PythonDepUpdateStep.run()`: check `"python-version"` (Python deps are tied to Python version phase)
   - `ChangelogStep.run()`: check `"llm-analysis"` — if disabled, set `context["analysis"] = {"version_bump": "patch", "changelog": ["update dependencies"], "commit_message": "update dependencies"}` and skip Claude call

4. Modify `GoVersionUpdateStep` to also check `"alpine-version"`:
   - Currently `update_versions()` updates both Go and Alpine in one call
   - If only `alpine-version` is disabled but not `golang-version`: still call `update_versions()` but this is acceptable for v1 (the function updates both together)
   - If `golang-version` is disabled: skip the entire `GoVersionUpdateStep` (which skips both Go and Alpine). Document this as a known limitation — Alpine is coupled to Go version step.
   - Alternative: if `alpine-version` is disabled independently, accept that it skips with Go for now.

5. Create `tests/test_module_config.py` with tests for:
   - `load_module_config` with missing file → default config
   - `load_module_config` with empty file → default config
   - `load_module_config` with valid disable list
   - `load_module_config` with malformed YAML → warning + defaults
   - `load_module_config` with unknown disable value → warning + known values kept
   - `load_module_config` with scalar disable → warning + defaults
   - `load_module_config` with file > 64KB → warning + defaults
   - `is_disabled` helper with enabled and disabled phases
   - Pipeline integration: disabled step returns SKIP

6. In `Pipeline.run()`, handle SKIP from config-disabled steps the same as `GoDepSkipStep` — continue to next step, don't abort pipeline.
</requirements>

<constraints>
- Do NOT commit — dark-factory handles git
- Existing tests must still pass unchanged
- No new Python package dependencies (pyyaml is already available)
- Projects without `.updater.yaml` must produce identical behavior to current
- Invalid config values produce warnings, not errors
- The `disable` value must be a YAML list — scalar values are rejected with a warning
- Use `yaml.safe_load` (never `yaml.load`)
</constraints>

<verification>
Run `make precommit` — must pass with exit code 0.
</verification>
