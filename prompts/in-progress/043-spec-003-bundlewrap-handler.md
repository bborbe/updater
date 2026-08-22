---
status: approved
spec: [003-infra-tier-special-case-handlers]
created: "2026-08-22T21:50:00Z"
queued: "2026-08-22T21:19:40Z"
---

# BundleWrap infra-tier handler

<summary>
- A new `updater bundlewrap` subcommand bumps `default_golang_version` in the BundleWrap repo's `bundles/golang/items.py` and, on a real run, opens a PR in the BundleWrap repo
- `--dry-run` prints the intended diff (file, constant before/after) and modifies only `bundles/golang/items.py`'s working tree — no branch, no commit, no PR
- The target Go version is supplied via `--go-version`, validated against an `X.Y.Z` regex before it is used anywhere
- A run against an already-current target exits 0 with no diff and no PR (idempotent)
- A real run against a target that already has an open `head:updater` PR exits 0 without opening a new one, reporting the existing PR's URL instead
- Reuses the shared patch-and-PR helper (`process_infra_target`) extracted by the claude-yolo prompt — no duplicated logic
</summary>

<objective>
Add the BundleWrap infra-tier handler as a new `updater bundlewrap` subcommand so the fleet-wide bump can cover the BundleWrap repo's `bundles/golang/items.py` `default_golang_version` constant.
</objective>

<context>
Read `/workspace/CLAUDE.md` for project conventions.

Read the frozen target map: `/workspace/docs/infra-tier-targets.md` (BundleWrap row). The BundleWrap frozen target is `bundles/golang/items.py` `default_golang_version = 'X.Y.Z'` (current value `'1.27.0'`).

Read these files fully before editing:
- `/workspace/src/updater/infra_tier.py` — the shared helper from the claude-yolo prompt: `process_infra_target(checkout, *, repo, target_file, pattern, new_value, branch_name, title, body, changelog_bullet, dry_run) -> int`, `validate_go_version`. REUSE these — do not reimplement.
- `/workspace/src/updater/claude_yolo_handler.py` — the handler shape to mirror (module constants + `XxxHandler` class with a `run` method).
- `/workspace/src/updater/cli.py` — `main_updater_async` subparser construction + dispatch chain (the `claude-yolo` subcommand is the template).
- `/workspace/tests/test_claude_yolo_handler.py` and `/workspace/tests/test_infra_tier.py` — test style for handler tests.
- `/workspace/tests/conftest.py` — the `tmp_git_repo` fixture.

Reference docs (in-container paths):
- `/home/node/.claude/plugins/marketplaces/coding/docs/python-cli-arguments-guide.md`
- `/home/node/.claude/plugins/marketplaces/coding/docs/python-logging-guide.md`

OPEN QUESTIONS FOR THE REVIEWER (resolved as best-effort below):
- The spec's target map lists the repo as "BundleWrap repo" and the AC probe uses a `<bw-repo>` placeholder, so the repo slug is not pinned in the spec. This prompt uses `bw2/BundleWrap` (the canonical upstream). If bborbe maintains a fork, change `BUNDLEWRAP_REPO` in the handler (and in the test assertions) to that fork before approving — the change is a one-constant edit.
</context>

<requirements>

## 1. Create `src/updater/bundlewrap_handler.py`

```python
"""Infra-tier handler for BundleWrap's default_golang_version constant."""

import re
from pathlib import Path

from .infra_tier import process_infra_target, validate_go_version
from .log_manager import log_message

BUNDLEWRAP_REPO = "bw2/BundleWrap"
BUNDLEWRAP_FILE = "bundles/golang/items.py"
BUNDLEWRAP_PATTERN = re.compile(r"^default_golang_version = '(\d+\.\d+\.\d+)'$")


class BundleWrapHandler:
    """Bump default_golang_version in BundleWrap's bundles/golang/items.py and open a PR."""

    def run(self, checkout: Path, *, dry_run: bool, go_version: str) -> int:
        if not validate_go_version(go_version):
            log_message(f"✗ Invalid Go version: {go_version!r} (expected X.Y.Z)", to_console=True)
            return 1
        return process_infra_target(
            checkout,
            repo=BUNDLEWRAP_REPO,
            target_file=BUNDLEWRAP_FILE,
            pattern=BUNDLEWRAP_PATTERN,
            new_value=go_version,
            branch_name=f"updater/bundlewrap-{go_version}",
            title=f"chore: bump default_golang_version to {go_version}",
            body=f"Bump default_golang_version to {go_version}.",
            changelog_bullet=f"chore: bump default_golang_version to {go_version}",
            dry_run=dry_run,
        )
```

`process_infra_target` reads the current value (group 1 = `1.27.0`), compares to the target, patches via its generic group-1 replacement (preserving `default_golang_version = '` … `'`), and runs the branch/commit/push/PR flow on a real run. Do not duplicate any of that here.

## 2. Wire the CLI in `src/updater/cli.py`

In `main_updater_async`:
- Add the import: `from .bundlewrap_handler import BundleWrapHandler`.
- AFTER the existing handler subparsers, add:
```python
sub = subparsers.add_parser(
    "bundlewrap",
    help="Bump default_golang_version in BundleWrap bundles/golang/items.py and open a PR",
)
sub.add_argument("path", help="Path to the BundleWrap checkout")
sub.add_argument("--dry-run", action="store_true", help="Show the diff and exit without opening a PR")
sub.add_argument(
    "--go-version",
    required=True,
    metavar="X.Y.Z",
    help="Target Go version to set in default_golang_version (e.g. 1.28.0)",
)
```
- In the dispatch chain add:
```python
elif args.subcommand == "bundlewrap":
    return BundleWrapHandler().run(
        Path(args.path), dry_run=args.dry_run, go_version=args.go_version
    )
```
- In the final `else` branch, `valid` is derived from `_sub_descs` (`valid = ", ".join(_sub_descs.keys())` in cli.py). Extend the derived value with the handler subcommand WITHOUT adding it to `_sub_descs` (adding it would give it the wrong positional and create a conflicting subparser): `valid = ", ".join([*_sub_descs.keys(), "bundlewrap"])`.

Do NOT touch the other subcommands.

## 3. CHANGELOG

Add (or append to) the `## Unreleased` section in the updater repo's CHANGELOG.md:
`- feat: Add infra-tier BundleWrap handler (updater bundlewrap) — bumps default_golang_version`

## 4. Tests — `tests/test_bundlewrap_handler.py` (new file)

Use the `tmp_git_repo` fixture; commit the target file so the worktree is clean. Mock gh and git push/PR by patching the names imported into the modules under test. For dry-run diff tests, let the real `git` binary run against the fixture (real subprocess boundary).

Fixture file content for `bundles/golang/items.py`:
```
default_golang_version = '1.27.0'
```
(create the `bundles/golang` directories, write the file, `git add` + `git commit`).

1. `test_run_dry_run_bumps_default_golang_version` — `run(repo, dry_run=True, go_version="1.28.0")` → 0; file now `'1.28.0'`; real `git diff --name-only` == `["bundles/golang/items.py"]`. Assert no `gh`/push/PR functions called (patch the git_operations functions as spies).
2. `test_run_dry_run_up_to_date` — fixture already at `1.28.0`; run with `1.28.0` → 0; diff empty.
3. `test_run_invalid_go_version` — `"1.28"` → 1; file untouched.
4. `test_run_real_opens_pr` — patch `find_existing_pull_request` → None, `git_checkout_new_branch`, `git_commit`, `git_push`, `create_pull_request` → URL; run → 0; assert PR created with branch `updater/bundlewrap-1.28.0` and title `chore: bump default_golang_version to 1.28.0`.
5. `test_run_real_already_current` — fixture at `1.28.0`; run → 0; no PR call.
6. `test_run_real_existing_pr` — patch `find_existing_pull_request` → URL → 0; no new PR; file untouched.
7. `test_run_pattern_not_found` — fixture with `default_golang_version = "1.27.0"` (double quotes) → 1; error names `bundles/golang/items.py` and the pattern.
8. `test_run_dirty_checkout_aborts` — uncommitted change → 1; file untouched.

### `tests/test_cli.py` (append)

9. `test_bundlewrap_subcommand_dispatch` — `sys.argv = ["updater", "bundlewrap", str(tmp_path), "--dry-run", "--go-version", "1.28.0"]`; patch `updater.cli.BundleWrapHandler` (`.return_value.run.return_value = 0`); assert exit 0 and `run` called with `Path(str(tmp_path))`, `dry_run=True`, `go_version="1.28.0"`.

Coverage: `bundlewrap_handler` ≥80% statement coverage (`uv run --with pytest-cov pytest --cov=updater.bundlewrap_handler --cov-report=term-missing`).
</requirements>

<constraints>
- Handlers live in `src/updater/` as modules (NO `handlers/` dir); CLI wiring goes in `cli.py`.
- Reuse the shared helper in `src/updater/infra_tier.py` — do NOT duplicate `process_infra_target` or any of its internals in the handler module.
- Reuse existing `git_operations.py` and `config.py` — no new bespoke git implementation.
- Target files are frozen per `docs/infra-tier-targets.md`; BundleWrap is `bundles/golang/items.py` `default_golang_version = 'X.Y.Z'`.
- `--go-version` (the handler's target-version input) is validated against the `X.Y.Z` regex BEFORE interpolation into any patch, branch name, title, body, or git command — no shell injection / path traversal.
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
grep -n 'BundleWrapHandler' src/updater/bundlewrap_handler.py
```

Confirm the CLI subcommand exists:
```
grep -n 'bundlewrap' src/updater/cli.py
```

Manual dry-run against a scratch fixture (produces the spec's AC #5 container evidence). Run from the repo root:
```
rm -rf /tmp/bundlewrap-fixture && mkdir -p /tmp/bundlewrap-fixture/bundles/golang && cd /tmp/bundlewrap-fixture && git init -q && git config user.email u@test && git config user.name u && printf "default_golang_version = '1.27.0'\n" > bundles/golang/items.py && git add bundles/golang/items.py && git commit -qm init && cd - && uv run updater bundlewrap /tmp/bundlewrap-fixture --dry-run --go-version 1.28.0 && cd /tmp/bundlewrap-fixture && git diff --name-only
```
The dry-run output must show the before/after constant (`1.27.0 → 1.28.0`) and the final `git diff --name-only` must print exactly `bundles/golang/items.py`.

Coverage check for the new module (≥80%):
```
uv run --with pytest-cov pytest --cov=updater.bundlewrap_handler --cov-report=term-missing tests/test_bundlewrap_handler.py
```
</verification>

<completion_report_template>
Append the standard DARK-FACTORY-REPORT block with `status`, `verification.command`, `verification.exitCode`. Then an `## Improvements` section (PROMPT / GUIDE / GLOBAL categories, or `- None`).
</completion_report_template>
