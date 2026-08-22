---
status: completed
spec: [003-infra-tier-special-case-handlers]
summary: Added the dark-factory infra-tier handler (updater dark-factory subcommand) that bumps DefaultContainerImage in bborbe/dark-factory pkg/const.go via the shared process_infra_target helper, wired it into cli.py, updated the CHANGELOG, and added 14 tests (100% coverage on the new module).
execution_id: updater-exec-042-spec-003-dark-factory-handler
dark-factory-version: dev
created: "2026-08-22T21:45:00Z"
queued: "2026-08-22T21:19:40Z"
started: "2026-08-22T21:59:06Z"
completed: "2026-08-22T22:02:02Z"
---

# dark-factory infra-tier handler

<summary>
- A new `updater dark-factory` subcommand bumps `DefaultContainerImage` in the dark-factory repo's `pkg/const.go` and, on a real run, opens a PR in `bborbe/dark-factory`
- The target value is the claude-yolo image tag (`docker.io/bborbe/claude-yolo:vA.B.C`), resolved from claude-yolo's latest GitHub release by default, or supplied explicitly via `--claude-yolo-tag` (required for deterministic container dry-runs, since the container has no gh auth)
- `--dry-run` prints the intended diff (file, constant before/after) and modifies only `pkg/const.go`'s working tree — no branch, no commit, no PR
- If claude-yolo's latest release cannot be resolved (network/gh failure), the handler fails fast with the resolution error and touches nothing
- A run against an already-current target exits 0 with no diff and no PR (idempotent)
- A real run against a target that already has an open `head:updater` PR exits 0 without opening a new one, reporting the existing PR's URL instead
- Reuses the shared patch-and-PR helper (`process_infra_target`) extracted by the claude-yolo prompt — no duplicated logic
</summary>

<objective>
Add the dark-factory infra-tier handler as a new `updater dark-factory` subcommand so the fleet-wide bump can cover `bborbe/dark-factory`'s `pkg/const.go` `DefaultContainerImage` (which tracks claude-yolo's release tag, not the Go version directly).
</objective>

<context>
Read `/workspace/CLAUDE.md` for project conventions.

Read the frozen target map: `/workspace/docs/infra-tier-targets.md` (dark-factory row + the "claude-yolo release flow" section). The dark-factory frozen target is `bborbe/dark-factory` `pkg/const.go` `DefaultContainerImage = "docker.io/bborbe/claude-yolo:vA.B.C"` (current value `docker.io/bborbe/claude-yolo:v0.15.1`), which tracks claude-yolo's release tag — resolved from claude-yolo's latest GitHub release, NOT from the Go version directly.

Read these files fully before editing:
- `/workspace/src/updater/infra_tier.py` — the shared helper from the prior prompt: `process_infra_target(checkout, *, repo, target_file, pattern, new_value, branch_name, title, body, changelog_bullet, dry_run) -> int`, `validate_claude_yolo_tag`, `validate_go_version`, `InfraTargetError`. REUSE these — do not reimplement.
- `/workspace/src/updater/claude_yolo_handler.py` — the handler shape to mirror (module constants + `XxxHandler` class with a `run` method).
- `/workspace/src/updater/cli.py` — `main_updater_async` subparser construction + dispatch chain (the `claude-yolo` subcommand added by the prior prompt is the template).
- `/workspace/src/updater/log_manager.py` — `run_command` (raises `RuntimeError` on non-zero exit).
- `/workspace/tests/test_claude_yolo_handler.py` and `/workspace/tests/test_infra_tier.py` — test style for handler tests (pytest, `unittest.mock.patch`, `tmp_git_repo` fixture, no real network).
- `/workspace/tests/conftest.py` — the `tmp_git_repo` fixture.

Reference docs (in-container paths):
- `/home/node/.claude/plugins/marketplaces/coding/docs/python-cli-arguments-guide.md`
- `/home/node/.claude/plugins/marketplaces/coding/docs/python-logging-guide.md`

OPEN QUESTIONS FOR THE REVIEWER (resolved as best-effort below):
- `--claude-yolo-tag` is an explicit override flag (optional). Without it the handler resolves the tag from `gh release view -R bborbe/claude-yolo`; with it the tag is used directly. The override exists so the container dry-run and tests are deterministic (the container has no gh auth). Confirm this is the intended injection point.
</context>

<requirements>

## 1. Create `src/updater/dark_factory_handler.py`

```python
"""Infra-tier handler for bborbe/dark-factory's DefaultContainerImage constant."""

import re
from pathlib import Path

from .infra_tier import (
    InfraTargetError,
    process_infra_target,
    validate_claude_yolo_tag,
)
from .log_manager import log_message, run_command

DARK_FACTORY_REPO = "bborbe/dark-factory"
DARK_FACTORY_FILE = "pkg/const.go"
DARK_FACTORY_PATTERN = re.compile(
    r'DefaultContainerImage = "docker\.io/bborbe/claude-yolo:(v\d+\.\d+\.\d+)"'
)
```

Add a module-level function that resolves claude-yolo's latest release tag:

```python
def resolve_latest_claude_yolo_tag(checkout: Path) -> str:
    """Return the latest claude-yolo release tag (e.g. 'v0.16.0') via gh.

    Raises:
        RuntimeError: gh failed (auth, network, rate limit).
        InfraTargetError: gh returned a tag that is not vX.Y.Z-shaped.
    """
    result = run_command(
        "gh release view -R bborbe/claude-yolo --json tagName --jq .tagName",
        cwd=checkout,
        capture_output=True,
        quiet=True,
        log_func=log_message,
    )
    tag = result.stdout.strip()
    if not validate_claude_yolo_tag(tag):
        raise InfraTargetError(f"unexpected claude-yolo release tag from gh: {tag!r}")
    return tag
```

Then the handler class:

```python
class DarkFactoryHandler:
    """Bump DefaultContainerImage in bborbe/dark-factory pkg/const.go and open a PR."""

    def run(self, checkout: Path, *, dry_run: bool, claude_yolo_tag: str | None) -> int:
        if claude_yolo_tag is None:
            try:
                claude_yolo_tag = resolve_latest_claude_yolo_tag(checkout)
                log_message(f"→ Resolved latest claude-yolo release tag: {claude_yolo_tag}", to_console=True)
            except (RuntimeError, InfraTargetError) as e:
                log_message(f"✗ Cannot resolve claude-yolo's latest release: {e}", to_console=True)
                return 1
        if not validate_claude_yolo_tag(claude_yolo_tag):
            log_message(f"✗ Invalid claude-yolo tag: {claude_yolo_tag!r} (expected vX.Y.Z)", to_console=True)
            return 1
        return process_infra_target(
            checkout,
            repo=DARK_FACTORY_REPO,
            target_file=DARK_FACTORY_FILE,
            pattern=DARK_FACTORY_PATTERN,
            new_value=claude_yolo_tag,
            branch_name=f"updater/dark-factory-{claude_yolo_tag}",
            title=f"chore: bump DefaultContainerImage to claude-yolo:{claude_yolo_tag}",
            body=f"Bump DefaultContainerImage to docker.io/bborbe/claude-yolo:{claude_yolo_tag}.",
            changelog_bullet=f"chore: bump DefaultContainerImage to claude-yolo:{claude_yolo_tag}",
            dry_run=dry_run,
        )
```

Notes:
- The resolution happens FIRST, before any patching — a resolution failure touches nothing (spec failure mode "dark-factory cannot resolve claude-yolo's latest release").
- `process_infra_target` reads the current value (group 1 = `v0.15.1`), compares to the target tag, patches via its generic group-1 replacement (preserving `DefaultContainerImage = "docker.io/bborbe/claude-yolo:` … `"`), and runs the branch/commit/push/PR flow on a real run. Do not duplicate any of that here.

## 2. Wire the CLI in `src/updater/cli.py`

In `main_updater_async`:
- Add the import: `from .dark_factory_handler import DarkFactoryHandler`.
- AFTER the existing `claude-yolo` subparser, add:
```python
sub = subparsers.add_parser(
    "dark-factory",
    help="Bump DefaultContainerImage in bborbe/dark-factory pkg/const.go and open a PR",
)
sub.add_argument("path", help="Path to the bborbe/dark-factory checkout")
sub.add_argument("--dry-run", action="store_true", help="Show the diff and exit without opening a PR")
sub.add_argument(
    "--claude-yolo-tag",
    default=None,
    metavar="TAG",
    help="Target claude-yolo release tag (e.g. v0.16.0); defaults to claude-yolo's latest GitHub release",
)
```
- In the dispatch chain add:
```python
elif args.subcommand == "dark-factory":
    return DarkFactoryHandler().run(
        Path(args.path), dry_run=args.dry_run, claude_yolo_tag=args.claude_yolo_tag
    )
```
- In the final `else` branch, `valid` is derived from `_sub_descs` (`valid = ", ".join(_sub_descs.keys())` in cli.py). Extend the derived value with the handler subcommand WITHOUT adding it to `_sub_descs` (adding it would give it the wrong positional and create a conflicting subparser): `valid = ", ".join([*_sub_descs.keys(), "dark-factory"])`.

Do NOT touch the other subcommands.

## 3. CHANGELOG

Add (or append to) the `## Unreleased` section in the updater repo's CHANGELOG.md:
`- feat: Add infra-tier dark-factory handler (updater dark-factory) — bumps DefaultContainerImage from claude-yolo's latest release tag`

## 4. Tests — `tests/test_dark_factory_handler.py` (new file)

Use the `tmp_git_repo` fixture; commit the target file so the worktree is clean. Mock gh and git push/PR by patching the names imported into the modules under test. For dry-run diff tests, let the real `git` binary run against the fixture (real subprocess boundary).

Fixture file content for `pkg/const.go`:
```
const DefaultContainerImage = "docker.io/bborbe/claude-yolo:v0.15.1"
```
(create the `pkg` directory, write the file, `git add` + `git commit`).

1. `test_run_dry_run_with_tag_bumps_const` — `run(repo, dry_run=True, claude_yolo_tag="v0.16.0")` → 0; file now `:v0.16.0`; real `git diff --name-only` == `["pkg/const.go"]`. Assert no `gh`/push/PR functions called (patch the git_operations functions as spies).
2. `test_run_dry_run_up_to_date` — fixture already at `v0.16.0`; run with `v0.16.0` → 0; diff empty.
3. `test_run_invalid_tag` — `"0.16.0"` → 1; file untouched.
4. `test_resolve_latest_claude_yolo_tag_success` — patch `updater.log_manager.run_command` → stdout `"v0.16.0\n"` → returns `"v0.16.0"`; assert the command contains `gh release view -R bborbe/claude-yolo`.
5. `test_resolve_latest_claude_yolo_tag_invalid` — stdout `"0.16.0\n"` → `pytest.raises(InfraTargetError)`.
6. `test_resolve_latest_claude_yolo_tag_gh_failure` — `run_command` raises `RuntimeError` → propagates.
7. `test_run_resolves_tag_from_gh` — patch `updater.dark_factory_handler.resolve_latest_claude_yolo_tag` → `"v0.16.0"`; run with `claude_yolo_tag=None`, `dry_run=True` → 0; file patched to `v0.16.0`.
8. `test_run_resolution_failure` — patch `resolve_latest_claude_yolo_tag` to raise `RuntimeError("gh: not authenticated")` → 1; file untouched.
9. `test_run_real_opens_pr` — patch `find_existing_pull_request` → None, `git_checkout_new_branch`, `git_commit`, `git_push`, `create_pull_request` → URL; run with `claude_yolo_tag="v0.16.0"` → 0; assert PR created with branch `updater/dark-factory-v0.16.0` and title `chore: bump DefaultContainerImage to claude-yolo:v0.16.0`.
10. `test_run_real_already_current` — fixture at `v0.16.0`; run → 0; no PR call.
11. `test_run_real_existing_pr` — patch `find_existing_pull_request` → URL → 0; no new PR; file untouched.
12. `test_run_pattern_not_found` — fixture `pkg/const.go` with `DefaultContainerImage = "docker.io/bborbe/claude-yolo:v0.15.1-extra"` (or a differently-shaped const line) → 1; error names `pkg/const.go` and the pattern.
13. `test_run_dirty_checkout_aborts` — uncommitted change → 1; file untouched.

### `tests/test_cli.py` (append)

14. `test_dark_factory_subcommand_dispatch` — `sys.argv = ["updater", "dark-factory", str(tmp_path), "--dry-run", "--claude-yolo-tag", "v0.16.0"]`; patch `updater.cli.DarkFactoryHandler` (`.return_value.run.return_value = 0`); assert exit 0 and `run` called with `Path(str(tmp_path))`, `dry_run=True`, `claude_yolo_tag="v0.16.0"`.

Coverage: `dark_factory_handler` ≥80% statement coverage (`uv run --with pytest-cov pytest --cov=updater.dark_factory_handler --cov-report=term-missing`).
</requirements>

<constraints>
- Handlers live in `src/updater/` as modules (NO `handlers/` dir); CLI wiring goes in `cli.py`.
- Reuse the shared helper in `src/updater/infra_tier.py` — do NOT duplicate `process_infra_target` or any of its internals in the handler module.
- Reuse existing `git_operations.py` and `config.py` — no new bespoke git implementation.
- Target files are frozen per `docs/infra-tier-targets.md`; dark-factory is `pkg/const.go` `DefaultContainerImage = "docker.io/bborbe/claude-yolo:vA.B.C"` (tracks claude-yolo's release tag, NOT the Go version directly).
- The handler's target-version input (`--claude-yolo-tag`, or the resolved tag) is validated against the `^v\d+\.\d+\.\d+$` regex BEFORE interpolation into any patch, branch name, title, body, or git command — no shell injection / path traversal.
- If claude-yolo's latest release cannot be resolved (network/gh), the handler fails fast with the resolution error and touches nothing (spec failure mode).
- PRs use the conventional `chore:` / `feat:` prefix and a `## Unreleased` CHANGELOG bullet per repo (autoRelease repos need the bullet) — the real run adds the bullet via `add_to_unreleased` inside `process_infra_target`.
- The only write path is a PR (reviewable, reversible); no handler pushes directly to a target's master.
- No secrets (gh tokens, clone URLs with credentials) are written to PR bodies or logs; git operations use `git_operations.py`'s ambient-credential handling, never inline credentials.
- Handler invocation order for the state machine is owned by the sibling [[Build Trigger Ordering State Machine]] spec — this handler is independently invocable.
- `make precommit` stays green; existing tests unchanged.
- Follow project Python conventions (pytest, type hints, uv, Google-style docstrings); no `print` — use `log_message()`; no new dependencies.
- Do NOT commit — dark-factory handles git.
- Do NOT modify `pipeline.py`, `go_updater.py`, `docker_updater.py`, `python_updater.py`, `gomod_excludes.py`, `cli.py`'s other subcommands, or `infra_tier.py` / `git_operations.py` (they were shipped by the prior prompt).
</constraints>

<verification>
Run `make precommit` — must exit 0 (sync + format + test + lint + typecheck).

Confirm the handler module and class exist:
```
grep -n 'DarkFactoryHandler' src/updater/dark_factory_handler.py
```

Confirm the CLI subcommand exists:
```
grep -n 'dark-factory' src/updater/cli.py
```

Manual dry-run against a scratch fixture (produces the spec's AC #3 container evidence). Run from the repo root:
```
rm -rf /tmp/dark-factory-fixture && mkdir -p /tmp/dark-factory-fixture/pkg && cd /tmp/dark-factory-fixture && git init -q && git config user.email u@test && git config user.name u && printf 'const DefaultContainerImage = "docker.io/bborbe/claude-yolo:v0.15.1"\n' > pkg/const.go && git add pkg/const.go && git commit -qm init && cd - && uv run updater dark-factory /tmp/dark-factory-fixture --dry-run --claude-yolo-tag v0.16.0 && cd /tmp/dark-factory-fixture && git diff --name-only
```
The dry-run output must show the before/after constant (`v0.15.1 → v0.16.0`) and the final `git diff --name-only` must print exactly `pkg/const.go`.

Coverage check for the new module (≥80%):
```
uv run --with pytest-cov pytest --cov=updater.dark_factory_handler --cov-report=term-missing tests/test_dark_factory_handler.py
```
</verification>

<completion_report_template>
Append the standard DARK-FACTORY-REPORT block with `status`, `verification.command`, `verification.exitCode`. Then an `## Improvements` section (PROMPT / GUIDE / GLOBAL categories, or `- None`).
</completion_report_template>
