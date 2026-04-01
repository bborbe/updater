---
status: completed
summary: Reordered pipeline so GoCleanIndirectStep runs before GoExcludesStep, and added go mod download after apply_gomod_excludes_and_replaces to keep go.sum in sync
container: updater-032-fix-excludes-breaks-clean-indirect
dark-factory-version: v0.85.0
created: "2026-04-01T13:23:28Z"
queued: "2026-04-01T13:23:28Z"
started: "2026-04-01T13:23:38Z"
completed: "2026-04-01T13:25:20Z"
---
<summary>
- The excludes step adds replace directives but leaves go.sum out of sync
- The clean-indirect step fails because it reads stale go.sum entries
- Fix: reorder pipeline so clean-indirect runs before excludes
- Add a defensive go.sum sync after any go.mod modifications
- New tests cover both the sync and no-sync code paths
</summary>

<objective>
Ensure GoExcludesStep leaves go.sum in a consistent state so downstream steps like GoCleanIndirectStep do not fail on stale go.sum entries. Currently `updater fix` and `updater --yes fix` fail on any repo that needs a new replace directive.
</objective>

<context>
Read CLAUDE.md for project conventions.
Read src/updater/pipeline.py — GoExcludesStep (line ~108) and GoCleanIndirectStep (line ~142).
Read src/updater/gomod_excludes.py — `apply_gomod_excludes_and_replaces()` (line ~130) adds replaces via `go mod edit -replace` but never runs `go mod download`.
Read src/updater/go_updater.py — `clean_indirect_deps()` (line ~162) runs `go list -m -f '{{if .Indirect}}{{.Path}}@{{.Version}}{{end}}' all` which fails when go.sum is stale.
Read src/updater/cli.py — find ALL pipelines that use both steps. Known location:
  - `process_single_go_fix_module()` (line ~155), pipeline constructed at lines 204-217
  - Search for any other pipeline functions that use both GoExcludesStep and GoCleanIndirectStep
Read tests/test_gomod_excludes.py — understand existing test patterns for mocking `run_command`.

**Bug reproduction:**
1. A module has `github.com/denis-tingaikin/go-header v1.0.0` in go.sum
2. GoExcludesStep adds `replace github.com/denis-tingaikin/go-header => github.com/denis-tingaikin/go-header v0.5.0`
3. GoCleanIndirectStep runs `go list -m -f '...' all` → fails: "missing go.sum entry for go.mod file"
4. Retry loops 3x with same failure because go.sum is never updated
</context>

<requirements>
1. In src/updater/cli.py — swap step order in ALL pipelines that have both steps:
   - Change `GoExcludesStep()` → `GoCleanIndirectStep()` → ... to `GoCleanIndirectStep()` → `GoExcludesStep()` → ...
   - This way `go list -m -f '...' all` runs on unmodified go.sum (before replaces are added)

2. In `apply_gomod_excludes_and_replaces()` in src/updater/gomod_excludes.py:
   - After ALL modifications (excludes + replaces + obsolete removal), if `changes_made` is True, run `go mod download` to sync go.sum
   - Use `run_command("go mod download", cwd=module_path, quiet=True, log_func=log_func)`
   - This is defensive: ensures go.sum is always consistent after go.mod changes

3. Add/update tests:
   - Test that verifies `go mod download` is called when changes are made in `apply_gomod_excludes_and_replaces`
   - Test that verifies `go mod download` is NOT called when no changes are made
   - Follow existing test patterns from tests/test_gomod_excludes.py

4. Run `make precommit` — must pass.
</requirements>

<constraints>
- Do NOT commit or push changes — only modify code and tests
- Use `run_command()` for all shell operations (no subprocess.run or os.system)
- Do NOT edit go.mod files directly — always use `go mod edit` commands
- Follow existing code style and import patterns in gomod_excludes.py
</constraints>

<verification>
- `make precommit` passes
- Pipeline order in cli.py shows GoCleanIndirectStep before GoExcludesStep
- `apply_gomod_excludes_and_replaces` calls `go mod download` when changes_made is True
- New tests cover both cases (changes made / no changes)
- Existing tests still pass
</verification>
