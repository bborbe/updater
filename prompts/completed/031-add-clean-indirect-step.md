---
status: completed
summary: 'Added GoCleanIndirectStep to the updater fix pipeline: clean_indirect_deps function in go_updater.py, GoCleanIndirectStep in pipeline.py, wired between GoExcludesStep and OsvFixStep in process_single_go_fix_module, with 7 tests in test_clean_indirect.py and updated CLAUDE.md pipeline table'
container: updater-031-add-clean-indirect-step
dark-factory-version: v0.80.0-1-g2b37ac1
created: "2026-04-01T09:08:52Z"
queued: "2026-04-01T09:13:34Z"
started: "2026-04-01T09:13:35Z"
completed: "2026-04-01T09:15:49Z"
---
<summary>
- New `GoCleanIndirectStep` removes all `// indirect` lines from go.mod require blocks
- `go mod tidy` re-adds only actually needed indirect deps, cleaning up stale entries
- Step added to `fix` pipeline only, between GoExcludesStep and OsvFixStep
- Stale indirect dependencies no longer accumulate in go.mod files processed by `updater fix`
- Existing tests unaffected, new tests cover the step
</summary>

<objective>
Add a pipeline step that strips stale indirect dependencies from go.mod by removing all `// indirect` require lines and running `go mod tidy` to regenerate only the needed ones.
</objective>

<context>
Read CLAUDE.md for project conventions.
Read src/updater/pipeline.py — understand Step base class and existing steps (GoExcludesStep, OsvFixStep pattern).
Read src/updater/cli.py — find all pipelines that process Go modules:
  - `process_single_go_module` (full update pipeline, line ~120)
  - `process_single_go_fix_module` (fix-only pipeline, line ~204)
Read src/updater/go_updater.py — `go mod tidy` is already called after dep updates and OSV fixes.
Read docs/architecture.md — understand pipeline/step design.
Read tests/test_gomod_excludes.py — understand test patterns for go.mod manipulation steps.

The step should:
1. Parse indirect deps using `go list`
2. Remove each via `go mod edit -droprequire` (no direct file editing per CLAUDE.md)
3. Run `go mod tidy` to re-resolve indirect deps
4. Report whether any lines were removed
</context>

<requirements>
1. Add `clean_indirect_deps(module_path: Path, log_func: Callable[..., None] = log_message) -> bool` function in src/updater/go_updater.py:
   - Parse indirect deps from go.mod using `go list -m -f '{{if .Indirect}}{{.Path}}@{{.Version}}{{end}}' all`
   - For each indirect dep, run `go mod edit -droprequire <module>` to remove it
   - Run `go mod tidy` to re-add actually needed indirect deps
   - Return True if any indirect deps were removed, False otherwise
   - Log how many indirect deps were removed
   - If no go.mod exists, log warning and return False
   - Note: uses `go mod edit` per CLAUDE.md convention — no direct file editing of go.mod

2. Add `GoCleanIndirectStep` in src/updater/pipeline.py:
   - Follow the same pattern as GoExcludesStep
   - Call `clean_indirect_deps` from go_updater
   - Log phase as "Phase 1d: Clean Indirect Dependencies"
   - Track `updates_made` in context like other steps

3. Wire into fix pipeline only in src/updater/cli.py:
   - In `process_single_go_fix_module`: insert GoCleanIndirectStep between GoExcludesStep and OsvFixStep
   - Import GoCleanIndirectStep in the function
   - Do NOT add to `process_single_go_module` — full update already handles indirect deps via `go mod tidy` after dep updates

4. Add tests in tests/test_clean_indirect.py for `clean_indirect_deps`:
   - go.mod with indirect deps → they are removed, go mod tidy is called
   - go.mod with no indirect deps → returns False, file unchanged
   - No go.mod → returns False with warning
   - go.mod with mixed direct and indirect → only indirect lines removed

5. Update CLAUDE.md pipeline table to show GoCleanIndirect step in the fix pipeline only.
</requirements>

<constraints>
- Do NOT commit — dark-factory handles git
- Do NOT modify any existing step logic
- Do NOT change how `go mod tidy` works in existing code (go_updater.py)
- Only remove lines ending with `// indirect` inside require blocks — never touch direct deps
- The step must be idempotent — running twice produces same result
</constraints>

<verification>
Run `make precommit` — must pass with exit code 0.
</verification>
