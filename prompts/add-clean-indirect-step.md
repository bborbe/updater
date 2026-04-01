---
status: draft
---
<summary>
- New `GoCleanIndirectStep` removes all `// indirect` lines from go.mod require blocks
- `go mod tidy` re-adds only actually needed indirect deps, cleaning up stale entries
- Step added to `fix` pipeline only, between GoExcludesStep and OsvFixStep
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
1. Read go.mod
2. Remove all lines containing `// indirect` from require blocks
3. Write go.mod back
4. Run `go mod tidy` to re-resolve indirect deps
5. Report whether any lines were removed
</context>

<requirements>
1. Add `clean_indirect_deps` function in src/updater/go_updater.py:
   - Read go.mod content
   - Remove lines in require blocks that end with `// indirect`
   - Write the cleaned go.mod
   - Run `go mod tidy` to re-add actually needed indirect deps
   - Return True if any indirect lines were removed, False otherwise
   - Log how many indirect deps were removed
   - If no go.mod exists, log warning and return False

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

5. Update CLAUDE.md pipeline table to show GoCleanIndirect step in both pipelines.
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
