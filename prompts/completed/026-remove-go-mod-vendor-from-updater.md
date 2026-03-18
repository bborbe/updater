---
status: completed
summary: Removed go mod vendor calls from update_go_dependencies and fix_osv_vulnerabilities in go_updater.py; vendor generation is now left to make precommit
container: updater-026-remove-go-mod-vendor-from-updater
dark-factory-version: v0.57.5
created: "2026-03-18T10:57:35Z"
queued: "2026-03-18T10:57:35Z"
started: "2026-03-18T10:57:37Z"
completed: "2026-03-18T10:59:03Z"
---
<summary>
- The updater no longer runs `go mod vendor` after dependency updates
- The updater no longer runs `go mod vendor` after OSV vulnerability fixes
- Projects that need vendor get it from `make precommit` which already runs afterward
- Projects using `-mod=mod` no longer suffer unnecessary heavy I/O from vendor generation
- Both `-mod=mod` and `-mod=vendor` projects continue to work correctly
</summary>

<objective>
Remove `go mod vendor` calls from the updater. Each project's `make precommit` already handles vendor generation when needed. The updater running vendor is redundant and causes unnecessary heavy I/O across many projects.
</objective>

<context>
Read CLAUDE.md for project conventions.
Read `src/updater/go_updater.py` — this is the only file that needs changes.

The updater pipeline runs in this order:
1. Phase 1c: `update_go_dependencies()` — runs `go get -u`, then `go mod tidy`, then `go mod vendor`
2. Phase 1d: `fix_osv_vulnerabilities()` — runs `go get -u`, then `go mod tidy`, then `go mod vendor`
3. Phase 2: `run_precommit()` — runs `make precommit` which already handles vendor if the project needs it

The `go mod vendor` in phases 1c and 1d is redundant because phase 2 always follows and handles vendor per-project.
</context>

<requirements>
1. In `src/updater/go_updater.py`, remove the `go mod vendor` call at line 90-91 (in `update_go_dependencies()` after `go mod tidy`)
2. In `src/updater/go_updater.py`, remove the `go mod vendor` call at line 160 (in `fix_osv_vulnerabilities()` after `go mod tidy`)
3. Remove the associated log lines for these vendor commands
4. Update tests if any assert on `go mod vendor` being called
</requirements>

<constraints>
- Do NOT commit — dark-factory handles git
- Existing tests must still pass
- Only modify `src/updater/go_updater.py` and test files if needed
- Keep `go mod tidy` — only remove `go mod vendor`
</constraints>

<verification>
Run `make precommit` -- must pass.
</verification>
