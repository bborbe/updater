---
status: verifying
approved: "2026-08-23T11:00:45Z"
generating: "2026-08-23T11:16:19Z"
prompted: "2026-08-23T11:16:19Z"
verifying: "2026-08-23T11:26:22Z"
branch: dark-factory/infra-tier-state-machine
---

## Summary

- Add an orchestration layer to `updater` that chains the four infra-tier handlers (claude-yolo, dark-factory, bundlewrap, trading — all shipped in v0.24.0) in the runbook order, enforced in code instead of operator intuition
- Chain: claude-yolo first → wait for its PR merge + docker.io image publish → `docker manifest inspect` gate → dark-factory pin → bundlewrap + trading as the parallel tail (the runbook has them sequential; parallel is the architecture's design — no hard dependency between them or with dark-factory)
- New CLI subcommand (`updater chain`), reusing the handlers + `infra_tier.py` shared machinery; dry-run prints the planned sequence; failures abort loudly naming the failed step
- Lives in updater (the "where" decision, resolved 2026-08-23): in-process invocation of the handlers, no cross-repo dependency; go-version-watcher keeps its trigger role and fires the chain

## Problem

The four infra-tier handlers are built and individually verified (`--dry-run` diffs correct, real-run contract intact) but **uncoordinated**. Nothing enforces the runbook ordering ([[Go - Update Version]] step 4): claude-yolo must publish its docker.io image **before** the dark-factory pin, because `DefaultContainerImage` must resolve to a tag whose image actually exists. A mis-ordered chain bumps `DefaultContainerImage` to a non-existent image — the runbook's 2026-06-03 `manifest unknown` incident (dark-factory pin landed before the claude-yolo image pushed, breaking `make buca` for every consuming repo). Today the operator sequences the four repos by hand (~30-60 min/cycle per the runbook's expected duration, more when merge-watching stalls); the goal's architecture decision requires this ordering be **encoded in code** and enforced by a state machine, not intuition.

## Goal

`updater` can run the full infra-tier chain unattended: one command that invokes the four handlers in the correct order, waits on the external gates (PR merge, docker.io publish, manifest presence), and aborts with a named step on the first wrong link — while preserving each handler's existing `--dry-run`/real-run contract.

## Assumptions

- The four handlers remain in updater (shipped v0.24.0) and are independently invocable via their CLI subcommands
- claude-yolo's `build-multiarch` GitHub Actions workflow auto-publishes the new tag to docker.io on merge (already configured)
- Operator has `gh` auth for all four target repos and the updater container has network access to github.com + docker.io
- `docker` (or `docker manifest inspect`) is available where the chain runs; falls back to a documented error if absent
- The standard Go projects' fan-out already exists and runs independently; this state machine covers only the 4 infra-tier handlers, running bundlewrap + trading as the parallel tail (the standard fan-out is out of scope)

## Non-goals

- The 4 handler implementations themselves — shipped in updater v0.24.0, see spec `003-infra-tier-special-case-handlers`
- Observing/verifying the first real-run invocation — owned by the follow-up task [[First Infra-Tier Handler Invocation (real-run e2e)]]
- `bw apply` propagation to the fleet — operator runs manually; automation is a follow-up
- Weekly digest report — separate task
- NPM/Python updater coverage — parent goal non-goal

## Acceptance Criteria

- [ ] A CLI subcommand exists that runs the chain; `--dry-run` prints the exact planned sequence (step order + each step's target repo/handler) — negative evidence: `updater chain --dry-run` output lists `claude-yolo → manifest-verify → dark-factory → bundlewrap → trading` in that order
- [ ] The chain invokes the claude-yolo handler first and **waits** for its PR to merge + the new docker.io tag to publish before proceeding — probe: chain log shows a wait state with the PR URL and the publish check, resuming only after both
- [ ] After claude-yolo publishes, the chain runs `docker manifest inspect docker.io/bborbe/claude-yolo:<tag>` and blocks until it succeeds — verify-before-proceed per runbook step 4's hard prerequisite, retrying every 30s up to 30 minutes then aborting — before the dark-factory pin — probe: chain log shows ≥2 manifest-verify attempts with strictly increasing timestamps before proceeding
- [ ] dark-factory handler runs only after manifest-verify passes; its `DefaultContainerImage` resolves the new claude-yolo tag — probe: chain log orders dark-factory strictly after the manifest gate
- [ ] bundlewrap + trading run in parallel after the dark-factory pin — probe: chain log shows both steps active concurrently (overlapping timestamps), both exit 0
- [ ] A failure in any step aborts the chain loudly naming the failed step — negative evidence: injecting a failing step (e.g. manifest never present, or a handler exit-1) stops the chain and the log names the step; exit code non-zero
- [ ] Each handler's existing `--dry-run`/real-run contract is preserved — `updater <handler> --dry-run` behaves unchanged; the chain invokes the same code paths
- [ ] Existing updater tests pass unchanged (`make precommit` exit 0); new chain-order tests cover claude-yolo-first, manifest gate, dark-factory-after-verify, parallel fan-out, and abort-names-step

## Verification

### Container-executable (runs inside the YOLO container at prompt time)

- `make precommit` exit 0 (format, tests, lint, typecheck)
- Unit tests cover the chain state transitions: `claude-yolo → waiting-pr-merge → waiting-publish → manifest-gate → dark-factory → parallel(bundlewrap, trading)`
- A mocked/managed chain run (handlers stubbed) verifies ordering + abort behavior end-to-end in-process

### Operator-executable (runs on the host)

- `updater chain --dry-run` against live repos prints the planned sequence matching the goal ordering exactly
- One real chain invocation observed on trigger (or explicitly deferred to the follow-up task, with the deferral recorded) — no untested silent chain

## Desired Behavior

1. `updater chain` reads the target Go version (from `--go-version` or the watcher's detected version) and computes the planned sequence
2. Runs claude-yolo first (real run, opens PR); polls the PR state until merged, then polls docker.io until the new tag's manifest is present
3. Runs `docker manifest inspect docker.io/bborbe/claude-yolo:<tag>` as an explicit gate — verify-before-proceed per runbook step 4's hard prerequisite — retrying every 30s up to 30 minutes, then aborting naming the step
4. Runs dark-factory (its handler resolves claude-yolo's latest release tag — now the published one)
5. Runs bundlewrap + trading in parallel
6. `--dry-run` prints the sequence and exits without side effects
7. Any step failure aborts the chain, logs the named step, and exits non-zero; no partial silent state
8. Idempotent per handler: an already-current target or an existing `head:updater` PR is reported and skipped, per the handlers' existing semantics

## Constraints

- Lives in `src/updater/` as a module following the `pipeline.py` Step-class pattern; CLI wiring in `cli.py`; reuses `infra_tier.py`, `git_operations.py`, `config.py` — no new bespoke git implementation
- Follows updater's dark-factory mandate (spec → audit → approve → prompts → daemon)
- `make precommit` stays green; existing tests unchanged
- Ordering is fixed: claude-yolo → manifest gate → dark-factory per the runbook's hard prerequisite; bundlewrap + trading as the parallel tail (the architecture's design, not a runbook prescription — no hard dependency between them or with dark-factory); the state machine does not reorder
- PRs use conventional `chore:`/`feat:` prefixes and `## Unreleased` CHANGELOG bullets (autoRelease repo needs the bullet)

## Failure Modes

| Trigger | Expected behavior | Recovery |
|---|---|---|
| claude-yolo PR not merged | Chain waits (state `waiting-pr-merge`); logs PR URL; continues polling, never proceeds | Operator merges the PR; chain resumes |
| docker.io tag manifest absent after merge | Manifest-verify retry loop logs attempts + timestamps (every 30s up to 30 min); chain stays in `waiting-publish` | Retry until `docker manifest inspect` succeeds; on 30-min timeout, abort naming the step (runbook's 2026-06-03 `manifest unknown` incident) |
| claude-yolo's build-multiarch workflow never fires | docker.io tag never appears; manifest-verify escalates with a named error pointing at the workflow (never a silent infinite poll) | Verify the workflow ran, fix, re-run |
| GitHub / docker.io API rate limit | Chain backs off and retries with jitter, logging the limit; never treats a 403/429 as a step failure | Chain resumes on reset; if persistent, operator adjusts quota |
| dark-factory handler exit 1 | Chain aborts naming `dark-factory`; exit non-zero | Fix + re-run; existing `find_existing_pull_request` prevents duplicate PRs |
| bundlewrap/trading one fails, other succeeds | Parallel step: failing branch aborts the chain naming the step; successful branch's PR is left (reported, not duplicated) | Re-run handles idempotency |
| `docker` not available | Chain fails at the manifest gate with a documented error naming the missing binary | Install docker or run where available |
| Target repo has uncommitted changes | Handler aborts before touching (existing `require_clean_worktree`); chain aborts naming the repo | Operator stashes/commits; re-run |

## Security/Abuse

- The chain invokes existing handler subcommands with validated inputs (`validate_go_version`, `validate_claude_yolo_tag`) — no new shell injection surface; branch names are controlled constants from validated version strings
- The manifest gate runs `docker manifest inspect` on a tag resolved from the just-merged claude-yolo PR — no user-supplied image string reaches the shell
- No credentials handled by the chain itself; `gh`/docker auth are the operator's ambient session

## Suggested Decomposition

| # | Prompt focus | Covers DBs | Covers ACs | Depends on |
|---|---|---|---|---|
| 1 | Chain command + state machine (claude-yolo-first, wait-for-merge, wait-for-publish, manifest gate, dark-factory, parallel tail) + CLI wiring in `cli.py`; unit tests for ordering state transitions | 1-8 | 1, 2, 3, 4, 5, 8 | shares `infra_tier.py` helper |
| 2 | Dry-run sequence printer + abort-on-failure naming + idempotency re-use of handler contracts; integration-style tests for the abort path | 6, 7 | 6, 7, 8 | prompt 1 |

(The shared `infra_tier.py` machinery already handles most git/PR work; the chain is mostly orchestration + polling, so the two prompts stay small.)

## Do-Nothing Option

The handlers stay individually invocable but uncoordinated; the operator hand-sequences four repos per Go release (~30-60 min/cycle per the runbook, more when merge-watching stalls). The parent goal's "fleet-wide unattended" outcome is not met — the chain is the last orchestration gap. Not acceptable; the task is named first in the goal's polish tail.
