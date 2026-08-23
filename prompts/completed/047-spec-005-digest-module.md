---
status: completed
spec: [005-digest-weekly]
summary: 'Implemented spec 005 weekly digest: added DIGEST_FLEET_REPOS/DIGEST_PARK_LIST_DIR/DIGEST_HUMAN_REVIEW_DIRS to config.py; created src/updater/digest.py (~800 lines) with DigestQueryError, date helpers (default_week_window/validate_date), six per-source queries (query_tags, query_pull_requests, query_failed_builds, query_parked_advisories, query_human_review_tasks, query_chain_aborts) each patchable by name with graceful degradation (missing dirs -> named errors, rate-limit backoff with RATE_LIMIT_RE + jitter + 3 retries, timeout via subprocess.run timeout), sort_tags numeric-version descending, and Digest class with render()/run() producing the five headings, Summary line, per-repo version lines, and omitted-when-empty Query errors section; wired `updater digest` into cli.py (subparser --since/--until/--dry-run, dispatch, valid list); added CHANGELOG ## Unreleased feat: bullet; wrote 48 tests in tests/test_digest.py (all 22 required + degradation/edge cases) and 3 async CLI dispatch tests in tests/test_cli.py. Coverage 94% for updater.digest. Verified: make precommit exit 0; manual dry-run renders all headings + named per-source errors and exits 0; invalid-date exits 1; forbidden-file diff empty.'
execution_id: updater-exec-047-spec-005-digest-module
dark-factory-version: dev
created: "2026-08-23T16:30:00Z"
queued: "2026-08-23T14:49:19Z"
started: "2026-08-23T14:49:38Z"
completed: "2026-08-23T15:00:25Z"
---

# Weekly Go update digest module and CLI

<summary>
- A new `updater digest` subcommand renders the weekly Go-update digest from live fleet state — the operator's single weekly touchpoint, replacing the ~3h/cycle hand re-derivation
- The digest enumerates a configurable fleet of repos (default from `config.py`, operator-maintained to match the watcher allowlist) and queries each source: git tags per repo, `gh` PRs with `head:updater`, and the exceptions (parked no-fix advisories, failed builds, chain aborts, `human_review` tasks)
- The output has five sections: a summary line, Go versions bumped (current vs previous tag per repo), pull requests opened/merged/closed, releases cut (tags are the source of truth — no GitHub Release objects assumed), and an `Exceptions` section listing everything needing operator judgment
- A week with no changes renders a "no updates this week" summary plus the exceptions — the operator still gets the negative signal
- Source failures degrade gracefully: a rate limit, a missing repo, or malformed data renders a named error in the affected section while the rest of the digest still renders — never a silent empty section, never a raw traceback
- GitHub rate limits back off with jitter and retry a bounded number of times before degrading to a named error, following the same carve-out pattern the chain module established for polling probes
- `--dry-run` prints the full digest to the console and sends nothing (delivery is wired in the next prompt); `--since`/`--until` override the default trailing-7-day window
- Everything is testable in-container with mocked queries and fixture files — no network, no real git/gh
</summary>

<objective>
Build the `updater digest` module and CLI so one invocation produces a complete, accurate weekly summary from live fleet state (versions bumped, PRs opened/merged/closed, releases cut) plus the judgment-needed exceptions, rendered and printed with graceful per-source error handling — the foundational prompt before cadence and delivery.
</objective>

<context>
Read `/workspace/CLAUDE.md` for project conventions (Python, uv + hatchling, pytest, dark-factory flow, changelog rules).

Read `/workspace/docs/architecture.md` for the pipeline topology (the fleet's repos are Go projects updated by the pipeline's fan-out; releases are tag-based). Read `/workspace/docs/dod.md` — the DoD's `run_command()` rule and its documented carve-out for direct `subprocess.run` in specific cases (already precedented in `chain.py`).

Read these files fully before editing:
- `/workspace/src/updater/chain.py` — THE precedent for this module: `_run_probe(cmd, cwd, step, log_func)` (direct `subprocess.run` WITHOUT raising — the DoD carve-out, marked with a comment), `_is_rate_limited(result)` (403/429 detection via `RATE_LIMIT_RE`), `_backoff_sleep(base, sleep, log_func)` (jittered backoff that never aborts). The digest's `_run_query` follows this exact idiom.
- `/workspace/src/updater/git_operations.py` — `find_existing_pull_request(module_path, repo, log_func)` shows the repo's existing `gh pr list --repo {repo} --search "head:updater" --state open --json url` invocation form; the digest's PR query uses the same `head:updater` search but with `--state all` and more JSON fields.
- `/workspace/src/updater/config.py` — the module-level constants pattern the new digest constants must follow.
- `/workspace/src/updater/log_manager.py` — `log_message(message: str, to_console: bool = True)`; `run_command(cmd, cwd=None, capture_output=False, quiet=False, log_func=log_message) -> subprocess.CompletedProcess` which RAISES `RuntimeError` on non-zero exit and discards output on failure (why the digest uses the chain-style probe for queries that must inspect output).
- `/workspace/src/updater/cli.py` — `main_updater_async()`: the `subparsers = parser.add_subparsers(dest="subcommand", metavar="SUBCOMMAND")` construction, `_sub_descs`, the `chain` subparser added after `trading` (the exact insertion pattern to copy), the `if args.subcommand == ...` dispatch chain, and the final `else` branch whose `valid` list ends with `..., "chain"]`. `from datetime import datetime` is already imported.
- `/workspace/src/updater/infra_tier.py` — `validate_go_version(value: str) -> bool` (regex-validate-a-string-arg pattern) and `InfraTargetError` (named-error exception pattern) for the digest's `DigestQueryError`.
- `/workspace/tests/conftest.py` — `tmp_path` fixtures. `/workspace/tests/test_chain.py` — the mocking conventions (`patch("updater.<module>.<name>")`, fake `sleep`, patched `random.uniform`). `/workspace/tests/test_cli.py` (the `TestMainUpdaterChain` class at the end, ~line 2278) — the exact `sys.argv` + `patch("updater.cli.<Class>")` subcommand-dispatch test pattern to copy for the digest dispatch tests.

Reference docs (in-container paths — the executor container runs from `/home/node`):
- `/home/node/.claude/plugins/marketplaces/coding/docs/python-cli-arguments-guide.md` — CLI subcommand/argument conventions
- `/home/node/.claude/plugins/marketplaces/coding/docs/python-logging-guide.md` — `log_message`/`run_command` conventions
- `/home/node/.claude/plugins/marketplaces/coding/docs/python-project-structure.md` — `src/` layout

Cross-project behavioral rules the digest depends on (the spec flags both for documentation in their repos' docs — do NOT try to import or parse either project's code):
- Parked no-fix advisories: the `github-update-go-agent` plan contract classifies `Outcome="needs_input"` (park path) and `PlanVuln.Action="park"` (no fix / out-of-scope). The digest reads park-list JSON files (see requirement 4.6) shaped like that contract from `config.DIGEST_PARK_LIST_DIR`.
- Failed builds: github-build-watcher's "failure" semantics; the digest's query is the observable `gh run list ... conclusion == "failure"` within the window.
- `human_review` tasks: the vault `24 Tasks/` + `OpenClaw/tasks/` task files whose frontmatter carries `status: human_review` or `phase: human_review`.
</context>

<requirements>

## 1. Add digest configuration constants to `src/updater/config.py`

Add `from pathlib import Path` to the imports at the top of `src/updater/config.py` (its only current import is `from typing import TextIO`), then append (after the existing Claude configuration block) the following module-level constants, following the existing module-level-constant style:

```python
# Weekly digest configuration
# Fleet of repos the weekly digest queries (operator-maintained — mirror the
# github-update-go-watcher REPO_ALLOWLIST plus repos with goUpdate.autoUpdate: true).
DIGEST_FLEET_REPOS: list[str] = [
    "bborbe/agent",
    "bborbe/coding",
    "bborbe/dark-factory",
    "bborbe/github-build-watcher",
    "bborbe/github-pr-watcher",
    "bborbe/github-release-watcher",
    "bborbe/github-update-go-watcher",
    "bborbe/go-version-watcher",
    "bborbe/maintainer",
    "bborbe/sentry-watcher",
    "bborbe/task-watcher",
    "bborbe/updater",
    "bborbe/vault-cli",
]
# Directory of park-list JSON files (github-update-go-agent plan outputs with
# Outcome="needs_input" / PlanVuln.Action="park"). REQUIRED for spec AC2 (surfaces
# parked advisories) — the operator MUST confirm this points at the agent's plan outputs
# before AC verification (see requirement 9).
DIGEST_PARK_LIST_DIR: Path | None = Path.home() / "Documents/OpenClaw/plans"
# Task directories scanned for human_review-flagged tasks (vault 24 Tasks/ + OpenClaw/tasks/).
DIGEST_HUMAN_REVIEW_DIRS: list[Path] = [
    Path.home() / "Documents/Obsidian/Personal/24 Tasks",
    Path.home() / "Documents/Obsidian/OpenClaw/tasks",
]
```

`Path` is NOT currently imported in `config.py` (its only import is `from typing import TextIO`) — the first step of this requirement adds `from pathlib import Path`. The fleet list is the operator's seam for enumeration — tests inject explicit repo lists via the `Digest` constructor instead.

## 2. Create `src/updater/digest.py` — the digest module

Module docstring (Google-style) explaining this renders the weekly Go-update digest from live fleet state per spec 005, with per-source graceful degradation.

```python
"""Weekly Go-update digest rendering.

Queries live fleet state (git tags, gh PRs, failed builds, park list,
human_review tasks, chain-abort logs) and renders the weekly digest the
operator reviews — versions bumped, PRs, releases cut, and the exceptions
needing judgment, per spec 005.
"""

import json
import random
import re
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

from . import config
from .log_manager import log_message
```

Module-level constants and the named error exception:

```python
WEEK_WINDOW_DAYS = 7
RATE_LIMIT_RE = re.compile(r"(?:403|429)")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
QUERY_TIMEOUT_SECONDS = 300
RATE_LIMIT_RETRIES = 3
GH_PR_SEARCH = "head:updater"


class DigestQueryError(Exception):
    """A named source-query failure (rate limit, repo missing, malformed data).

    Carries a human-readable message that is rendered verbatim into the
    affected section — the digest never silently drops a failed source.
    """

    def __init__(self, source: str, message: str) -> None:
        self.source = source
        super().__init__(f"{source}: {message}")
```

## 3. Date helpers

```python
def default_week_window(now: datetime | None = None) -> tuple[str, str]:
    """Return (since, until) ISO dates for the trailing 7-day window ending at now."""

def validate_date(value: str) -> bool:
    """Return whether value is a valid YYYY-MM-DD date (regex + real-date check)."""

def _in_window(iso_timestamp: str | None, since: str, until: str) -> bool:
    """Return whether iso_timestamp's date falls within the inclusive [since, until] window."""
```

- `default_week_window`: `end = now or datetime.now()`; `start = end - timedelta(days=WEEK_WINDOW_DAYS)`; return `(start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))`. (The window is inclusive of `until` — the trailing 7 days ending today.)
- `validate_date`: `DATE_RE.fullmatch(value)` AND `date.fromisoformat(value)` succeeds; return False on either failure (wrap the parse in try/except `ValueError`).
- `_in_window`: return False when `iso_timestamp` is None or empty; parse the date via `datetime.fromisoformat(iso_timestamp.replace("Z", "+00:00")).date()` wrapped in try/except `ValueError` (return False on unparseable — a malformed timestamp is filtered out, never a traceback); compare against `date.fromisoformat(since)` / `date.fromisoformat(until)` inclusive on both ends.

## 4. Source queries

All queries return plain data or raise `DigestQueryError` naming their source. Each query is a module-level function so tests patch it by name (`patch("updater.digest.query_tags", ...)`).

### 4.1 `_run_query` — the shell boundary (chain.py carve-out precedent)

```python
def _run_query(
    cmd: str,
    cwd: Path,
    source: str,
    *,
    log_func: Callable[..., None] = log_message,
) -> str:
    """Run cmd and return stdout on success; raise DigestQueryError on failure.

    Deliberate exception to the run_command() convention (see DoD carve-out,
    same as chain._run_probe): the digest must inspect stderr for rate-limit
    markers and treat a non-zero exit as a recoverable source error, which
    run_command cannot do (it raises and discards output).
    """
```

Behavior:
- `subprocess.run(cmd, shell=True, cwd=cwd, capture_output=True, text=True, timeout=QUERY_TIMEOUT_SECONDS)` in a try/except; on `subprocess.TimeoutExpired` raise `DigestQueryError(source, f"{cmd} timed out after {QUERY_TIMEOUT_SECONDS}s")`. Do NOT raise on non-zero `returncode`.
- Rate-limit handling: if `RATE_LIMIT_RE.search((result.stdout or "") + (result.stderr or ""))` matches, back off with jitter and retry — `delay = 1.0 + random.uniform(0.0, 2.0)`; log `f"rate limit on {source}; backing off {delay:.0f}s"` via `log_func(..., to_console=True)`; `time.sleep(delay)`; retry up to `RATE_LIMIT_RETRIES` times. After the retries are exhausted while still rate-limited, raise `DigestQueryError(source, "GitHub API rate limit — backed off and retried; still limited")`. (Never a silent empty section — the section renders this named error.)
- Other non-zero exit: raise `DigestQueryError(source, (result.stderr or result.stdout or "command failed").strip())` — this covers "repo missing / renamed" for `git ls-remote` (fatal: repository not found) and gh auth failures.
- Success: return `result.stdout`.

### 4.2 `query_tags(repo, cwd, log_func) -> list[str]`

- Command: `git ls-remote --tags https://github.com/{repo}.git` (repo is the `owner/name` from the fleet list — validated constant, never free-form input).
- Run via `_run_query(..., source=f"tags for {repo}")`.
- Parse stdout: one `{sha}\trefs/tags/{name}` per line. Skip the peeled lines ending `^{}`. Strip the `refs/tags/` prefix. Return the raw tag-name list (unsorted).
- A repo with no tags returns an empty list (a repo that has never released renders as "no tags").

### 4.3 `parse_tags(raw: str) -> list[str]` — pure parse helper

`parse_tags` does the line parsing described in 4.2 (so it is unit-tested without any subprocess). `query_tags` calls `parse_tags(_run_query(...))`.

### 4.4 `query_pull_requests(repo, since, until, cwd, log_func) -> list[PullRequest]`

- Command: `gh pr list --repo {repo} --search '{GH_PR_SEARCH}' --state all --limit 100 --json number,title,state,createdAt,mergedAt,closedAt,url` — use the single-quoted `--search 'head:updater'` form (the same single-quoted form the chain's `wait_for_pr_merge` uses, NOT the double-quoted form in `git_operations.py`).
- Run via `_run_query(..., source=f"PRs for {repo}")`.
- Parse stdout as JSON (try/except `json.JSONDecodeError` → raise `DigestQueryError(f"PRs for {repo}", "malformed gh pr list JSON")` — the malformed-data failure mode).
- Return the PRs that have at least one event (`created`, `merged`, or `closed`) inside the window (see `pr_events` in 4.5). An empty result is valid (no `head:updater` PRs this week).

### 4.5 `PullRequest` dataclass and helpers

```python
@dataclass(frozen=True)
class PullRequest:
    """One head:updater pull request, as returned by gh pr list."""

    repo: str
    number: int
    title: str
    state: str  # OPEN | MERGED | CLOSED
    created_at: str
    merged_at: str | None
    closed_at: str | None
    url: str


def parse_pull_requests(repo: str, raw_json: str) -> list[PullRequest]:
    """Parse gh pr list JSON output into PullRequest objects."""


def pr_events(pr: PullRequest, since: str, until: str) -> set[str]:
    """Return the subset of {"opened", "merged", "closed"} events in the window."""
```

- `parse_pull_requests`: `json.loads(raw_json)` (let `json.JSONDecodeError` propagate — the caller in 4.4 wraps it into a `DigestQueryError`); build a `PullRequest` per element with the exact JSON keys above.
- `pr_events`: `"opened"` iff `_in_window(pr.created_at, since, until)`; `"merged"` iff `pr.state == "MERGED"` and `_in_window(pr.merged_at, since, until)`; `"closed"` iff `pr.state == "CLOSED"` and `_in_window(pr.closed_at, since, until)`.

### 4.6 `query_parked_advisories(park_list_dir, log_func) -> list[ParkedAdvisory]`

```python
@dataclass(frozen=True)
class ParkedAdvisory:
    """A parked no-fix advisory from the github-update-go-agent park list."""

    repo: str
    vuln_id: str
    package: str
    reason: str
```

- Scan `park_list_dir.glob("*.json")` (if `park_list_dir` is None → return `[]`).
- Each file is shaped like the cross-project `PlanOutput` contract: `{"outcome": "needs_input", "reason": "...", "vulns": [{"id": "...", "package": "...", "action": "park", "reason": "..."}]}`. A file yields one `ParkedAdvisory` per vuln with `action == "park"` (repo = file stem, vuln_id = `id`, package = `package`, reason = the vuln's `reason` or the file-level `reason` fallback). A file with `outcome == "needs_input"` and no park vulns yields nothing.
- A malformed file (invalid JSON, or not a dict) must NOT crash the digest — collect it and raise `DigestQueryError(f"park list", f"{file.name}: malformed park-list JSON")` at the end so the exceptions section shows the named parse error while the rest of the digest renders.
- A configured-but-missing directory: raise `DigestQueryError("park list", f"park-list dir not found: {park_list_dir}")`.

### 4.7 `query_human_review_tasks(human_review_dirs, log_func) -> list[HumanReviewTask]`

```python
@dataclass(frozen=True)
class HumanReviewTask:
    """A task file flagged human_review (status or phase) in the vault/OpenClaw dirs."""

    path: Path
    title: str
```

- For each dir in `human_review_dirs`: if it does not exist, record a `DigestQueryError(f"human_review", f"task dir not found: {d}")` and continue (the other dirs still scan). Empty list → `[]`.
- For each `*.md` file under the dir (recursive `rglob`), read it and parse the YAML frontmatter between the leading `---` fences (use `yaml.safe_load`, imported as `import yaml` — pyyaml is already a dependency). A file whose frontmatter maps to a dict containing `status == "human_review"` OR `phase == "human_review"` yields `HumanReviewTask(path=file, title=<frontmatter "title" if present else first non-frontmatter line, stripped>)`.
- A file with unparseable frontmatter is skipped silently (task files are scanned best-effort; the parse helper 4.8 is the tested contract).

### 4.8 `parse_task_frontmatter(text: str) -> dict` — pure parse helper

Extracts the YAML block between the first two `---` lines and returns `yaml.safe_load` of it; returns `{}` when there is no frontmatter or the block is unparseable (never raises).

### 4.9 `query_chain_aborts(log_dir, since, until, log_func) -> list[ChainAbortInfo]`

```python
@dataclass(frozen=True)
class ChainAbortInfo:
    """A chain-abort line from an updater run log within the window."""

    log_file: Path
    line: str
```

- `log_dir` is the updater log dir (`config.LOG_DIR_NAME`, i.e. `.update-logs`), resolved from the digest's `workdir`.
- If the dir does not exist → `[]` (no chain runs yet, not an error).
- For each `*.log` file, the log filename encodes the run timestamp in `config.RUN_TIMESTAMP` format `%Y-%m-%d-%H%M%S` (prefix of the filename). A file is in the window iff its date portion (first 10 chars) satisfies `_in_window` against `since`/`until` (treat the prefix as a midnight timestamp). Files whose prefix is not parseable are skipped.
- For each in-window file, scan lines for `Chain aborted` (the chain module logs `✗ Chain aborted at step ...`); yield one `ChainAbortInfo` per matching line.

### 4.10 `query_failed_builds(repo, since, until, cwd, log_func) -> list[FailedBuild]`

```python
@dataclass(frozen=True)
class FailedBuild:
    """A failed CI run on master within the window (github-build-watcher semantics)."""

    repo: str
    name: str
    created_at: str
    url: str
```

- Command: `gh run list --repo {repo} --branch master --limit 100 --json name,conclusion,createdAt,url` — run via `_run_query(..., source=f"builds for {repo}")`.
- Parse stdout as JSON (try/except `json.JSONDecodeError` → `DigestQueryError(f"builds for {repo}", "malformed gh run list JSON")`).
- Keep runs with `conclusion == "failure"` and `_in_window(createdAt, since, until)`; build `FailedBuild(repo, name, created_at, url)`. Empty result is valid.

## 5. The `Digest` class

```python
class Digest:
    """Render the weekly Go-update digest for a fleet of repos."""

    def __init__(
        self,
        *,
        since: str,
        until: str,
        repos: list[str] | None = None,
        dry_run: bool = False,
        workdir: Path | None = None,
        park_list_dir: Path | None = None,
        human_review_dirs: list[Path] | None = None,
    ) -> None:
```

- `repos` defaults to `config.DIGEST_FLEET_REPOS`; `workdir` defaults to `Path.cwd()`; `park_list_dir` defaults to `config.DIGEST_PARK_LIST_DIR`; `human_review_dirs` defaults to `config.DIGEST_HUMAN_REVIEW_DIRS`. Store all as private attributes (`self._since`, `self._until`, `self._repos`, `self._dry_run`, `self._workdir`, `self._park_list_dir`, `self._human_review_dirs`).
- The `repos`/`workdir`/`park_list_dir`/`human_review_dirs` parameters are the testability seam (tests pass explicit tiny fleets and tmp dirs); they are NOT CLI flags.

Methods:

- `def render(self) -> str` — compose the full digest text. It NEVER raises for a source failure: every source query is wrapped so a `DigestQueryError` becomes a named error entry appended to an internal error list `self._errors: list[str]` (format `"<source>: <message>"`), and rendering continues. Steps:
  1. Per repo in `self._repos` (iterate in list order): run `query_tags(repo, self._workdir)` and `query_pull_requests(repo, since, until, self._workdir)` in separate try/except `DigestQueryError` blocks (each failure recorded and the repo's other data still collected). Compute `current_tag` / `previous_tag` via the sort helper in 5.1 (None when fewer than two version tags). Also run `query_failed_builds(repo, since, until, self._workdir)` per repo, same error capture.
  2. Compute `updated_repos = [repo for repo in self._repos if any("merged" in pr_events(pr, since, until) for pr in repo_prs[repo])]`.
  3. Exceptions: run `query_parked_advisories(self._park_list_dir)`, `query_human_review_tasks(self._human_review_dirs)`, and `query_chain_aborts(self._workdir / config.LOG_DIR_NAME, since, until)` — each in its own try/except `DigestQueryError` (recorded, section renders "no items (source failed)").
  4. Build the text per the layout in 5.2 and return it.
- `def run(self) -> int` — the CLI entry (SYNC, matching the handler classes — no async needed):
  1. Validate: `if not validate_date(self._since) or not validate_date(self._until): log_message(f"✗ Invalid date range: {self._since!r} .. {self._until!r} (expected YYYY-MM-DD)", to_console=True); return 1`.
  2. Empty fleet: `if not self._repos: log_message("✗ Empty fleet — check config.DIGEST_FLEET_REPOS", to_console=True); return 1`.
  3. `text = self.render()`; `log_message(text, to_console=True)` (prints the full digest text); `return 0`.
  (Delivery for the non-dry-run path is wired by the next prompt; this prompt prints in both modes. The `self._dry_run` flag is stored now.)

- `def sort_tags(tags: list[str]) -> list[str]` (module-level helper, 5.1) — return tags matching `^v?\d+(\.\d+)+$` sorted descending by numeric version (`[int(p) for p in tag.lstrip("v").split(".")]` as the sort key, padded to equal length); non-version tags are dropped from the sorted result.

### 5.2 Rendering layout (exact headings — the AC probes assert on these)

```
Weekly Go Update Digest
Window: {since} .. {until}

Summary: {len(updated_repos)}/{len(self._repos)} repos updated this week

## Go versions bumped
  - {repo}: {previous_tag} -> {current_tag}     (one line per updated repo with both tags)
  - {repo}: {current_tag}                        (updated repo with no previous tag)
  (when updated_repos is empty: "  no updates this week")

## Pull requests
  opened: {n}  merged: {n}  closed: {n}
  - {repo} #{number}: {title} ({state}) {url}    (one line per in-window PR, events determined by pr_events)
  (when empty: "  no updates this week")

## Releases cut
  - {repo}: {current_tag}                        (one line per repo UPDATED this week, scoped to updated_repos — `git ls-remote --tags` has no dates, so listing every repo's tag would mislabel stale tags as this week's releases)
  (when no repo was updated this week: "  no releases this week")

## Exceptions
  Parked advisories:
    - {repo}: {vuln_id} in {package} — {reason}
    (or "    none")
  Failed builds:
    - {repo}: {name} ({url})
    (or "    none")
  Chain aborts:
    - {log_file.name}: {line}
    (or "    none")
  human_review tasks:
    - {path}: {title}
    (or "    none")
    (or "    {source} failed: {message}" when that source errored)

## Query errors
  - {source}: {message}                          (one line per recorded error; section omitted entirely when none)
```

The exact inter-line spacing is free; the headings (`## Go versions bumped`, `## Pull requests`, `## Releases cut`, `## Exceptions`, `## Query errors`), the `Summary:` line, and the literal `no updates this week` string must match exactly (AC probes and tests assert on them). Sections are present even when empty (rendered with their empty marker), except `## Query errors` which is omitted when there are no errors.

## 6. Wire the CLI in `src/updater/cli.py`

In `main_updater_async`:
- Add the import at the top with the other handler imports: `from .digest import Digest, default_week_window`.
- AFTER the `chain` subparser (before `args = parser.parse_args()`), add the `digest` subparser:
  ```python
  sub = subparsers.add_parser(
      "digest",
      help="Render the weekly Go-update digest (versions bumped, PRs, releases, exceptions)",
  )
  sub.add_argument(
      "--since",
      default=None,
      metavar="YYYY-MM-DD",
      help="Window start (inclusive); default: 7 days ago",
  )
  sub.add_argument(
      "--until",
      default=None,
      metavar="YYYY-MM-DD",
      help="Window end (inclusive); default: today",
  )
  sub.add_argument(
      "--dry-run",
      action="store_true",
      help="Print the digest to the console and send nothing",
  )
  ```
- In the dispatch chain, add before the final `else`:
  ```python
  elif args.subcommand == "digest":
      since, until = default_week_window()
      if args.since:
          since = args.since
      if args.until:
          until = args.until
      return Digest(
          since=since,
          until=until,
          dry_run=args.dry_run,
          workdir=Path.cwd(),
      ).run()
  ```
- In the final `else` branch, extend `valid` to include the new subcommand (without touching `_sub_descs`): the list `[*_sub_descs.keys(), "claude-yolo", "dark-factory", "bundlewrap", "trading", "chain"]` becomes `[*_sub_descs.keys(), "claude-yolo", "dark-factory", "bundlewrap", "trading", "chain", "digest"]`.

Do NOT touch the existing subcommands, the handler subparsers, `_run_go_modules`, `_run_python_modules`, `_run_docker_modules`, `_run_release_modules`, `_run_all_modules`, or any `process_*` function. Do NOT modify `chain.py`, `git_operations.py`, `infra_tier.py`, or any handler module.

## 7. CHANGELOG

The updater repo has a CHANGELOG.md. Add to the `## Unreleased` section:
`- feat: Add weekly Go-update digest (updater digest) — fleet source queries (tags, head:updater PRs, failed builds, park list, human_review tasks, chain-abort logs), summary + exceptions rendering, --since/--until window, --dry-run no-send`

## 8. Tests

Use pytest with the conventions from `tests/test_chain.py` / `tests/test_cli.py` (pytest, `unittest.mock.patch` on the name imported into the module under test, `tmp_path`, no real network, never sleep for real — patch `time.sleep` or `random.uniform`). pytest config sets `asyncio_mode = "auto"`. The digest module itself is synchronous — write plain `def test_...` (no async) for the digest tests; **EXCEPT the CLI dispatch tests (23-25), which must be `async def test_...` invoking `await main_updater_async()`** (copy the existing `TestMainUpdaterChain` pattern — a plain sync test would silently test an un-awaited coroutine).

### `tests/test_digest.py` (new file)

Unit tests:

1. `test_default_week_window` — `default_week_window(now=datetime(2026, 8, 21, 12, 0, 0))` returns `("2026-08-14", "2026-08-21")`.
2. `test_validate_date_accepts` — `"2026-08-21"` → True; `test_validate_date_rejects` — `"2026-8-21"`, `"2026-13-01"`, `"not-a-date"`, `""` → False.
3. `test_in_window_inclusive` — a timestamp exactly on `since` and exactly on `until` are both in-window; one day outside on each side is not; None and a malformed timestamp are not.
4. `test_parse_tags` — raw `git ls-remote --tags` output (a few `{sha}\trefs/tags/vX.Y.Z` lines plus one `^{}` peeled line) parses to the tag list with the peeled line skipped.
5. `test_sort_tags_descending` — `["v1.25.2", "v1.25.3", "v1.9.0", "nightly"]` sorts to `["v1.25.3", "v1.25.2", "v1.9.0"]` (nightly dropped, numeric ordering correct).
6. `test_parse_pull_requests` — gh JSON with the seven keys parses to `PullRequest` objects; `test_pr_events` — a PR opened+merged in-window yields `{"opened", "merged"}`; a MERGED PR merged outside the window yields `{"opened"}` (if created in-window) or `set()`.
7. `test_query_pull_requests_malformed_json` — `_run_query` returns `"not json"` → `pytest.raises(DigestQueryError)` whose message contains `PRs for`.
8. `test_query_tags_repo_missing` — `_run_query` raises `DigestQueryError` (git fatal) → propagates with `tags for` in the message (the Digest renderer converts it into a `## Query errors` entry).
9. `test_rate_limit_retries_then_succeeds` — patch `updater.digest.subprocess.run` to return a 403-stderr result once then a success; patch `updater.digest.random.uniform` → 0.0 and `updater.digest.time.sleep` (recording calls); `_run_query` returns stdout after one backoff; assert the rate-limit log line and one sleep call.
10. `test_rate_limit_exhausted_raises` — patch `subprocess.run` to always return a 403-stderr result; `_run_query` raises `DigestQueryError` whose message contains `rate limit`.
11. `test_query_parked_advisories` — fixture `tmp_path` dir with one valid `{"outcome": "needs_input", "vulns": [{"id": "GO-2026-1", "package": "golang.org/x/foo", "action": "park", "reason": "no upstream fix"}]}` file and one `{"action": "fix"}` file → only the park vuln yields an advisory with repo=file stem; `test_query_parked_advisories_malformed` — a file with invalid JSON → `DigestQueryError` naming the file; `test_query_parked_advisories_missing_dir` — non-existent dir → `DigestQueryError`; `None` dir → `[]`.
12. `test_query_human_review_tasks` — fixture dir with one task file whose frontmatter has `phase: human_review` and one with `status: in_progress` → only the human_review file yields a task with the right title; `test_query_human_review_tasks_missing_dir` — non-existent dir → `DigestQueryError`, other dirs still scanned.
13. `test_query_chain_aborts` — fixture `.update-logs` dir with a log named `2026-08-20-090000.log` containing `✗ Chain aborted at step manifest-verify: ...` and an out-of-window log `2026-08-01-090000.log` with the same line → only the in-window file yields an abort; non-existent dir → `[]`.
14. `test_query_failed_builds` — `_run_query` returns gh run list JSON with one `conclusion == "failure"` in-window, one failure out-of-window, one success in-window → only the first yields a `FailedBuild`.
15. `test_render_full_digest` — `Digest(since="2026-08-14", until="2026-08-21", repos=["bborbe/a", "bborbe/b"], workdir=tmp_path)` with `query_tags`/`query_pull_requests`/`query_failed_builds`/`query_parked_advisories`/`query_human_review_tasks`/`query_chain_aborts` all patched to deterministic data → `render()` text contains the exact headings `## Go versions bumped`, `## Pull requests`, `## Releases cut`, `## Exceptions`, the `Summary:` line with the right `X/Y`, the version bump line `a: v1.25.2 -> v1.25.3`, a PR line, a parked-advisory line, a failed-build line, a chain-abort line, and a human_review line, and NO `## Query errors` section.
16. `test_render_no_updates_this_week` — all PRs merged outside the window → text contains `0/2 repos updated this week` and the literal `no updates this week` in the versions and PRs sections, and the exceptions STILL render (the negative-signal failure mode).
17. `test_render_source_error_degrades` — `query_tags` raises `DigestQueryError("tags for bborbe/a", "fatal: repository not found")` while `query_pull_requests` succeeds → `render()` still returns text whose `## Query errors` section contains `tags for bborbe/a`, and the PR section still renders (per-source degradation).
18. `test_run_dry_run_prints_no_send` — `Digest(...)` with all queries patched; capture output via `patch("updater.digest.log_message")` with a `Mock(side_effect=...)` appending to a list; `run()` returns 0 and the captured output contains the full digest text (assert the `Summary:` line is present).
19. `test_run_invalid_date` — `since="not-a-date"` → `run()` returns 1 and the logged message names the invalid range.
20. `test_run_empty_fleet` — `repos=[]` → `run()` returns 1 and the logged message mentions `DIGEST_FLEET_REPOS`.
21. `test_query_pull_requests_command_boundary` — boundary test: patch `_run_query` with a spy and assert `query_pull_requests("bborbe/a", ...)` invokes it with EXACTLY `gh pr list --repo bborbe/a --search 'head:updater' --state all --limit 100 --json number,title,state,createdAt,mergedAt,closedAt,url` (the single-quoted `head:updater` shell form — a wrong quote form silently returns nothing).
22. `test_query_tags_command_boundary` — patch `_run_query` with a spy and assert `query_tags("bborbe/a", ...)` invokes it with EXACTLY `git ls-remote --tags https://github.com/bborbe/a.git` (the repo string is validated/constant — no user-supplied input reaches the shell).

### `tests/test_cli.py` (append a `TestMainUpdaterDigest` class)

23. `test_digest_subcommand_dispatch_dry_run` — `patch("sys.argv", ["updater", "digest", "--dry-run"])`; `patch("updater.cli.Digest")` with `.return_value.run` a Mock returning 0; `patch("updater.cli.default_week_window", return_value=("2026-08-14", "2026-08-21"))`; assert exit 0; assert `Digest` constructed with `since="2026-08-14"`, `until="2026-08-21"`, `dry_run=True`, `workdir=Path.cwd()`; `run` called once.
24. `test_digest_subcommand_dispatch_custom_window` — `sys.argv` with `--since 2026-08-01 --until 2026-08-07` → `Digest` constructed with those values.
25. `test_digest_subcommand_dispatch_default_no_dry_run` — `sys.argv = ["updater", "digest"]` → `Digest` constructed with `dry_run=False`.

Coverage: new module must have ≥80% statement coverage — verify with `uv run --with pytest-cov pytest --cov=updater.digest --cov-report=term-missing tests/test_digest.py tests/test_cli.py`.
</requirements>

<constraints>
- Lives in `src/updater/` as a module following the repo's conventions; CLI wiring in `cli.py`; reuses `git_operations.py` (gh invocation form), `config.py`, `log_manager.py` — no new bespoke git implementation, NO changes to `chain.py`, the four handler modules, or `infra_tier.py`.
- The digest is READ-ONLY reporting: it never mutates repos, opens/closes PRs, or changes state — it only queries and reports (spec constraint).
- No shell injection: repo names and tags are validated constants (from `DIGEST_FLEET_REPOS` / the git/gh command strings), never interpolated into shell commands outside the `_run_query` boundary; delivery content is generated from repo metadata — no free-text from sources reaches a shell.
- No credentials are handled by the digest itself; `gh`/git auth are the operator's ambient session. No secrets written to logs.
- A source query failure (rate limit, repo missing, malformed data) degrades gracefully: back off + retry with jitter (bounded) for rate limits, then render the affected section with a NAMED error — never a silent empty section, never a raw traceback.
- `--dry-run` prints the full digest and sends nothing; `--since`/`--until` override the default trailing-7-day window (both validated as `YYYY-MM-DD`).
- Follow project Python conventions (pytest, type hints, uv, Google-style docstrings); no `print` — use `log_message()`; no new dependencies beyond what pyproject.toml already declares.
- `make precommit` stays green; existing tests unchanged.
- `## Unreleased` CHANGELOG bullet for the new subcommand (autoRelease repo).
- Do NOT commit — dark-factory handles git.
</constraints>

## 9. Operator configuration for AC verification

`config.DIGEST_PARK_LIST_DIR` and `config.DIGEST_HUMAN_REVIEW_DIRS` are REQUIRED for spec AC2 (surfacing parked advisories + `human_review` tasks) and the sample-verification rung. Confirm both point at the real locations on this machine — the park-list dir at github-update-go-agent's plan outputs (`Outcome="needs_input"` JSON), the human_review dirs at the vault `24 Tasks/` + `OpenClaw/tasks/` (the defaults in requirement 1 are the spec-named locations; adjust if this machine differs). A default run with no parked advisory / human_review items renders "none" for those sections — that is correct only when the sources are genuinely empty, not when they are misconfigured.

<verification>
Run `make precommit` — must exit 0 (sync + format + test + lint + typecheck).

Confirm the digest module, helpers, and class exist:
```
grep -nE 'class (Digest|DigestQueryError|PullRequest|ParkedAdvisory|HumanReviewTask|ChainAbortInfo|FailedBuild)|def (default_week_window|validate_date|_in_window|_run_query|query_tags|parse_tags|query_pull_requests|parse_pull_requests|pr_events|query_parked_advisories|query_human_review_tasks|parse_task_frontmatter|query_chain_aborts|query_failed_builds|sort_tags)' src/updater/digest.py
```

Confirm the CLI subcommand exists:
```
grep -n 'digest' src/updater/cli.py
```

Confirm no production file outside the allowed set changed:
```
git diff --stat -- src/updater/chain.py src/updater/git_operations.py src/updater/infra_tier.py src/updater/claude_yolo_handler.py src/updater/dark_factory_handler.py src/updater/bundlewrap_handler.py src/updater/trading_handler.py
```
(Expected: empty — nothing may change in the chain, git_operations, infra_tier, or the handler modules.)

Run the new unit tests:
```
uv run pytest tests/test_digest.py tests/test_cli.py -q
```

Coverage check for the new module (≥80%):
```
uv run --with pytest-cov pytest --cov=updater.digest --cov-report=term-missing tests/test_digest.py tests/test_cli.py
```

Manual dry-run — the graceful-degradation container evidence (deterministic): the container has `gh` but no GitHub auth, so `gh` queries fail; `git ls-remote` against public repos may succeed (no auth needed). Either way the digest must render with the `## Query errors` section naming each failing source and exit 0 (the spec failure-mode behavior, verified in-container):
```
uv run updater digest --dry-run --since 2026-08-14 --until 2026-08-21
```
The output must contain the headings `## Go versions bumped`, `## Pull requests`, `## Releases cut`, `## Exceptions`, and `## Query errors` with at least one named source error, and the command must exit 0. (This is the same check the next prompt repeats after delivery is wired; `--dry-run` sends nothing.)

Invalid-date guard (deterministic):
```
uv run updater digest --dry-run --since not-a-date
```
The output must name the invalid range and exit 1.
</verification>
