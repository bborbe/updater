# Infra-Tier Targets

The four infra-tier files the generic updater can't touch — each has a unique file + constant + repo.
These are the frozen targets for the infra-tier special-case handlers (spec
`specs/infra-tier-special-case-handlers.md`).

| Target | Repo | File | Constant | Current value (2026-08-22) |
|---|---|---|---|---|
| claude-yolo | `bborbe/claude-yolo` | `Dockerfile` | `ARG GO_VERSION=X.Y.Z` | `ARG GO_VERSION=1.27.0` |
| dark-factory | `bborbe/dark-factory` | `pkg/const.go` | `DefaultContainerImage = "docker.io/bborbe/claude-yolo:vA.B.C"` (tracks claude-yolo's release tag, NOT the Go version directly) | `DefaultContainerImage = "docker.io/bborbe/claude-yolo:v0.15.1"` |
| BundleWrap | BundleWrap repo | `bundles/golang/items.py` | `default_golang_version = 'X.Y.Z'` | `default_golang_version = '1.27.0'` |
| trading monorepo | `bborbe/trading` | no central constant — version lives across every module's `go.mod`/`Dockerfile`/workflow | `make updategoversion` → `update-go-version.sh` (bumps all to latest from go.dev) | (no `Makefile.folder go X.Y.Z` line exists — verified 2026-08-22) |

## claude-yolo release flow

- On merge of a handler PR, `make build-multiarch` auto-publishes the new claude-yolo tag to
  docker.io (already-configured GitHub Actions workflow).
- dark-factory's `DefaultContainerImage` must be bumped to the **new claude-yolo tag** after that
  publish — resolved from claude-yolo's latest GitHub release, not the Go version directly.

## trading monorepo — the real mechanism (verified 2026-08-22)

The trading monorepo (`bborbe/trading`) has **no central Go version constant** —
`Makefile.folder` never contained a `go X.Y.Z` line (confirmed via git history).
The canonical mechanism is `make updategoversion`, which runs
`update-go-version.sh` (in `~/Documents/workspaces/scripts/`) per module. That
script bumps **all** of these to the latest Go release from go.dev (excluding
`vendor/`):

1. Every `go.mod` `go X.Y.Z` directive + `toolchain goX.Y.Z` directive
2. Every Dockerfile `FROM golang:X.Y.Z`
3. Every `.github/workflows/*.yml` `go-version: 'X.Y.Z'` pin

The trading handler replicates exactly these sed patterns, driven by an explicit
`--go-version` target instead of a runtime fetch from go.dev. Real run: feature
worktree from `master` → apply the walk → commit → push → PR.

## Handler module convention

Handlers live in `src/updater/` as modules following the `pipeline.py` Step-class pattern (the
repo's class-based convention — `go_updater.py` / `docker_updater.py` / `python_updater.py` are
function-based and are not the class pattern to copy). CLI wiring goes in `cli.py`. Reuse
`git_operations.py` (branch/PR) and `config.py`; no new bespoke git implementation.
