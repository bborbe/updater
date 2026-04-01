---
status: verifying
approved: "2026-04-01T07:32:51Z"
prompted: "2026-04-01T07:34:50Z"
verifying: "2026-04-01T07:57:14Z"
branch: dark-factory/subcommand-cli-refactor
---

## Summary

- Replace 8 individual CLI entry points with a single `updater` binary using subcommands
- `updater go`, `updater all`, `updater python`, etc. replace `update-go`, `update-deps`, `update-python`
- Single entry point in `pyproject.toml` instead of 8 separate scripts
- Shared/global flags (e.g. `--yes`, `--check-command`) defined once on the root parser

## Problem

The updater exposes 8 separate commands (`update-go`, `update-deps`, `update-go-only`, `update-go-with-deps`, `update-python`, `update-docker`, `release-only`, `fix-only`). Each has its own argument parser with duplicated flag definitions (`--yes`, `--check-command`, etc.). Adding a new global flag requires touching all parsers. Discovery is poor — users must know all command names upfront.

## Goal

A single `updater <subcommand>` binary where subcommands map 1:1 to the current commands, shared flags are defined once on the root parser, and `pyproject.toml` has one entry point.

## Assumptions

- No CI scripts, Makefiles, or external projects invoke the old `update-*` / `release-only` / `fix-only` command names directly — they are only used interactively
- argparse subparsers support inheriting parent parser flags
- `uv` / `pyproject.toml` entry points work with a single binary that dispatches subcommands

## Non-goals

- Changing pipeline logic, step order, or behavior of any command
- Renaming or removing any existing functionality
- Backwards-compatible aliases for old `update-*` command names

## Desired Behavior

1. `updater go` runs the same pipeline as current `update-go`
2. `updater all` runs the same pipeline as current `update-deps` / `update-all`
3. `updater go-only` runs the same pipeline as current `update-go-only`
4. `updater go-with-deps` runs the same pipeline as current `update-go-with-deps`
5. `updater python` runs the same pipeline as current `update-python`
6. `updater docker` runs the same pipeline as current `update-docker`
7. `updater release` runs the same pipeline as current `release-only`
8. `updater fix` runs the same pipeline as current `fix-only`
9. Global flags (`--yes`, `--check-command`) defined once on root parser, apply to all subcommands

## Constraints

- All existing pipeline logic and step order must remain unchanged (see `docs/architecture.md` for pipeline/step design)
- All existing tests must still pass
- `--yes`, `--check-command`, and any future global flags must behave identically to current per-parser flags

## Failure Modes

| Trigger | Expected behavior | Recovery |
|---------|-------------------|----------|
| Unknown subcommand | Print usage with subcommand list, exit 1 | User corrects subcommand |
| No subcommand given | Print usage, exit 1 | User provides subcommand |
| Global flag after subcommand | Argparse handles naturally (standard behavior) | N/A |
| Old `update-*` command invoked after migration | Command not found (removed from pyproject.toml) | User switches to `updater <subcommand>` |
| `updater --help` | Lists all subcommands with descriptions | N/A |
| `updater go --help` | Shows subcommand-specific flags and description | N/A |

## Acceptance Criteria

- [ ] `updater go --yes` behaves identically to current `update-go --yes`
- [ ] `updater all --check-command "make ensure test"` works
- [ ] `updater` with no subcommand prints usage and exits 1
- [ ] `updater unknown` exits 1 with clear error
- [ ] `pyproject.toml` has single `updater` entry point
- [ ] All 8 subcommands produce identical behavior to their predecessors
- [ ] All existing tests pass

## Verification

```
make precommit
uv run pytest
uv run updater --help
uv run updater go --help
```

## Do-Nothing Option

Keep the current multi-command approach. It works, but every new global flag requires N parser changes. Acceptable short-term, painful as flags accumulate.
