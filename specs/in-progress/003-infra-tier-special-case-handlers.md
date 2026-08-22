---
status: verifying
approved: "2026-08-22T20:40:58Z"
generating: "2026-08-22T20:41:46Z"
verifying: "2026-08-22T22:07:16Z"
branch: dark-factory/infra-tier-special-case-handlers
---

## Summary

- Add four handler classes to `updater` that patch-and-PR the infra-tier files the generic Go updater can't touch
- Each handler targets one repo + one file + one constant: claude-yolo `Dockerfile ARG GO_VERSION`, dark-factory `pkg/const.go DefaultContainerImage`, BundleWrap `bundles/golang/items.py default_golang_version`, trading monorepo (no single constant — replicates `update-go-version.sh`'s walk across go.mod/Dockerfile/workflow pins)
- Each handler supports `--dry-run` (show diff, no PR) and a real run (open PR in the target repo)
- Handlers live as classes in `src/updater/` matching the existing per-domain updater convention (`go_updater.py`, `docker_updater.py`, `python_updater.py`)
- The sibling [[Build Trigger Ordering State Machine]] will invoke these handlers in order

## Problem

The generic `updater` tool bumps the 33 standard Go projects. Four infra-tier targets have unique files/constants the generic tool can't touch — claude-yolo (Dockerfile `ARG GO_VERSION`), dark-factory (Go const tracking claude-yolo's release tag), BundleWrap (Python `default_golang_version`), trading monorepo (no central constant — the version lives across every module's go.mod/Dockerfile/workflow, updated via `make updategoversion` → `update-go-version.sh`). Without handlers for these, "fleet-wide" stops at 33 repos and the operator hand-edits the other four every Go release.

## Goal

The updater can bump all four infra-tier targets autonomously: a handler exists for each, produces the correct diff (`--dry-run`), and opens a PR on a real run — exactly the patch-and-PR pattern the generic updater already applies to the 33 standard projects.

## Assumptions

- Operator has `gh` auth for all four target repos (claude-yolo, dark-factory, bw, trading)
- The updater container has network access to github.com for cloning targets (or the dry-run evidence runs on the host per the operator rung — see Verification)
- Target files stay at the frozen paths listed in Constraints
- Each target repo follows the standard bot-review → auto-merge flow for handler-opened PRs

## Non-goals

- `bw apply` propagation to the fleet after a BundleWrap merge — operator runs it manually; automation is a follow-up
- docker.io manifest-verify after claude-yolo auto-publish — owned by [[Build Trigger Ordering State Machine]]
- NPM/Python updater coverage (parent-goal non-goal)
- Fixing the 2 laggard repos' pre-existing debt (separate task)
- Changes to existing updater pipeline logic, step order, or the generic Go/Python/Docker updaters

## Acceptance Criteria

- [ ] `src/updater/` contains a claude-yolo handler module; `--dry-run --go-version 1.28.0` against a fixture/scratch checkout shows before `ARG GO_VERSION=1.27.0` → after `ARG GO_VERSION=1.28.0`, touching `Dockerfile` only — negative evidence: `git diff --name-only` lists exactly `Dockerfile`
- [ ] The claude-yolo handler's real run opens a PR in `bborbe/claude-yolo` with `ARG GO_VERSION` bumped — probe: `gh pr list --repo bborbe/claude-yolo --search 'head:updater'` shows one open PR
- [ ] `src/updater/` contains a dark-factory handler module; `--dry-run` shows a diff touching `pkg/const.go` `DefaultContainerImage` bumped to the latest `claude-yolo:vA.B.C` tag — negative evidence: `git diff --name-only` lists exactly `pkg/const.go`
- [ ] The dark-factory handler's real run opens a PR in `bborbe/dark-factory` — probe: `gh pr list --repo bborbe/dark-factory --search 'head:updater'` shows one open PR
- [ ] `src/updater/` contains a BundleWrap handler module; `--dry-run` shows a diff touching `bundles/golang/items.py` `default_golang_version` — negative evidence: `git diff --name-only` lists exactly `bundles/golang/items.py`
- [ ] The BundleWrap handler's real run opens a PR in the BundleWrap repo — probe: `gh pr list --repo <bw-repo> --search 'head:updater'` shows one open PR
- [ ] `src/updater/` contains a trading handler module; `--dry-run` applies the `update-go-version.sh` walk (go.mod `go`+`toolchain`, Dockerfile `FROM golang:`, workflow `go-version:`, excluding vendor/) to the target version — negative evidence: `git diff --name-only` lists the patched go.mod/Dockerfile/workflow files and never vendor/
- [ ] The trading handler's real run opens a PR in the trading monorepo (feature worktree from master, apply the walk, commit, push) — probe: `gh pr list --repo bborbe/trading --search 'head:updater'` shows one open PR
- [ ] Each handler exits 0 on `--dry-run` with an up-to-date target (no spurious diff) — negative evidence: `git diff` of the target file is empty
- [ ] A real run against an already-current target, or against a target with an existing open `head:updater` PR, exits 0 and opens no new PR — negative evidence: `git diff` of the target file empty after run; `gh pr list --repo <target> --search 'head:updater'` shows no new PR from the handler (existing one, if any, is reported by URL and left alone)
- [ ] Existing updater tests pass unchanged (`make precommit` exit 0)

## Verification

### Container-executable (runs inside the YOLO container at prompt time)

- `make precommit` — lint/typecheck/tests clean
- `uv run pytest` — unit + integration suite passes
- `uv run updater <handler> --dry-run --go-version X.Y.Z` against a fixture/scratch checkout in `/tmp` — prints the intended diff (file, constant, before/after). NOTE: `.dark-factory.yaml` mounts only the updater repo + uv cache; the container does NOT mount the four target checkouts, so container dry-runs use a scratch clone/fixture, and the real-target dry-run + PR-opening evidence lives in the operator rung.
- `grep -n 'Handler' src/updater/*.py` — four handler modules present (pipeline `Step`-class convention, per Recommendation)

### Operator-executable (runs on the host after PR merge, spec verification ladder)

- `uv run updater <handler> --dry-run` against a real target repo checkout — diff matches expected constant (frozen target map in `docs/infra-tier-targets.md`)
- A real run on each target repo opens a PR (claude-yolo, dark-factory, bw, trading)
- `gh pr view <n> --json state` — PR open, review flows, merged

## Desired Behavior

1. A new `updater <handler>` CLI subcommand exists for each of the four infra-tier targets (claude-yolo, dark-factory, bundlewrap, trading)
2. Each handler resolves its target constant from the repo's current state (or, for dark-factory, from claude-yolo's latest release tag)
3. `--dry-run` prints the exact diff that would be applied and opens no PR
4. A real run applies the patch in a feature worktree (trading) or direct branch, opens a PR with a conventional-title, and reports the PR URL
5. A handler run against an already-current target exits 0 with no diff and no PR (idempotent — both `--dry-run` and real run)
6. Each handler module follows the existing updater `pipeline.py` Step-class convention (config, logging, git-ops reuse) — `go_updater.py` / `docker_updater.py` / `python_updater.py` are function-based modules, not classes; the class-based `Step` pattern is the class convention to match

## Constraints

- Handlers live in `src/updater/` as modules following the `pipeline.py` Step-class pattern (repo convention — no `handlers/` dir); CLI wiring in `cli.py`
- Reuse existing `git_operations.py` (branch/PR) and `config.py` where possible — no new bespoke git implementation
- Target repos' files are frozen — the canonical map is `docs/infra-tier-targets.md` (see Recommendation); current paths: claude-yolo `Dockerfile` `ARG GO_VERSION=X.Y.Z`, dark-factory `pkg/const.go` `DefaultContainerImage = "docker.io/bborbe/claude-yolo:vA.B.C"`, BundleWrap `bundles/golang/items.py` `default_golang_version = 'X.Y.Z'`, trading monorepo (no central constant — the handler replicates `update-go-version.sh`'s sed walk: go.mod `go`/`toolchain`, Dockerfile `FROM golang:`, workflow `go-version:`, excluding vendor/; feature worktree from master, documented in `docs/infra-tier-targets.md`)
- Handler invocation order for the state machine is owned by the sibling [[Build Trigger Ordering State Machine]] spec — this spec's handlers are each independently invocable
- `make precommit` stays green; existing tests unchanged
- PRs use the conventional `chore:` / `feat:` prefix and `## Unreleased` CHANGELOG bullet per repo (autoRelease repos need the bullet)

## Failure Modes

| Trigger | Expected behavior | Recovery |
|---------|-------------------|----------|
| claude-yolo already on target Go version | Exit 0, no diff, no PR | No-op (idempotent) |
| dark-factory cannot resolve claude-yolo's latest release (network/gh) | Handler fails fast with the resolution error | Operator retries; check `gh release list` on claude-yolo |
| Target repo has uncommitted local changes (trading worktree) | Handler aborts before touching the file | Operator stashes/commits; re-run |
| Target constant not found (file moved/renamed in target repo) | Handler fails with "pattern not found" naming the file+pattern | Operator updates the handler's pattern to the new location |
| PR creation fails (auth, branch protection) | Handler reports the error, no partial PR | Operator fixes auth; PR flow is reversible |
| GitHub API rate limit (4 repos, PR + tag-resolution calls) | Handler surfaces the `gh` rate-limit error; no partial PR | Operator waits for the limit window, re-runs; each handler is idempotent |

## Security / Abuse

- `--go-version` (and the handler's target-version input) is validated against a `X.Y.Z`-shaped regex before interpolation into the patch — no shell injection / path traversal into the sed/patch or git command
- The only write path is a PR (reviewable, reversible); no handler ever pushes directly to a target's master
- No secrets (gh tokens, clone URLs with credentials) are written to PR bodies or logs
- Handler-scoped git operations use the repo's existing `git_operations.py` token handling, never inline credentials

## Suggested Decomposition

Prompts generated in this order — each is a single handler + its test.

| # | Prompt focus | Covers DBs | Covers ACs | Depends on |
|---|---|---|---|---|
| 1 | claude-yolo handler class + CLI subcommand + tests | 1, 3, 5 | 1, 2, 9, 10 | — |
| 2 | dark-factory handler (claude-yolo tag resolution) + tests | 2, 3, 5 | 3, 4, 9, 10 | prompt 1 (shares patch-and-PR helper) |
| 3 | BundleWrap handler + tests | 3, 5 | 5, 6, 9, 10 | prompt 1 (shares helper) |
| 4 | trading handler (worktree + sed walk) + tests | 4, 5 | 7, 8, 9, 10 | prompt 1 (shares helper) |

Rationale: prompt 1 establishes the shared patch-and-PR helper + CLI wiring; prompts 2-4 each add one target reusing it; all four are independently verifiable. A shared helper (patch file → diff → branch → PR) is extracted in prompt 1 and reused.

## Do-Nothing Option

Operator keeps hand-editing claude-yolo + dark-factory + BundleWrap + trading each Go release — ~30-60 min/cycle across four repos, exactly the manual load the parent goal exists to remove. The state machine (next task) would have nothing to invoke for these targets.
