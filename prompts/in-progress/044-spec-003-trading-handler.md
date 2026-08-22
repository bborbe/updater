---
status: approved
spec: [003-infra-tier-special-case-handlers]
created: "2026-08-22T21:55:00Z"
queued: "2026-08-22T21:19:40Z"
---

# trading infra-tier handler

<summary>
- A new `updater trading` subcommand bumps the `go X.Y.Z` constant in the trading monorepo's `Makefile.folder` and, on a real run, opens a PR in `bborbe/trading`
- `--dry-run` patches `Makefile.folder` in the provided checkout and prints the intended diff — no worktree, no `make ensurecommit`, no PR (so the dry-run diff touches exactly `Makefile.folder`)
- A real run follows the trading repo's canonical pattern: feature worktree from `master`, bump `Makefile.folder`, run `make ensurecommit` (which propagates the version to every per-module Makefile/config), commit, push, and open the PR
- The temporary worktree is always removed after the run (success or failure) — no stale worktrees accumulate
- A run against an already-current target exits 0 with no diff and no PR (idempotent)
- A real run against a target that already has an open `head:updater` PR exits 0 without opening a new one, reporting the existing PR's URL instead
- Reuses the shared patch-and-PR primitives (clean-check, read/require current value, patch, existing-PR lookup, PR creation) from `infra_tier.py` and `git_operations.py` — no duplicated logic
</summary>

<objective>
Add the trading infra-tier handler as a new `updater trading` subcommand so the fleet-wide bump can cover the trading monorepo's `Makefile.folder` `go X.Y.Z` constant via the repo's feature-worktree + `make ensurecommit` canonical pattern.
</objective>

<context>
Read `/workspace/CLAUDE.md` for project conventions.

Read the frozen target map: `/workspace/docs/infra-tier-targets.md` (trading row + the "trading monorepo — the 2026-06-03 canonical pattern" section). The trading frozen target is `bborbe/trading` `Makefile.folder` `go X.Y.Z` constant; the real run MUST use the canonical pattern: create a feature worktree from `master`, bump the constant, run `make ensurecommit` in that worktree (propagates the version to every per-module Makefile/config), then open a PR.

Read these files fully before editing:
- `/workspace/src/updater/infra_tier.py` — the shared primitives from the claude-yolo prompt: `process_infra_target(...) -> int`, `require_clean_worktree`, `read_current_value`, `patch_file`, `InfraTargetError`, `validate_go_version`. REUSE these — do not reimplement.
- `/workspace/src/updater/claude_yolo_handler.py` — the handler shape to mirror (module constants + `XxxHandler` class with a `run` method).
- `/workspace/src/updater/cli.py` — `main_updater_async` subparser construction + dispatch chain (the `claude-yolo` subcommand is the template).
- `/workspace/src/updater/git_operations.py` — `git_commit`, `git_push`, `find_existing_pull_request`, `create_pull_request`, `check_git_status`; `/workspace/src/updater/changelog.py` — `add_to_unreleased`; `/workspace/src/updater/log_manager.py` — `run_command` (raises `RuntimeError` on non-zero exit).
- `/workspace/tests/test_claude_yolo_handler.py` and `/workspace/tests/test_infra_tier.py` — test style for handler tests.
- `/workspace/tests/conftest.py` — the `tmp_git_repo` fixture.

Reference docs (in-container paths):
- `/home/node/.claude/plugins/marketplaces/coding/docs/python-cli-arguments-guide.md`
- `/home/node/.claude/plugins/marketplaces/coding/docs/python-logging-guide.md`

OPEN QUESTIONS FOR THE REVIEWER (resolved as best-effort below):
- The exact `go X.Y.Z` line shape inside the real `Makefile.folder` is not pinned by the spec (only "`go X.Y.Z` constant"). This prompt's pattern is line-anchored `^go (\d+\.\d+\.\d+)$`. The operator should verify this matches the real file on the first real-target dry-run; if the line differs, adjust `TRADING_PATTERN` only.
- The worktree is created from `master` per the canonical pattern; if the repo's default branch is ever renamed, `master` in the worktree-add command must follow.
- The real run adds the `## Unreleased` bullet only if the checkout root has a CHANGELOG.md (`add_to_unreleased` skips otherwise). The trading monorepo may use per-module changelogs — confirm this matches the repo convention at review time.
</context>

<requirements>

## 1. Create `src/updater/trading_handler.py`

```python
"""Infra-tier handler for the bborbe/trading monorepo's Makefile.folder Go version."""

import re
import tempfile
from pathlib import Path

from .changelog import add_to_unreleased
from .git_operations import (
    create_pull_request,
    find_existing_pull_request,
    git_commit,
    git_push,
)
from .infra_tier import (
    InfraTargetError,
    patch_file,
    process_infra_target,
    read_current_value,
    require_clean_worktree,
    validate_go_version,
)
from .log_manager import log_message, run_command

TRADING_REPO = "bborbe/trading"
TRADING_FILE = "Makefile.folder"
TRADING_PATTERN = re.compile(r"^go (\d+\.\d+\.\d+)$")


class TradingHandler:
    """Bump the Go version in bborbe/trading Makefile.folder and open a PR."""

    def run(self, checkout: Path, *, dry_run: bool, go_version: str) -> int:
        """Implement as described below."""
```

Implement `run` as follows:

- If `not validate_go_version(go_version)`: log `"✗ Invalid Go version: {go_version!r} (expected X.Y.Z)"` and return 1.
- If `dry_run`: delegate to the shared dry-run flow on the PRIMARY checkout (no worktree, no `make ensurecommit`):
  `return process_infra_target(checkout, repo=TRADING_REPO, target_file=TRADING_FILE, pattern=TRADING_PATTERN, new_value=go_version, branch_name=f"updater/trading-go-{go_version}", title=..., body=..., changelog_bullet=..., dry_run=True)`
  using the title/body/bullet from the constants below. This patches `Makefile.folder` in the working tree and shows the diff — AC evidence: `git diff --name-only` == exactly `Makefile.folder`.
- Real run (numbered flow; wrap the whole body in `try/except (InfraTargetError, RuntimeError) as e` that logs the error and returns 1):
  1. `require_clean_worktree(checkout)` — aborts BEFORE touching anything if the primary checkout has uncommitted changes (spec failure mode).
  2. `current = read_current_value(checkout, TRADING_FILE, TRADING_PATTERN)`; if `current is None` log `"pattern not found: {TRADING_PATTERN.pattern} in {TRADING_FILE}"` and return 1.
  3. If `current == go_version`: log `"Makefile.folder already up to date ({go_version})"` and return 0.
  4. `existing = find_existing_pull_request(checkout, TRADING_REPO)`; if truthy log `"existing updater PR: {existing}"` and return 0.
  5. `branch = f"updater/trading-go-{go_version}"`. Create the worktree: `worktree = Path(tempfile.mkdtemp(prefix=f"{checkout.name}-trading-wt-"))` then `run_command(f"git worktree add -b {branch} {worktree} master", cwd=checkout, quiet=True, log_func=log_message)`.
  6. `try:` patch + propagate + changelog + commit + push + PR:
     - `patch_file(worktree, TRADING_FILE, TRADING_PATTERN, go_version)`
     - `run_command("make ensurecommit", cwd=worktree, quiet=True, log_func=log_message)` — propagates the version to every per-module Makefile/config (the canonical pattern). If this fails, the whole run fails.
     - `add_to_unreleased(worktree, {"changelog": [f"chore: bump Go version to {go_version}"]}, log_func=log_message)` — skips if the worktree has no root CHANGELOG.md.
     - `git_commit(worktree, f"chore: bump Go version to {go_version}", log_func=log_message)`
     - `git_push(worktree, log_func=log_message)`
     - `pr_url = create_pull_request(worktree, TRADING_REPO, branch, f"chore: bump Go version to {go_version}", f"Bump the Go version constant in Makefile.folder to {go_version} and run make ensurecommit.", log_func=log_message)`
     - log `"PR opened: {pr_url}"` and return 0.
     `finally:` `run_command(f"git worktree remove --force {worktree}", cwd=checkout, quiet=True, log_func=log_message)` — ALWAYS remove the temporary worktree after push (success or failure); the branch stays on origin, so the PR is unaffected.

Use the branch `updater/trading-go-{go_version}` (starts with `updater` so the spec's `head:updater` probe matches), title `chore: bump Go version to {go_version}`, body `Bump the Go version constant in Makefile.folder to {go_version} and run make ensurecommit.`, changelog bullet `chore: bump Go version to {go_version}`.

No partial PR: the change is committed and pushed only on the feature branch; a `gh` failure leaves the branch pushed with no PR, which is reversible.

## 2. Wire the CLI in `src/updater/cli.py`

In `main_updater_async`:
- Add the import: `from .trading_handler import TradingHandler`.
- AFTER the existing handler subparsers, add:
```python
sub = subparsers.add_parser(
    "trading",
    help="Bump the Go version in bborbe/trading Makefile.folder and open a PR",
)
sub.add_argument("path", help="Path to the bborbe/trading checkout")
sub.add_argument("--dry-run", action="store_true", help="Show the diff and exit without opening a PR")
sub.add_argument(
    "--go-version",
    required=True,
    metavar="X.Y.Z",
    help="Target Go version to set in Makefile.folder (e.g. 1.28.0)",
)
```
- In the dispatch chain add:
```python
elif args.subcommand == "trading":
    return TradingHandler().run(
        Path(args.path), dry_run=args.dry_run, go_version=args.go_version
    )
```
- In the final `else` branch, `valid` is derived from `_sub_descs` (`valid = ", ".join(_sub_descs.keys())` in cli.py). Extend the derived value with the handler subcommand WITHOUT adding it to `_sub_descs` (adding it would give it the wrong positional and create a conflicting subparser): `valid = ", ".join([*_sub_descs.keys(), "trading"])`.

Do NOT touch the other subcommands.

## 3. CHANGELOG

Add (or append to) the `## Unreleased` section in the updater repo's CHANGELOG.md:
`- feat: Add infra-tier trading handler (updater trading) — Makefile.folder bump via feature worktree + make ensurecommit`

## 4. Tests — `tests/test_trading_handler.py` (new file)

Use the `tmp_git_repo` fixture; commit the target file so the worktree is clean. Mock gh and push by patching the names imported into the modules under test.

Fixture file content for `Makefile.folder`:
```
go 1.27.0
```
(commit it with `git add` + `git commit`).

1. `test_run_dry_run_bumps_makefile_folder` — `run(repo, dry_run=True, go_version="1.28.0")` → 0; file now `go 1.28.0`; real `git diff --name-only` == `["Makefile.folder"]`; assert NO `make ensurecommit` was invoked (patch `run_command` and assert no call contains `make ensurecommit`).
2. `test_run_dry_run_up_to_date` — fixture at `1.28.0`; run with `1.28.0` → 0; diff empty.
3. `test_run_invalid_go_version` — `"1.28"` → 1; file untouched.
4. `test_run_real_opens_pr` (mocked command sequence) — patch `run_command`, `find_existing_pull_request` → None, `git_commit`, `git_push`, `create_pull_request` → URL. Run real flow → 0. Assert:
   - `run_command` was called with a `git worktree add -b updater/trading-go-1.28.0 ... master` command, a `make ensurecommit` command whose `cwd` is the worktree path, and a `git worktree remove --force ...` command;
   - `create_pull_request` was called with repo `bborbe/trading`, branch `updater/trading-go-1.28.0`, title `chore: bump Go version to 1.28.0`.
5. `test_run_real_already_current` — fixture at `1.28.0`; run → 0; no worktree, no PR (assert `run_command` has no `worktree`/`gh` calls and `create_pull_request` not called).
6. `test_run_real_existing_pr` — patch `find_existing_pull_request` → URL → 0; no worktree, no new PR; file untouched.
7. `test_run_real_pattern_not_found` — fixture `Makefile.folder` containing `GO_VERSION := 1.27.0` (different shape) → 1; error names `Makefile.folder` and the pattern.
8. `test_run_real_dirty_checkout_aborts` — uncommitted change in the primary checkout → 1; file untouched; no worktree created.
9. `test_run_real_ensurecommit_failure_removes_worktree` — patch `run_command` such that the `make ensurecommit` call raises `RuntimeError`; assert return 1 AND `git worktree remove --force` was still invoked (worktree cleanup runs even on failure).
10. `test_run_real_worktree_flow_with_real_git` (boundary — real `git worktree` subprocess) — use `tmp_git_repo` with a committed `Makefile.folder` on `master`. IMPORTANT: pin the fixture's default branch so `master` exists — the `tmp_git_repo` fixture does bare `git init` and may default to `main`; if the fixture doesn't pin `-b master`, create the branch explicitly (e.g. `git init -b master` in a dedicated fixture, or `git checkout -b master` after init) before committing. Patch `updater.trading_handler.run_command` with a `side_effect` function that calls the real `run_command` for git commands and returns a success `subprocess.CompletedProcess` for the `make ensurecommit` call (capture the real function before patching: `from updater.log_manager import run_command as real_run`). Patch `updater.trading_handler.git_push` and `updater.trading_handler.create_pull_request` (→ URL) so no remote is needed. Assert return 0 and that the branch `updater/trading-go-1.28.0` was created, `Makefile.folder` in the worktree contains `go 1.28.0`, and the worktree dir no longer exists after the run.

### `tests/test_cli.py` (append)

11. `test_trading_subcommand_dispatch` — `sys.argv = ["updater", "trading", str(tmp_path), "--dry-run", "--go-version", "1.28.0"]`; patch `updater.cli.TradingHandler` (`.return_value.run.return_value = 0`); assert exit 0 and `run` called with `Path(str(tmp_path))`, `dry_run=True`, `go_version="1.28.0"`.

Coverage: `trading_handler` ≥80% statement coverage (`uv run --with pytest-cov pytest --cov=updater.trading_handler --cov-report=term-missing`).
</requirements>

<constraints>
- Handlers live in `src/updater/` as modules (NO `handlers/` dir); CLI wiring goes in `cli.py`.
- Reuse the shared primitives in `src/updater/infra_tier.py` and `src/updater/git_operations.py` — do NOT duplicate the patch/clean-check/PR logic in the handler module.
- Reuse existing `git_operations.py` and `config.py` — no new bespoke git implementation.
- Target files are frozen per `docs/infra-tier-targets.md`; trading is `Makefile.folder` `go X.Y.Z` + per-module `make ensurecommit` (the 2026-06-03 canonical pattern: feature worktree from `master` + `make ensurecommit`).
- `--go-version` (the handler's target-version input) is validated against the `X.Y.Z` regex BEFORE interpolation into any patch, branch name, title, body, or git command — no shell injection / path traversal.
- The real run applies the patch in a feature worktree (never edits `Makefile.folder` in the primary working tree directly), runs `make ensurecommit`, and opens a PR.
- PRs use the conventional `chore:` / `feat:` prefix and a `## Unreleased` CHANGELOG bullet per repo (autoRelease repos need the bullet).
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
grep -n 'TradingHandler' src/updater/trading_handler.py
```

Confirm the CLI subcommand exists:
```
grep -n 'trading' src/updater/cli.py
```

Confirm all four handler modules are present (spec's cumulative grep):
```
grep -ln 'Handler' src/updater/*_handler.py
```
Must list `claude_yolo_handler.py`, `dark_factory_handler.py`, `bundlewrap_handler.py`, `trading_handler.py`.

Manual dry-run against a scratch fixture (produces the spec's AC #7 container evidence). Run from the repo root:
```
rm -rf /tmp/trading-fixture && mkdir -p /tmp/trading-fixture && cd /tmp/trading-fixture && git init -q -b master && git config user.email u@test && git config user.name u && printf 'go 1.27.0\n' > Makefile.folder && git add Makefile.folder && git commit -qm init && cd - && uv run updater trading /tmp/trading-fixture --dry-run --go-version 1.28.0 && cd /tmp/trading-fixture && git diff --name-only
```
The dry-run output must show the before/after constant (`1.27.0 → 1.28.0`) and the final `git diff --name-only` must print exactly `Makefile.folder` (no `make ensurecommit` in a dry run).

Coverage check for the new module (≥80%):
```
uv run --with pytest-cov pytest --cov=updater.trading_handler --cov-report=term-missing tests/test_trading_handler.py
```
</verification>

<completion_report_template>
Append the standard DARK-FACTORY-REPORT block with `status`, `verification.command`, `verification.exitCode`. Then an `## Improvements` section (PROMPT / GUIDE / GLOBAL categories, or `- None`).
</completion_report_template>
