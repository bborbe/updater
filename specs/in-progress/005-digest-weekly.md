---
status: prompted
approved: "2026-08-23T14:23:38Z"
generating: "2026-08-23T14:49:19Z"
prompted: "2026-08-23T14:49:19Z"
branch: dark-factory/digest-weekly
---

## Summary

- Add an `updater digest` subcommand that renders the weekly Go-update digest — the operator's only routine touchpoint in the unattended fleet pipeline
- Queries the past week's state: git tags per repo (which Go versions bumped), `gh` PRs (`head:updater`), releases (tag-only → tags are the source of truth), parked no-fix advisories, `human_review`-flagged tasks, failed builds, chain aborts
- Renders one summary (versions, PRs, releases) + the exceptions needing judgment; scheduled weekly with Slack/email delivery
- Lives in updater (the "where/how" decision, resolved 2026-08-23): consistent with the pipeline's home, testable, truly unattended; the recurring-vault-task / maintainer-infra / dark-factory-prompt branches were ruled out

## Problem

The fleet pipeline is proven unattended end-to-end (watcher → fan-out → agent → PR → bot review → auto-merge → auto-release), and the operator's role has shrunk to "review a weekly digest, handle the 1-2 exceptions per cycle that need judgment". But that digest does not exist — the operator must either trust the pipeline blindly or re-derive fleet state by hand from git tags / `gh` PRs / releases / the park list, recreating the ~3h/cycle manual load the goal's impact section says the role shrinks to. The goal's success criterion is explicit: *"Weekly digest report — Slack/email '32/33 repos updated this week, 1 failed: vault-cli (vuln in foo, no upstream fix yet)'. Operator gets one notification per week, not 33 individual PR pings."*

## Goal

One `updater digest` invocation produces a complete, accurate weekly summary from live state (versions bumped, PRs opened/merged/closed, releases cut) plus the judgment-needed exceptions — generated unattended on a weekly cadence, so the operator's review is one pass.

## Assumptions

- All data sources are queryable today from the operator's machine / the scheduler environment: `git ls-remote --tags` per repo; `gh pr list --search 'head:updater'`; tags (release source of truth — many repos are tag-only, no GitHub Release objects); github-update-go-agent `plan_output.go` `Outcome=needs_input` park classification; vault `24 Tasks/` + `OpenClaw/tasks/` for `human_review`; github-build-watcher for failed builds; updater chain state/logs for aborts (verified 2026-08-23 in the task)
- `gh` auth and network access exist where the digest runs (same ambient session as the rest of the updater tooling)
- The weekly cadence target is Monday-morning delivery (or the operator's preferred channel) — channel (Slack/email) is a prompt decision with a default of email
- The fleet of repos is enumerable (the same repo list the pipeline's fan-out uses)

## Non-goals

- The pipeline itself (watcher → fan-out → agent → PR → review → auto-merge → auto-release) — proven end-to-end, owned by the parent goal
- Handling the exceptions the digest surfaces — the operator + [[Failed Build Fix Agent]] do that; the digest only reports them
- Replacing the [[Go - Update Version]] runbook — stays as the manual fallback
- Non-Go dependency reporting (NPM/Python) — parent goal non-goal
- Real-run e2e of infra-tier handlers / trigger-ordering chain — owned by the follow-up task

## Acceptance Criteria

- [ ] `updater digest` renders a complete weekly summary from live state: per-repo Go versions bumped, PRs opened/merged/closed (`head:updater`), releases cut — negative evidence: running it prints the summary with each section populated from live `git ls-remote` / `gh pr list` / tags, not placeholder text
- [ ] The digest surfaces judgment-needed exceptions: parked no-fix advisories, failed builds, chain aborts, `human_review`-flagged tasks — probe: a run with a known parked advisory / failed build lists it under an "Exceptions" section
- [ ] The digest is generated unattended on a weekly cadence (no operator action beyond reading); running twice for the same week produces exactly one message — probe: a scheduled run posts the digest to the delivery channel without interaction; negative evidence: the channel's send-log/inbox count for the week is 1 after two runs of the same week
- [ ] A sample digest for the current week is verified accurate: every claim cross-checked one-by-one against live git tags / `gh` PRs / tags / park list — probe: sample matches live state (e.g. updater tag v0.25.0, zero open `head:updater` PRs on updater, no GitHub Release objects for updater (tag-only), park list shows the known parked advisories, `human_review` count matches the vault/OpenClaw state)
- [ ] `updater digest --dry-run` (or `--stdout`) prints the digest to the console without sending — negative evidence: dry-run shows the full digest text and sends nothing
- [ ] Existing updater tests pass unchanged (`make precommit` exit 0); new digest tests cover rendering, source queries (mocked), and the exceptions section

## Verification

### Container-executable (runs inside the YOLO container at prompt time)

- `make precommit` exit 0 (format, tests, lint, typecheck)
- Unit tests: source-query parsing (tags / gh PR JSON / park list), summary rendering, exceptions section, dry-run no-send
- A mocked digest run renders a full digest with no network

### Operator-executable (runs on the host)

- `updater digest` (live) renders the current week's digest; every claim cross-checked against live state (the sample-verification rung)
- One observed weekly-cadence delivery (or explicitly deferred with the deferral recorded) — no untested silent schedule

## Desired Behavior

1. `updater digest` (default: current week; `--since`/`--until` override) enumerates the fleet repos and queries each source
2. Renders sections: Go versions bumped (per repo, current vs previous tag), PRs opened/merged/closed, releases cut, exceptions (parked advisories, failed builds, chain aborts, `human_review` items)
3. Delivers via the configured channel (default email; Slack if configured); `--dry-run`/`--stdout` prints without sending
4. Idempotent: re-running the same week produces the same digest (no duplicate sends)
5. A source query failure (rate limit, repo missing) degrades gracefully: the section shows a named error, the rest of the digest still renders

## Constraints

- Lives in `src/updater/` as a module following the `pipeline.py` Step-class pattern; CLI wiring in `cli.py`; reuses `git_operations.py` (gh invocations), `config.py`, `log_manager.py` — no new bespoke git implementation
- Follows updater's dark-factory mandate (spec → audit → approve → prompts → daemon)
- References `docs/architecture.md` + `docs/roadmap.md` for pipeline topology; the park-list classification (github-update-go-agent `plan_output.go` `Outcome=needs_input`) and github-build-watcher failure semantics are cross-project behavioral rules the digest depends on — flag both for documentation in their repos' docs before prompts are generated
- `make precommit` stays green; existing tests unchanged
- Delivery is read-only reporting: the digest never mutates repos, opens/closes PRs, or changes state — it only queries and reports
- `## Unreleased` CHANGELOG bullet for the new subcommand (autoRelease repo)

## Failure Modes

| Trigger | Expected behavior | Recovery |
|---|---|---|
| GitHub API rate limit during queries | Digest backs off + retries with jitter, logs the limit, renders the affected sections with a named error; never a silent empty section | Chain/digest resumes on reset; operator adjusts quota if persistent |
| Repo missing / renamed | Section shows a named error for that repo; digest still renders the rest | Operator updates the repo list |
| Delivery channel unreachable | Digest renders to stdout with a send-failure note; exit non-zero naming the channel | Fix channel creds; re-run |
| No changes in the week | Digest renders "no updates this week" summary + exceptions (still delivered — the operator needs the negative signal) | None |
| A source returns malformed data | That section shows a named parse error, rest renders; never a raw traceback | Fix source; re-run |
| Two runs overlap / delivery retried after partial failure | One message sent; the second run detects the week already delivered and skips (no duplicate send) | Check the delivery log; re-run |

## Security/Abuse

- The digest only queries public-ish repo state via the operator's ambient `gh`/git auth — no credentials handled by the command itself
- No shell injection: repo names / tags are validated inputs, never interpolated into shell commands without the existing `run_command` boundary
- Delivery content is generated from repo metadata — no free-text from sources reaches a shell
- The digest never mutates state (read-only by constraint) — no blast radius beyond an accurate report

## Suggested Decomposition

| # | Prompt focus | Covers DBs | Covers ACs | Depends on |
|---|---|---|---|---|
| 1 | Digest module + `updater digest` CLI wiring: fleet enumeration, source queries (tags/gh/releases), summary + exceptions rendering, `--dry-run`/`--stdout` | 1-5 | 1, 2, 4, 5, 6 | reuses `git_operations.py` |
| 2 | Weekly cadence + delivery (email default, Slack if configured): scheduling, idempotent no-duplicate-send, send-failure handling; integration tests for the delivery path | 1, 3, 5 | 3, 5, 6 | prompt 1 |

## Do-Nothing Option

The operator keeps re-deriving fleet state by hand each week (~3h/cycle) or trusts the pipeline blindly. The goal's "Weekly digest report" success criterion is unmet — the digest is the last unbuilt deliverable of the pipeline's polish tail. Not acceptable; the task is the goal's named next deliverable.
