# Infra-Tier Targets

The four infra-tier files the generic updater can't touch — each has a unique file + constant + repo.
These are the frozen targets for the infra-tier special-case handlers (spec
`specs/infra-tier-special-case-handlers.md`).

| Target | Repo | File | Constant | Current value (2026-08-22) |
|---|---|---|---|---|
| claude-yolo | `bborbe/claude-yolo` | `Dockerfile` | `ARG GO_VERSION=X.Y.Z` | `ARG GO_VERSION=1.27.0` |
| dark-factory | `bborbe/dark-factory` | `pkg/const.go` | `DefaultContainerImage = "docker.io/bborbe/claude-yolo:vA.B.C"` (tracks claude-yolo's release tag, NOT the Go version directly) | `DefaultContainerImage = "docker.io/bborbe/claude-yolo:v0.15.1"` |
| BundleWrap | BundleWrap repo | `bundles/golang/items.py` | `default_golang_version = 'X.Y.Z'` | `default_golang_version = '1.27.0'` |
| trading monorepo | `bborbe/trading` | `Makefile.folder` | `go X.Y.Z` constant | (present; current value per repo) |

## claude-yolo release flow

- On merge of a handler PR, `make build-multiarch` auto-publishes the new claude-yolo tag to
  docker.io (already-configured GitHub Actions workflow).
- dark-factory's `DefaultContainerImage` must be bumped to the **new claude-yolo tag** after that
  publish — resolved from claude-yolo's latest GitHub release, not the Go version directly.

## trading monorepo — the 2026-06-03 canonical pattern

For the trading monorepo (`bborbe/trading`), do NOT edit `Makefile.folder` in the working tree
directly:

1. Create a feature worktree from `master`.
2. Bump the `go X.Y.Z` constant in `Makefile.folder`.
3. Run `make ensurecommit` in that worktree — it propagates the Go version to every per-module
   `Makefile`/config the monorepo needs.
4. Open a PR (the monorepo's standard flow).

## Handler module convention

Handlers live in `src/updater/` as modules following the `pipeline.py` Step-class pattern (the
repo's class-based convention — `go_updater.py` / `docker_updater.py` / `python_updater.py` are
function-based and are not the class pattern to copy). CLI wiring goes in `cli.py`. Reuse
`git_operations.py` (branch/PR) and `config.py`; no new bespoke git implementation.
