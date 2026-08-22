---
status: completed
spec: [003-infra-tier-special-case-handlers]
summary: Implemented updater claude-yolo infra-tier handler, shared infra_tier patch-and-PR helper, three new git_operations primitives, CLI wiring, CHANGELOG entry, and 36 tests; make precommit exits 0
execution_id: updater-exec-041-spec-003-claude-yolo-handler
dark-factory-version: dev
created: "2026-08-22T21:40:00Z"
queued: "2026-08-22T21:19:40Z"
started: "2026-08-22T21:57:15Z"
completed: "2026-08-22T21:59:05Z"
---

# claude-yolo infra-tier handler, shared patch-and-PR helper, and CLI wiring

<summary>
- A new `updater claude-yolo` subcommand bumps `ARG GO_VERSION` in a claude-yolo checkout and, on a real run, opens a PR in `bborbe/claude-yolo`
- `--dry-run` prints the intended diff (file, constant before/after) and modifies only the target file's working tree — no branch, no commit, no PR
- A run against an already-current target exits 0 with no diff and no PR (idempotent)
- A real run against a target that already has an open `head:updater` PR exits 0 without opening a new one, reporting the existing PR's URL instead
- The target-version input is validated against an `X.Y.Z` regex before it is interpolated into any patch, branch name, title, or git command — no shell injection
- The shared patch-and-PR machinery (clean-check → read constant → patch → diff → branch → commit → push → PR) is extracted into one reusable module that the dark-factory, BundleWrap, and trading handlers in later prompts reuse unchanged
- Feature-branch checkout, existing-PR lookup, and PR creation are added as functions to the existing git-operations module — no new bespoke git implementation
- The CLI wiring follows the existing unified-subcommand pattern; the existing eight subcommands are untouched and still pass their tests
</summary>

<objective>
Add the claude-yolo infra-tier handler as a new `updater claude-yolo` subcommand so the fleet-wide Go bump can cover `bborbe/claude-yolo`'s `Dockerfile` `ARG GO_VERSION` automatically, and extract the shared patch-and-PR machinery that the remaining three infra-tier handlers will reuse.
</objective>

<context>
Read `/workspace/CLAUDE.md` for project conventions (Python, uv + hatchling, pytest, dark-factory flow, changelog rules).

Read the frozen target map: `/workspace/docs/infra-tier-targets.md` (claude-yolo row, handler-module convention section). The claude-yolo frozen target is `bborbe/claude-yolo` `Dockerfile` `ARG GO_VERSION=X.Y.Z` (current value 1.27.0).

Read these files fully before editing:
- `/workspace/src/updater/cli.py` — `main_updater_async`: the `subparsers = parser.add_subparsers(dest="subcommand", ...)` construction, the `_sub_descs` loop that adds a `modules` positional to the existing subcommands, the `if args.subcommand == ...` dispatch chain, and `main_updater`/`main_updater_async` entry points. `Path` is already imported.
- `/workspace/src/updater/git_operations.py` — existing primitives `find_git_repo`, `check_git_status`, `git_commit`, `git_push`; the module's function + `log_func` convention and the import-`run_command`-inside-the-function style. There is currently NO branch-creation or PR function here.
- `/workspace/src/updater/log_manager.py` — `log_message(message, to_console=True)` and `run_command(cmd, cwd=None, capture_output=False, quiet=False, log_func=log_message)`. IMPORTANT: `run_command` RAISES `RuntimeError` on non-zero exit.
- `/workspace/src/updater/docker_updater.py` and `/workspace/src/updater/version_updater.py` — the function-module + `log_func: Callable[..., None] = log_message` default-param pattern, and `re`-based constant patching style.
- `/workspace/src/updater/pipeline.py` — the class-based Step convention (constructor + `run` method, config/logging/git-ops reuse) that the handler module matches IN SPIRIT. The handlers are standalone subcommands with CLI args, NOT `Step` subclasses and NOT part of a module pipeline.
- `/workspace/src/updater/changelog.py` — `add_to_unreleased(module_path, analysis, log_func)` — appends a `## Unreleased` bullet from `analysis["changelog"]` and skips when the repo has no CHANGELOG.md.
- `/workspace/tests/conftest.py` — the `tmp_git_repo` fixture (creates a real git repo with user configured); `/workspace/tests/test_git_operations.py`, `/workspace/tests/test_cli.py`, `/workspace/tests/test_docker_updater.py` — test conventions (pytest, `unittest.mock.patch`, `tmp_path`/`tmp_git_repo`, no real network).

Reference docs (in-container paths — the executor container runs from `/home/node`):
- `/home/node/.claude/plugins/marketplaces/coding/docs/python-cli-arguments-guide.md` — CLI subcommand/argument conventions
- `/home/node/.claude/plugins/marketplaces/coding/docs/python-project-structure.md` — `src/` layout
- `/home/node/.claude/plugins/marketplaces/coding/docs/python-logging-guide.md` — logging conventions

OPEN QUESTIONS FOR THE REVIEWER (resolved as best-effort below):
- The shared helper lives in `src/updater/infra_tier.py` as module-level functions; the handler is a class. This matches the repo's function-module pattern (docker_updater.py) for the helper and the class pattern (pipeline.py Steps) for the handler.
- Dry-run writes the patch to the working tree (unstaged) so `git diff --name-only` can serve as the AC negative evidence. The operator restores with `git checkout -- <file>` after reviewing.
</context>

<requirements>

## 1. Add git primitives to `src/updater/git_operations.py`

Add `import json` at the top of the module. Add `from .log_manager import log_message` at the top (the module currently imports only `from . import config`).

Add three functions, following the existing function + `log_func` convention (`run_command` imported inside each function from `.log_manager`, as `git_commit` and `git_push` do):

```python
def git_checkout_new_branch(
    module_path: Path, branch_name: str, log_func: Callable[..., None] = log_message
) -> None:
    """Create and switch to a new feature branch from the current HEAD."""

def find_existing_pull_request(
    module_path: Path, repo: str, log_func: Callable[..., None] = log_message
) -> str | None:
    """Return the URL of the first open PR whose head branch matches 'updater', or None."""

def create_pull_request(
    module_path: Path,
    repo: str,
    branch: str,
    title: str,
    body: str,
    log_func: Callable[..., None] = log_message,
) -> str:
    """Open a pull request via gh for branch in repo. Returns the PR URL."""
```

Behavior:
- `git_checkout_new_branch`: `run_command(f"git checkout -b {branch_name}", cwd=module_path, quiet=True, log_func=log_func)`. `branch_name` is always a controlled constant built from a regex-validated version (see requirement 2) — never a free-form user string.
- `find_existing_pull_request`: run `run_command(f'gh pr list --repo {repo} --search "head:updater" --state open --json url', cwd=module_path, capture_output=True, quiet=True, log_func=log_func)`. Parse `result.stdout` as JSON (tolerate empty stdout → treat as `[]`). Return the first entry's `url` field, or `None`. Let `RuntimeError` from `run_command` propagate — callers convert it to an error exit.
- `create_pull_request`: run `run_command(f'gh pr create --repo {repo} --head {branch} --title "{title}" --body "{body}"', cwd=module_path, capture_output=True, quiet=True, log_func=log_func)`. Return `result.stdout.strip()` (the PR URL). `repo`/`branch` are constants and `title`/`body` are constants plus a regex-validated version/tag, so no shell-injection surface exists. Let `RuntimeError` propagate.

These functions use plain `gh` with the ambient credential helper — no inline tokens, no secrets in any argument.

## 2. Create `src/updater/infra_tier.py` — the shared patch-and-PR helper

Module docstring (Google-style) explaining it is the shared machinery for the four infra-tier target handlers.

```python
import re
from pathlib import Path

from .changelog import add_to_unreleased
from .git_operations import (
    check_git_status,
    create_pull_request,
    find_existing_pull_request,
    git_checkout_new_branch,
    git_commit,
    git_push,
)
from .log_manager import log_message, run_command

GO_VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")
CLAUDE_YOLO_TAG_RE = re.compile(r"^v\d+\.\d+\.\d+$")


class InfraTargetError(Exception):
    """Raised when an infra-tier handler cannot proceed."""
```

Add these functions (signatures pinned; bodies follow the referenced patterns):

- `validate_go_version(value: str) -> bool` — returns `bool(GO_VERSION_RE.match(value))`.
- `validate_claude_yolo_tag(value: str) -> bool` — returns `bool(CLAUDE_YOLO_TAG_RE.match(value))`. (Used by the dark-factory handler in the next prompt; include it now so the shared helper is complete.)
- `require_clean_worktree(checkout: Path) -> None` — `count, _ = check_git_status(checkout)`. If `count == -1` raise `InfraTargetError(f"not a git repository: {checkout}")`. If `count > 0` raise `InfraTargetError(f"uncommitted changes in {checkout}; stash or commit and re-run")`.
- `read_current_value(checkout: Path, target_file: str, pattern: re.Pattern[str]) -> str | None` — return `None` if `checkout / target_file` does not exist; otherwise return `pattern.search(content).group(1)` or `None`.
- `require_current_value(checkout: Path, target_file: str, pattern: re.Pattern[str]) -> str` — raise `InfraTargetError(f"target file not found: {target_file}")` if the file is missing; raise `InfraTargetError(f"pattern not found: {pattern.pattern} in {target_file}")` if the pattern does not match; else return the matched group 1.
- `patch_file(checkout: Path, target_file: str, pattern: re.Pattern[str], new_value: str) -> bool` — `content = re.sub(pattern, lambda m: m.group(0).replace(m.group(1), new_value, 1), content)`; if the content changed, write it back; return whether it changed. This preserves the constant's surrounding text (`ARG GO_VERSION=1.27.0` → `ARG GO_VERSION=1.28.0`).

### `process_infra_target` — the shared flow

```python
def process_infra_target(
    checkout: Path,
    *,
    repo: str,
    target_file: str,
    pattern: re.Pattern[str],
    new_value: str,
    branch_name: str,
    title: str,
    body: str,
    changelog_bullet: str,
    dry_run: bool,
) -> int:
    """Patch an infra-tier target constant and optionally open a PR. Returns exit code."""
```

Implement it as this exact sequence (log via `log_message(..., to_console=True)`; return 0 on success/no-op, 1 on any error):

1. `require_clean_worktree(checkout)` — on `InfraTargetError` log the message and return 1. (Aborts BEFORE touching the file.)
2. `current = require_current_value(checkout, target_file, pattern)` — on `InfraTargetError` log the message and return 1.
3. If `current == new_value`: log `"{target_file} already up to date ({new_value})"` and return 0. (Both modes — no network, no diff. This is the idempotency path.)
4. If NOT `dry_run`: `existing = find_existing_pull_request(checkout, repo)`; if `existing` is truthy, log `"existing updater PR: {existing}"` and return 0 (no new PR).
5. If NOT `dry_run`: `git_checkout_new_branch(checkout, branch_name)`.
6. `patch_file(checkout, target_file, pattern, new_value)` and log `"Patched {target_file}: {current} → {new_value}"`.
7. If NOT `dry_run`: `add_to_unreleased(checkout, {"changelog": [changelog_bullet]}, log_func=log_message)` — appends the `## Unreleased` bullet, or skips if the checkout has no CHANGELOG.md.
8. Print the diff: `result = run_command("git diff --name-only", cwd=checkout, capture_output=True, quiet=True, log_func=log_message)` and log the output as the changed-files list (this is the AC negative evidence — for a dry run it must list exactly `target_file`).
9. If `dry_run`: log `"(dry-run — no branch or PR opened)"` and return 0.
10. Real run: `git_commit(checkout, title, log_func=log_message)`; `git_push(checkout, log_func=log_message)`; `pr_url = create_pull_request(checkout, repo, branch_name, title, body, log_func=log_message)`; log `"PR opened: {pr_url}"`; return 0.

Wrap steps 4-10 in `try/except (InfraTargetError, RuntimeError) as e` that logs the error and returns 1. No partial PR: if push/PR fails, the change lives only on the local feature branch and nothing is merged.

Do NOT add any tunable knobs, extra flags, or metrics — the spec asks only for this flow.

## 3. Create `src/updater/claude_yolo_handler.py`

```python
"""Infra-tier handler for bborbe/claude-yolo's Dockerfile ARG GO_VERSION."""

import re
from pathlib import Path

from .infra_tier import process_infra_target, validate_go_version
from .log_manager import log_message

CLAUDE_YOLO_REPO = "bborbe/claude-yolo"
CLAUDE_YOLO_FILE = "Dockerfile"
CLAUDE_YOLO_PATTERN = re.compile(r"^ARG GO_VERSION=(\d+\.\d+\.\d+)$")


class ClaudeYoloHandler:
    """Bump ARG GO_VERSION in the bborbe/claude-yolo Dockerfile and open a PR."""

    def run(self, checkout: Path, *, dry_run: bool, go_version: str) -> int:
        if not validate_go_version(go_version):
            log_message(f"✗ Invalid Go version: {go_version!r} (expected X.Y.Z)", to_console=True)
            return 1
        return process_infra_target(
            checkout,
            repo=CLAUDE_YOLO_REPO,
            target_file=CLAUDE_YOLO_FILE,
            pattern=CLAUDE_YOLO_PATTERN,
            new_value=go_version,
            branch_name=f"updater/claude-yolo-{go_version}",
            title=f"chore: bump Go version to {go_version} in Dockerfile",
            body=f"Bump ARG GO_VERSION to {go_version}.",
            changelog_bullet=f"chore: bump Go version to {go_version} in Dockerfile",
            dry_run=dry_run,
        )
```

The branch name starts with `updater` so the spec's `head:updater` PR probes match it.

## 4. Wire the CLI in `src/updater/cli.py`

In `main_updater_async`:

- Add the import at the top with the other handler imports: `from .claude_yolo_handler import ClaudeYoloHandler`.
- AFTER the `_sub_descs` loop that adds the existing subcommands, add the claude-yolo subparser:
```python
sub = subparsers.add_parser(
    "claude-yolo",
    help="Bump ARG GO_VERSION in the bborbe/claude-yolo Dockerfile and open a PR",
)
sub.add_argument("path", help="Path to the bborbe/claude-yolo checkout")
sub.add_argument("--dry-run", action="store_true", help="Show the diff and exit without opening a PR")
sub.add_argument(
    "--go-version",
    required=True,
    metavar="X.Y.Z",
    help="Target Go version to set in ARG GO_VERSION (e.g. 1.28.0)",
)
```
- In the dispatch chain, add before the final `else`:
```python
elif args.subcommand == "claude-yolo":
    return ClaudeYoloHandler().run(
        Path(args.path), dry_run=args.dry_run, go_version=args.go_version
    )
```
- In the final `else` branch, `valid` is derived from `_sub_descs` (`valid = ", ".join(_sub_descs.keys())` in cli.py). Extend the derived value with the handler subcommand WITHOUT adding it to `_sub_descs` (adding it would give it the wrong positional and create a conflicting subparser): `valid = ", ".join([*_sub_descs.keys(), "claude-yolo"])`.

Do NOT touch the existing 8 subcommands, `_run_go_modules`, `_run_python_modules`, `_run_docker_modules`, `_run_release_modules`, `_run_all_modules`, or any `process_*` function.

## 5. CHANGELOG

The updater repo has a CHANGELOG.md. Add (or append to) a `## Unreleased` section with:
`- feat: Add infra-tier claude-yolo handler (updater claude-yolo) and the shared patch-and-PR helper reused by the other infra-tier handlers`

## 6. Tests

Use pytest with the conventions from `tests/test_git_operations.py` / `tests/test_cli.py` (pytest, `unittest.mock.patch`, `tmp_path`/`tmp_git_repo`, no real network). Mock `gh`/push via patching the names imported into the module under test (e.g. `patch("updater.infra_tier.create_pull_request")`). Use the `tmp_git_repo` fixture from `tests/conftest.py` for tests that need a real git repo (dry-run diff, clean/dirty worktree). Where a fixture file is needed, create it and `git add` + `git commit` it so the worktree is clean.

### `tests/test_infra_tier.py` (new file)

Boundary tests (level 1 — call the validation/parse boundary directly; level 2 — real git subprocess through the dry-run path):

1. `test_validate_go_version_accepts` — parametrize `["1.28.0", "1.0.0"]` → True.
2. `test_validate_go_version_rejects` — parametrize `["1.28", "1.28.0-rc1", "go1.28.0", "v1.28.0", "1.28.0 ", "; rm -rf /", ""]` → False.
3. `test_validate_claude_yolo_tag_accepts` — `["v0.16.0", "v1.2.3"]` → True.
4. `test_validate_claude_yolo_tag_rejects` — `["0.16.0", "v0.16", "v0.16.0-rc1", "1.28.0", "v1.28.0 ", ""]` → False.
5. `test_read_current_value_found` / `test_read_current_value_missing_file` / `test_read_current_value_pattern_absent` — the three returns (value / None / None).
6. `test_require_current_value_raises_missing_file` — `pytest.raises(InfraTargetError)` whose message contains the file name.
7. `test_require_current_value_raises_pattern_not_found` — message contains BOTH the file name and the pattern string (the spec requires "pattern not found" naming file+pattern).
8. `test_patch_file_changes_value` — returns True and file content updated.
9. `test_patch_file_no_op_when_current` — returns False and content unchanged.
10. `test_require_clean_worktree_clean` — `tmp_git_repo` with a committed file → no raise.
11. `test_require_clean_worktree_dirty` — `tmp_git_repo` plus an uncommitted file → raises `InfraTargetError`.
12. `test_require_clean_worktree_not_repo` — plain `tmp_path` → raises.
13. `test_process_infra_target_dry_run_patches_and_shows_diff` — `tmp_git_repo` + committed `Dockerfile` containing `ARG GO_VERSION=1.27.0`; call with `dry_run=True`, `new_value="1.28.0"`, `target_file="Dockerfile"`, `pattern=re.compile(r"^ARG GO_VERSION=(\d+\.\d+\.\d+)$")`. Assert return 0, the file now contains `1.28.0`, and running the real `git diff --name-only` (via `subprocess`/`git -C` from the fixture) lists exactly `["Dockerfile"]`. Patch `git_checkout_new_branch`/`git_commit`/`git_push`/`create_pull_request` as spies and assert none was called. This test traverses the real git subprocess boundary with the new value.
14. `test_process_infra_target_dry_run_up_to_date` — target already at `new_value` → return 0 and no diff (run `git diff --name-only` → empty).
15. `test_process_infra_target_dry_run_dirty_aborts` — dirty worktree → return 1, file untouched.
16. `test_process_infra_target_real_opens_pr` — `tmp_git_repo` + committed Dockerfile at 1.27.0; patch `find_existing_pull_request` → None, `git_checkout_new_branch`, `git_commit`, `git_push`, `create_pull_request` → `"https://github.com/bborbe/claude-yolo/pull/7"`. Assert return 0 and `create_pull_request` called with repo `"bborbe/claude-yolo"`, branch, title, body; assert `add_to_unreleased` was called (patch it).
17. `test_process_infra_target_real_existing_pr_skips` — patch `find_existing_pull_request` → `"https://.../pull/5"` → return 0, no branch/patch/PR calls, file NOT patched.
18. `test_process_infra_target_real_up_to_date_skips` — already current → return 0 and `find_existing_pull_request` NOT called (no network when nothing to do).
19. `test_process_infra_target_real_pr_failure` — `create_pull_request` raises `RuntimeError` → return 1 (no partial PR).

### `tests/test_git_operations.py` (append)

20. `test_git_checkout_new_branch` — patch `run_command`; assert the command contains `git checkout -b updater/claude-yolo-1.28.0`.
21. `test_find_existing_pull_request_none` — patch `run_command` → stdout `"[]"` → returns None.
22. `test_find_existing_pull_request_empty_stdout` — stdout `""` → returns None.
23. `test_find_existing_pull_request_found` — stdout `[{"url": "https://github.com/bborbe/claude-yolo/pull/5"}]` → returns the URL.
24. `test_find_existing_pull_request_gh_error` — `run_command` raises `RuntimeError` → propagates.
25. `test_create_pull_request_returns_url` — stdout `"https://github.com/bborbe/claude-yolo/pull/6"` → returns URL; assert the command contains `--repo bborbe/claude-yolo` and `--head updater/claude-yolo-1.28.0` and the title/body.
26. `test_create_pull_request_failure_propagates` — `run_command` raises → `pytest.raises(RuntimeError)`.

### `tests/test_claude_yolo_handler.py` (new file)

27. `test_run_dry_run_bumps_dockerfile` — `tmp_git_repo` + committed Dockerfile `ARG GO_VERSION=1.27.0`; `ClaudeYoloHandler().run(repo, dry_run=True, go_version="1.28.0")` → 0; file 1.28.0; real `git diff --name-only` == `["Dockerfile"]`.
28. `test_run_dry_run_up_to_date` — fixture at 1.28.0; run with 1.28.0 → 0; diff empty.
29. `test_run_invalid_go_version` — `"1.28"` → 1; file untouched.
30. `test_run_real_opens_pr` — mock `updater.infra_tier.find_existing_pull_request` → None, `git_checkout_new_branch`, `git_commit`, `git_push`, `create_pull_request` → URL → 0; assert PR created with branch `updater/claude-yolo-1.28.0` and title `chore: bump Go version to 1.28.0 in Dockerfile`.
31. `test_run_real_already_current` — fixture at 1.28.0; run → 0; no PR call.
32. `test_run_real_existing_pr` — mock `find_existing_pull_request` → URL → 0; no new PR; file untouched.
33. `test_run_pattern_not_found` — Dockerfile contains `ARG GO_VERSION = 1.27.0` (spaces) → 1; error names `Dockerfile` and the pattern.
34. `test_run_dirty_checkout_aborts` — uncommitted change → 1; file untouched.

### `tests/test_cli.py` (append)

35. `test_claude_yolo_subcommand_dispatch` — `sys.argv = ["updater", "claude-yolo", str(tmp_path), "--dry-run", "--go-version", "1.28.0"]`; `patch("updater.cli.ClaudeYoloHandler")` with `.return_value.run.return_value = 0`; assert exit 0 and `run` called with `Path(str(tmp_path))`, `dry_run=True`, `go_version="1.28.0"`.
36. `test_claude_yolo_subcommand_requires_go_version` — `sys.argv` without `--go-version` → `pytest.raises(SystemExit)`.

Coverage: new modules (`infra_tier`, `claude_yolo_handler`, and the new `git_operations` functions) must have ≥80% statement coverage — the tests above cover that; verify with `uv run --with pytest-cov pytest --cov=updater.infra_tier --cov=updater.claude_yolo_handler --cov=updater.git_operations --cov-report=term-missing`.
</requirements>

<constraints>
- Handlers live in `src/updater/` as modules (NO `handlers/` dir); CLI wiring goes in `cli.py`.
- Reuse existing `git_operations.py` and `config.py` — no new bespoke git implementation.
- Target files are frozen per `docs/infra-tier-targets.md`; claude-yolo is `Dockerfile` `ARG GO_VERSION=X.Y.Z`. Do not invent new target paths.
- PRs use the conventional `chore:` / `feat:` prefix and a `## Unreleased` CHANGELOG bullet per repo (autoRelease repos need the bullet) — the real run adds the bullet via `add_to_unreleased`.
- `--go-version` (and the handler's target-version input) is validated against the `X.Y.Z` regex BEFORE interpolation into any patch, branch name, title, body, or git command — no shell injection / path traversal.
- The only write path is a PR (reviewable, reversible); no handler pushes directly to a target's master.
- No secrets (gh tokens, clone URLs with credentials) are written to PR bodies or logs; git operations use `git_operations.py`'s ambient-credential handling, never inline credentials.
- Handler invocation order for the state machine is owned by the sibling [[Build Trigger Ordering State Machine]] spec — this handler is independently invocable.
- `make precommit` stays green; existing tests unchanged.
- Follow project Python conventions (pytest, type hints, uv, Google-style docstrings); no `print` — use `log_message()`; no new dependencies.
- Do NOT commit — dark-factory handles git.
- Do NOT modify `pipeline.py`, `go_updater.py`, `docker_updater.py`, `python_updater.py`, `gomod_excludes.py`, or any existing subcommand's behavior (spec Non-goal).
- The shared `infra_tier.py` helper is REUSED by the next three prompts' handlers — do not duplicate its logic into the handler module; the handler module only holds target constants + validation + delegation.
</constraints>

<verification>
Run `make precommit` — must exit 0 (sync + format + test + lint + typecheck).

Confirm the handler module and class exist:
```
grep -n 'ClaudeYoloHandler' src/updater/claude_yolo_handler.py
```

Confirm the shared helper functions exist:
```
grep -nE 'def (process_infra_target|validate_go_version|validate_claude_yolo_tag|require_clean_worktree|patch_file|read_current_value|require_current_value)' src/updater/infra_tier.py
```

Confirm the CLI subcommand exists:
```
grep -n 'claude-yolo' src/updater/cli.py
```

Manual dry-run against a scratch fixture (produces the spec's AC #1 container evidence). Run from the repo root:
```
rm -rf /tmp/claude-yolo-fixture && mkdir -p /tmp/claude-yolo-fixture && cd /tmp/claude-yolo-fixture && git init -q && git config user.email u@test && git config user.name u && printf 'ARG GO_VERSION=1.27.0\n' > Dockerfile && git add Dockerfile && git commit -qm init && cd - && uv run updater claude-yolo /tmp/claude-yolo-fixture --dry-run --go-version 1.28.0 && cd /tmp/claude-yolo-fixture && git diff --name-only
```
The dry-run output must show the before/after constant (`ARG GO_VERSION=1.27.0 → ARG GO_VERSION=1.28.0`) and the final `git diff --name-only` must print exactly `Dockerfile`.

Coverage check for the new modules (≥80%):
```
uv run --with pytest-cov pytest --cov=updater.infra_tier --cov=updater.claude_yolo_handler --cov=updater.git_operations --cov-report=term-missing tests/test_infra_tier.py tests/test_claude_yolo_handler.py tests/test_git_operations.py tests/test_cli.py
```
</verification>

<completion_report_template>
Append the standard DARK-FACTORY-REPORT block with `status`, `verification.command`, `verification.exitCode`. Then an `## Improvements` section (PROMPT / GUIDE / GLOBAL categories, or `- None`).
</completion_report_template>
