---
status: completed
summary: Removed anthropic-sdk-go v1.26.0 pin from STANDARD_REPLACES, added it to OBSOLETE_REPLACES, updated five tests, added new test for obsolete-replace cleanup, and added CHANGELOG Unreleased entry.
container: updater-039-drop-anthropic-sdk-replace
dark-factory-version: v0.135.19-1-gc08c946
created: "2026-04-28T14:53:22Z"
queued: "2026-04-28T14:53:22Z"
started: "2026-04-28T14:53:40Z"
completed: "2026-04-28T14:55:41Z"
---

<summary>
- Updater no longer pins `anthropic-sdk-go` to v1.26.0 in projects it updates
- The pin now actively breaks builds because newer gosec releases require constants only present in newer SDK versions
- Existing pinned projects get the stale replace stripped automatically on next update run
- Standard replace list shrinks by one entry; obsolete replace list grows by one entry
- All test fixtures and assertions stay green after the change
</summary>

<objective>
Stop pinning `github.com/anthropics/anthropic-sdk-go` to v1.26.0 via `STANDARD_REPLACES` and start treating that pin as obsolete so updater actively removes it from any project that still has it.
</objective>

<context>
Read CLAUDE.md for project conventions.
Read `docs/dod.md` for the Definition of Done.
Read `src/updater/gomod_excludes.py` — find `STANDARD_REPLACES` and `OBSOLETE_REPLACES`.
Read `tests/test_gomod_excludes.py` — find the four tests that reference `anthropic-sdk-go`:
  `test_apply_excludes_to_empty_gomod`, `test_apply_excludes_idempotent`,
  `test_apply_excludes_does_not_call_go_mod_download_when_no_changes`,
  and any helper assertion at line ~156.

Background (do not include in code comments): the original pin was added because gosec v2.25.0
referenced a constant removed in `anthropic-sdk-go` v1.27.0. Newer gosec releases (v2.26.1+) now
reference constants that only exist in v1.27.0+, so the v1.26.0 pin breaks the build. gosec keeps
moving the model constant — pinning is the wrong strategy. Drop the pin and let the SDK update
naturally; mark it obsolete so existing projects get cleaned up.
</context>

<requirements>
1. In `src/updater/gomod_excludes.py`, remove this entry from the `STANDARD_REPLACES` list (and the comment line directly above it that begins with `# gosec v2.25.0 autofix uses ModelClaude3_7SonnetLatest removed in v1.27.0`):
   ```
   ("github.com/anthropics/anthropic-sdk-go", "github.com/anthropics/anthropic-sdk-go v1.26.0"),
   ```
   The remaining four entries (`cellbuf`, `go-header`, `go-diskfs`, `ginkgolinter/types`) stay unchanged and in their current order.

2. In `src/updater/gomod_excludes.py`, add `"github.com/anthropics/anthropic-sdk-go"` to the `OBSOLETE_REPLACES` list. Keep the list sorted alphabetically. The result should be:
   ```python
   OBSOLETE_REPLACES = [
       "github.com/anthropics/anthropic-sdk-go",
       "k8s.io/kube-openapi",
   ]
   ```

3. In `tests/test_gomod_excludes.py`, update `test_apply_excludes_to_empty_gomod` (around line 143):
   - Change `assert mock_run.call_count == 6  # 5 replace calls + 1 go mod download` to `assert mock_run.call_count == 5  # 4 replace calls + 1 go mod download`
   - Remove ONLY the line `assert any("anthropic-sdk-go" in c for c in calls)` (around line 156). Leave the sibling assertions for `go-header`, `go-diskfs`, `ginkgolinter`, and `go mod download` untouched.

4. In `tests/test_gomod_excludes.py`, update `test_apply_excludes_idempotent`:
   - Remove the `github.com/anthropics/anthropic-sdk-go => github.com/anthropics/anthropic-sdk-go v1.26.0` line from the `replace ( ... )` block in the test fixture so the fixture only contains the four current standard replaces.
   - The existing assertions (`result is False`, `mock_run.call_count == 0`) remain unchanged.

5. In `tests/test_gomod_excludes.py`, update `test_apply_excludes_does_not_call_go_mod_download_when_no_changes` (around line 272):
   - Remove the `github.com/anthropics/anthropic-sdk-go => github.com/anthropics/anthropic-sdk-go v1.26.0` line from the `replace ( ... )` block in that test fixture as well.
   - Existing assertions remain unchanged.

6. In `tests/test_gomod_excludes.py`, update `test_apply_removes_old_non_k8s_excludes` (around line 189):
   - Change `assert mock_run.call_count == 15  # 9 dropexclude + 5 replace calls + 1 go mod download` to `assert mock_run.call_count == 14  # 9 dropexclude + 4 replace calls + 1 go mod download`. The fixture itself does not need to change.

7. In `tests/test_gomod_excludes.py`, add a new test `test_apply_excludes_removes_obsolete_anthropic_replace` that verifies updater actively drops a stale `anthropic-sdk-go` replace when present. Pattern after `test_apply_excludes_removes_obsolete_k8s_entries`:
   - go.mod fixture contains a single replace block with `github.com/anthropics/anthropic-sdk-go => github.com/anthropics/anthropic-sdk-go v1.26.0` and nothing else
   - Mock `run_command`, call `apply_gomod_excludes_and_replaces(tmp_path)`
   - Assert `result is True`
   - Assert at least one call contains both `dropreplace` and `anthropic-sdk-go`
   - Assert standard replaces are still added (e.g. `cellbuf`, `go-header`)

8. Add a `## Unreleased` section to `CHANGELOG.md`, placed below the `# Changelog` top-level header and above the existing top version section (currently `## v0.23.0`). One bullet under it, prefix with `fix:`, describing the change in user-facing terms (drop the anthropic-sdk-go replace pin, mark as obsolete so existing projects get cleaned up).

9. Run `make precommit` and resolve any failures.
</requirements>

<constraints>
- Do NOT commit — dark-factory handles git
- Do NOT change any other entries in `STANDARD_REPLACES`, `STANDARD_EXCLUDES`, `OBSOLETE_EXCLUDES_PREFIXES`, or unrelated tests
- Do NOT bump versions or edit any other CHANGELOG entries
- Keep the existing comment style in `gomod_excludes.py` (one-line comment immediately above each replace tuple) for the remaining entries
- Do NOT add explanatory comments about the SDK history into the source — the changelog entry is the user-facing record
</constraints>

<verification>
Run `make precommit` — must pass with exit code 0.
</verification>
