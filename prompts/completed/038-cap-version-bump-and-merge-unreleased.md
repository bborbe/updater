---
status: completed
summary: Capped version bumps at MINOR in claude_analyzer.py prompts with defensive guards, added drain_unreleased_section to changelog.py, updated ChangelogStep to merge and drain pre-existing Unreleased entries, updated all tests and docs/version-bumping.md
container: updater-038-cap-version-bump-and-merge-unreleased
dark-factory-version: v0.128.1-3-gf1cfca3-dirty
created: "2026-04-19"
queued: "2026-04-19T20:40:01Z"
started: "2026-04-19T20:40:07Z"
completed: "2026-04-19T20:46:00Z"
---

<summary>
- Updater never bumps the major version — breaking changes are now capped at minor
- Claude's analysis prompts no longer list `major` as a valid version_bump option
- On every release, any pre-existing `## Unreleased` bullets are merged into the new version section instead of being left orphaned
- Final CHANGELOG after a release contains only the new version header with merged bullets — no leftover Unreleased section
- Tests cover the merge behavior and the removal of the major option
</summary>

<objective>
Fix two related bugs in the updater pipeline. (1) Prevent the updater from ever bumping the major version — cap all "breaking" changes at minor, keep dependency-only changes at patch. (2) Ensure the `ChangelogStep` merges any existing `## Unreleased` entries into the new release section and drains the Unreleased header, so running `updater all` after `updater --no-tag` no longer leaves orphaned bullets above the new version.
</objective>

<context>
Read `CLAUDE.md` for project conventions.
Read `docs/dod.md` for quality standards (no real subprocess/filesystem in tests; async step pattern).
Read `docs/version-bumping.md` — update this doc to reflect the new rules (MAJOR removed, breaking changes = MINOR).
Read `docs/architecture.md` for pipeline step contracts.

Source files to read before making changes:
- `src/updater/claude_analyzer.py` — function `analyze_changes_with_claude` (around line 254-371) and `analyze_unreleased_for_release` (around line 374-502)
- `src/updater/pipeline.py` — class `ChangelogStep` (around line 302-390) and class `ReleaseStep` (around line 518+)
- `src/updater/changelog.py` — functions `get_unreleased_entries`, `promote_unreleased_to_version`, `add_to_unreleased`, `update_changelog_with_suggestions`, `bump_version`
- `tests/test_claude_analyzer.py` — existing tests including `test_successful_analysis_major` (around line 110-125)
- `tests/test_changelog.py` — `test_bump_version_major` (around line 32-35)
- `tests/test_pipeline.py` — existing `ChangelogStep` tests for the merge test pattern

Motivation (real bug from 2026-04-19):
- Running `updater all` on the `agent` project bumped v0.44.1 → v1.0.0 because a generics refactor ("Generalize TaskRunner/ResultDeliverer with type parameters") was classified as breaking/major. User had to manually delete the tag and rebump to v0.45.0.
- The same run left a pre-existing `## Unreleased` bullet orphaned above the new v1.0.0 section because `ChangelogStep` only analyzes the git diff and ignores any existing `## Unreleased` entries.

User directives:
- "the updater should never ever change the major version"
- "go mod updates are only minor or patches updates"
- "on every release we should add the existing ## Unreleased sections"
</context>

<requirements>

## Fix 1: Cap version bumps at MINOR

1. In `src/updater/claude_analyzer.py`, update the prompt string inside `analyze_changes_with_claude` (the prompt literal starting at around line 275):
   - Replace the "Version Bump Decision Rules" block so it reads:
     ```
     Version Bump Decision Rules:
     1. **DEPENDENCY CHANGES = AT LEAST PATCH**
        - If go.mod, go.sum, package.json, pyproject.toml, or Dockerfile have version updates → PATCH minimum
        - Dependency updates are ALWAYS patch or minor — NEVER major

     2. **CODE CHANGES:**
        - **MINOR**: New features OR breaking API changes (backwards-compatible OR not)
        - **PATCH**: Bug fixes or small improvements

     3. **NONE**: ONLY when there are ZERO dependency updates AND ZERO code changes
        - Examples: .gitignore, README.md, Makefile, docs/

     CRITICAL: NEVER return "major". This tool caps version bumps at minor.
     If you detect breaking changes, return "minor" — never "major".
     ```
   - Update the JSON format line (currently line 301) to:
     ```
     {{"version_bump": "patch|minor|none", "changelog": ["bullet 1", "bullet 2"], "commit_message": "short message"}}
     ```
   - No `major` anywhere in the prompt.

2. In `src/updater/claude_analyzer.py`, add a defensive guard after `_extract_json_from_response` inside `analyze_changes_with_claude` (before building the return dict): if `analysis.get("version_bump") == "major"`, coerce it to `"minor"` and log a warning via `log_func` (e.g. `"⚠ Claude returned 'major' — capping to 'minor' (updater never bumps major)"`). This is belt-and-suspenders in case the LLM ignores the prompt.

3. In `src/updater/claude_analyzer.py`, update `analyze_unreleased_for_release` (around line 374-502):
   - Remove the entire `**MAJOR**` block from the Version Bump Rules in the prompt string.
   - Update the rules so `**MINOR**` explicitly covers both new features AND breaking API changes (append a line: "Breaking API changes are also MINOR — this tool never bumps major.").
   - Change the JSON format line from `"version_bump": "patch|minor|major"` to `"version_bump": "patch|minor"`.
   - Add the same defensive guard: if the parsed `version_bump == "major"`, coerce to `"minor"` with a warning log.

4. In `src/updater/changelog.py`, `bump_version` (line 129):
   - Keep the `"major"` branch functional (some callers may still pass it), but it should no longer be reachable from Claude analysis paths. Do NOT raise on `"major"` — keep backward compat for direct API callers. The cap is enforced upstream in `claude_analyzer.py`.
   - Do not modify `extract_current_version` or `promote_unreleased_to_version`.

## Fix 2: Merge existing Unreleased entries on release

5. In `src/updater/pipeline.py`, modify `ChangelogStep.run` (around line 309-390):
   - AFTER the `is_disabled(module_config, "llm-analysis")` branch and BEFORE the call to `analyze_changes_with_claude` (line 333), read existing unreleased entries:
     ```python
     from .changelog import get_unreleased_entries
     changelog_path = module_path / "CHANGELOG.md"
     existing_unreleased = get_unreleased_entries(changelog_path) if changelog_path.exists() else None
     ```
   - When `is_disabled("llm-analysis")` is true (the early branch where Claude is NOT called): do NOT drain the Unreleased section — leave existing bullets in place (no merge possible without Claude). Set `existing_unreleased = None` in that branch so the Case 4 drain logic skips.
   - When calling `analyze_changes_with_claude`, pass `existing_unreleased` as a new optional parameter (see requirement 6 for the signature change). Example:
     ```python
     analysis = await analyze_changes_with_claude(
         module_path,
         existing_unreleased=existing_unreleased,
         log_func=log_message,
     )
     ```
   - In "Case 4: Normal — update changelog and create version" (around line 386-390), AFTER calling `update_changelog_with_suggestions(...)`:
     - If `existing_unreleased` was non-empty, the `## Unreleased` header and its bullets must be removed from the CHANGELOG (they are already merged into the new version by Claude).
     - Call a new helper `drain_unreleased_section(changelog_path)` (see requirement 7) to strip the header + bullets.
   - Do NOT change Cases 1-3 (NO_GIT, --no-tag, missing CHANGELOG).

6. In `src/updater/claude_analyzer.py`, extend `analyze_changes_with_claude` signature:
   ```python
   async def analyze_changes_with_claude(
       module_path: Path,
       existing_unreleased: list[str] | None = None,
       log_func: Callable[..., None] = log_message,
   ) -> dict[str, Any]:
   ```
   - If `existing_unreleased` is non-empty, inject a block into the prompt after the "Steps:" section and before "Version Bump Decision Rules:":
     ```
     Existing ## Unreleased entries (MUST be merged into your output):
     <bullet 1>
     <bullet 2>
     ...

     Merge these with changes from the git diff. Deduplicate. Produce a single
     combined list of changelog bullets covering BOTH the existing unreleased
     entries AND the new git diff changes.
     ```
   - If `existing_unreleased` is None or empty, the prompt is unchanged (no block inserted).
   - Preserve backward-compatibility: existing callers that don't pass `existing_unreleased` still work.

7. In `src/updater/changelog.py`, add a new function `drain_unreleased_section`:
   ```python
   def drain_unreleased_section(changelog_path: Path) -> None:
       """Remove the ## Unreleased section (header + all bullets) from CHANGELOG.md.

       Removes any ## <Title> that's not a version (not matching ## vX.Y.Z), along
       with all bullet lines following it until the next ## section. Used after
       merging unreleased entries into a new version section.

       No-op if the file doesn't exist or there is no unreleased section.
       """
   ```
   - Implementation: walk lines, find the first non-version `## ` header, then remove that line and all subsequent lines until (exclusive) the next `## ` line. Collapse any resulting consecutive blank lines to a single blank line. Write back.
   - Mirror the parsing style used in `get_unreleased_entries` and `promote_unreleased_to_version` (use the same `version_pattern = re.compile(r"^##\s+v\d+\.\d+\.\d+")`).

8. Verify `ReleaseStep` (around line 518+ in `pipeline.py`) still works after these changes:
   - `ReleaseStep` already uses `promote_unreleased_to_version` (via `get_unreleased_entries` + `bump_version` + direct rewrite) — do NOT change its logic.
   - Confirm by reading the code path that `ReleaseStep` does not call `drain_unreleased_section` (it promotes the header instead of draining). No code changes needed here — just read to confirm.

## Fix 3: Update tests

9. In `tests/test_claude_analyzer.py`:
   - Rename `test_successful_analysis_major` (around line 110) to `test_major_coerced_to_minor`.
   - Change the mock response to have `"version_bump": "major"` (simulating Claude returning major despite the prompt).
   - Assert `result["version_bump"] == "minor"` (the defensive guard kicked in).
   - Add a new test `test_analyze_with_existing_unreleased`:
     - Call `analyze_changes_with_claude(module_path, existing_unreleased=["- old bullet"])` with a mocked `_run_claude`.
     - Assert that the prompt passed to `_run_claude` contains `"old bullet"` and contains the phrase "MUST be merged".
     - Assert the returned analysis uses the mocked Claude JSON response.
   - Add a new test `test_analyze_unreleased_for_release_major_coerced` for `analyze_unreleased_for_release`:
     - Mock Claude returning `{"version_bump": "major"}`.
     - Assert result is `{"version_bump": "minor"}`.

10. In `tests/test_changelog.py`:
    - Keep `test_bump_version_major` (bump_version still supports "major" for direct API callers).
    - Add tests for `drain_unreleased_section`:
      - `test_drain_unreleased_removes_header_and_bullets`: CHANGELOG has `## Unreleased\n\n- bullet 1\n- bullet 2\n\n## v1.2.3\n...`. After drain: `## v1.2.3\n...` (no Unreleased).
      - `test_drain_unreleased_no_section_noop`: CHANGELOG has only version sections → file unchanged.
      - `test_drain_unreleased_missing_file_noop`: non-existent path → no exception.
      - `test_drain_unreleased_custom_header`: header is `## Banana` (non-version) → also drained.

11. In `tests/test_pipeline.py`:
    - Add a new test `test_changelog_step_merges_existing_unreleased`:
      - Create a `tmp_path / "CHANGELOG.md"` with an existing `## Unreleased` section containing a bullet, plus a `## v1.0.0` section.
      - Mock `analyze_changes_with_claude` to return `{"version_bump": "minor", "changelog": ["merged bullet 1", "merged bullet 2"], "commit_message": "test"}`.
      - Run `ChangelogStep().run(module_path, context)`.
      - Assert that the mock was called with `existing_unreleased=["- old bullet"]` (or equivalent).
      - Assert the resulting CHANGELOG has a `## v1.1.0` section with the merged bullets and NO `## Unreleased` section.
    - Add a new test `test_changelog_step_no_unreleased_works_as_before`:
      - CHANGELOG has only `## v1.0.0` (no Unreleased).
      - Mock should be called with `existing_unreleased=None`.
      - Resulting CHANGELOG has new version, no regressions.
    - Add a new test `test_changelog_step_llm_disabled_preserves_unreleased`:
      - `module_config` with `llm-analysis` disabled.
      - CHANGELOG has `## Unreleased` with a bullet.
      - Run `ChangelogStep().run(...)`.
      - Assert `analyze_changes_with_claude` was NOT called.
      - Assert the resulting CHANGELOG still contains the `## Unreleased` section (not drained).
    - Follow existing test style: `@pytest.mark.asyncio`, `mocker` fixture, `tmp_path`, no real subprocess/filesystem calls outside `tmp_path`.

## Fix 4: Documentation

12. Update `docs/version-bumping.md`:
    - Remove the `**MAJOR**` row and any references to major bumps under "Code Changes".
    - Update the examples table: change `Remove exported function | MAJOR | Breaking change` to `Remove exported function | MINOR | Breaking change (updater caps at minor)`.
    - Add a note at the top: "**Note:** This tool never bumps the major version. Breaking changes are capped at MINOR."
    - Update the "CHANGELOG Behavior" section: `**Version bump (MAJOR/MINOR/PATCH)**` → `**Version bump (MINOR/PATCH)**`.

13. No changes required to `CLAUDE.md` pipeline table — the pipeline steps themselves are unchanged.

</requirements>

<constraints>
- Do NOT commit or push changes — dark-factory handles git
- Do NOT modify `ReleaseStep` logic — it already drains via `promote_unreleased_to_version`
- Do NOT break `bump_version("major", ...)` — keep backward compat for direct API callers; the cap is enforced upstream in the Claude analyzer
- Follow project DoD: `run_command` for all shell operations (no direct `subprocess`), Google-style docstrings, no `print()` (use `log_message` / `log_func`)
- Tests: use `mocker` fixture, `tmp_path` for filesystem, `@pytest.mark.asyncio` for async tests, NO real subprocess/network/filesystem outside `tmp_path`
- Preserve backward compatibility of `analyze_changes_with_claude` — new `existing_unreleased` parameter must be optional with default `None`
- Existing tests must still pass
</constraints>

<verification>
Run `make precommit` — must pass.

Manual spot-check:
1. In `src/updater/claude_analyzer.py`, confirm the string `"major"` appears nowhere in either prompt literal (the inline prompt inside `analyze_changes_with_claude` and the inline prompt inside `analyze_unreleased_for_release`). Quick check: `grep -n '"major"\|major\|MAJOR' src/updater/claude_analyzer.py` — only matches should be defensive-guard string literals (e.g. `if analysis.get("version_bump") == "major":`) and warning log strings, NOT prompt content.
2. Confirm the defensive guard in both functions coerces `"major"` → `"minor"` before returning.
3. Confirm `ChangelogStep.run` reads `get_unreleased_entries` before calling Claude and calls `drain_unreleased_section` after `update_changelog_with_suggestions` (only when `existing_unreleased` was non-empty).
4. Confirm `drain_unreleased_section` exists in `changelog.py` and handles missing file / missing section gracefully.
5. Confirm the llm-disabled branch in `ChangelogStep.run` does NOT drain `## Unreleased`.
</verification>
