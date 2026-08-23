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

import yaml

from . import config
from .log_manager import log_message

WEEK_WINDOW_DAYS = 7
RATE_LIMIT_RE = re.compile(r"(?:403|429)")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
QUERY_TIMEOUT_SECONDS = 300
RATE_LIMIT_RETRIES = 3
GH_PR_SEARCH = "head:updater"
VERSION_TAG_RE = re.compile(r"^v?\d+(\.\d+)+$")


class DigestQueryError(Exception):
    """A named source-query failure (rate limit, repo missing, malformed data).

    Carries a human-readable message that is rendered verbatim into the
    affected section — the digest never silently drops a failed source.
    """

    def __init__(self, source: str, message: str) -> None:
        self.source = source
        self.message = message
        super().__init__(f"{source}: {message}")


def default_week_window(now: datetime | None = None) -> tuple[str, str]:
    """Return (since, until) ISO dates for the trailing 7-day window ending at now.

    Args:
        now: End of the window; defaults to the current time

    Returns:
        A (since, until) pair of YYYY-MM-DD strings covering the inclusive
        trailing WEEK_WINDOW_DAYS ending at now
    """
    end = now or datetime.now()
    start = end - timedelta(days=WEEK_WINDOW_DAYS)
    return (start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))


def validate_date(value: str) -> bool:
    """Return whether value is a valid YYYY-MM-DD date (regex + real-date check).

    Args:
        value: Candidate date string

    Returns:
        True if value is a well-formed calendar date, False otherwise
    """
    if not DATE_RE.fullmatch(value):
        return False
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


def _in_window(iso_timestamp: str | None, since: str, until: str) -> bool:
    """Return whether iso_timestamp's date falls within the inclusive [since, until] window.

    Args:
        iso_timestamp: ISO-8601 timestamp or YYYY-MM-DD date (or None)
        since: Inclusive window start (YYYY-MM-DD)
        until: Inclusive window end (YYYY-MM-DD)

    Returns:
        True if the timestamp's date is within the window, False otherwise
        (including unparseable or empty timestamps)
    """
    if not iso_timestamp:
        return False
    try:
        ts_date = datetime.fromisoformat(iso_timestamp.replace("Z", "+00:00")).date()
    except ValueError:
        return False
    return date.fromisoformat(since) <= ts_date <= date.fromisoformat(until)


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

    Args:
        cmd: Shell command to run
        cwd: Working directory for the command
        source: Source name that names a failure (e.g. "tags for bborbe/updater")
        log_func: Logging function to use

    Returns:
        The command's stdout

    Raises:
        DigestQueryError: If the command times out, is rate-limited after
            bounded retries, or exits non-zero
    """
    for attempt in range(RATE_LIMIT_RETRIES + 1):
        try:
            result = subprocess.run(
                cmd,
                shell=True,
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=QUERY_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired:
            raise DigestQueryError(
                source, f"{cmd} timed out after {QUERY_TIMEOUT_SECONDS}s"
            ) from None

        if RATE_LIMIT_RE.search((result.stdout or "") + (result.stderr or "")):
            if attempt < RATE_LIMIT_RETRIES:
                delay = 1.0 + random.uniform(0.0, 2.0)
                log_func(f"rate limit on {source}; backing off {delay:.0f}s", to_console=True)
                time.sleep(delay)
            continue
        if result.returncode != 0:
            raise DigestQueryError(
                source, (result.stderr or result.stdout or "command failed").strip()
            )
        return result.stdout or ""

    raise DigestQueryError(source, "GitHub API rate limit — backed off and retried; still limited")


def parse_tags(raw: str) -> list[str]:
    """Parse `git ls-remote --tags` stdout into a raw tag-name list.

    Args:
        raw: The command's stdout

    Returns:
        Tag names with the refs/tags/ prefix stripped and peeled ^{} lines
        skipped; unsorted
    """
    tags: list[str] = []
    for line in raw.splitlines():
        if "\t" not in line:
            continue
        _, ref = line.split("\t", 1)
        if ref.endswith("^{}"):
            continue
        tags.append(ref.removeprefix("refs/tags/"))
    return tags


def query_tags(repo: str, cwd: Path, log_func: Callable[..., None] = log_message) -> list[str]:
    """Return the repo's git tags via `git ls-remote --tags` (unsorted).

    Args:
        repo: GitHub repository in owner/name form (validated fleet constant)
        cwd: Working directory for the command
        log_func: Logging function to use

    Returns:
        Tag names, or an empty list for a repo with no tags

    Raises:
        DigestQueryError: If the query fails (e.g. repo missing)
    """
    raw = _run_query(
        f"git ls-remote --tags https://github.com/{repo}.git",
        cwd=cwd,
        source=f"tags for {repo}",
        log_func=log_func,
    )
    return parse_tags(raw)


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
    """Parse gh pr list JSON output into PullRequest objects.

    Args:
        repo: GitHub repository in owner/name form
        raw_json: The command's stdout

    Returns:
        The parsed pull requests

    Raises:
        json.JSONDecodeError: If raw_json is not valid JSON
    """
    data = json.loads(raw_json)
    return [
        PullRequest(
            repo=repo,
            number=int(item["number"]),
            title=item["title"],
            state=item["state"],
            created_at=item["createdAt"],
            merged_at=item["mergedAt"],
            closed_at=item["closedAt"],
            url=item["url"],
        )
        for item in data
    ]


def pr_events(pr: PullRequest, since: str, until: str) -> set[str]:
    """Return the subset of {"opened", "merged", "closed"} events in the window.

    Args:
        pr: The pull request to evaluate
        since: Inclusive window start (YYYY-MM-DD)
        until: Inclusive window end (YYYY-MM-DD)

    Returns:
        The set of events that occurred inside the window
    """
    events: set[str] = set()
    if _in_window(pr.created_at, since, until):
        events.add("opened")
    if pr.state == "MERGED" and _in_window(pr.merged_at, since, until):
        events.add("merged")
    if pr.state == "CLOSED" and _in_window(pr.closed_at, since, until):
        events.add("closed")
    return events


def query_pull_requests(
    repo: str,
    since: str,
    until: str,
    cwd: Path,
    log_func: Callable[..., None] = log_message,
) -> list[PullRequest]:
    """Return the repo's head:updater PRs with at least one event in the window.

    Args:
        repo: GitHub repository in owner/name form (validated fleet constant)
        since: Inclusive window start (YYYY-MM-DD)
        until: Inclusive window end (YYYY-MM-DD)
        cwd: Working directory for the command
        log_func: Logging function to use

    Returns:
        The in-window pull requests; empty if none

    Raises:
        DigestQueryError: If the query fails or gh returns malformed JSON
    """
    cmd = (
        f"gh pr list --repo {repo} --search '{GH_PR_SEARCH}' --state all --limit 100 "
        "--json number,title,state,createdAt,mergedAt,closedAt,url"
    )
    raw = _run_query(cmd, cwd=cwd, source=f"PRs for {repo}", log_func=log_func)
    try:
        prs = parse_pull_requests(repo, raw)
    except json.JSONDecodeError:
        raise DigestQueryError(f"PRs for {repo}", "malformed gh pr list JSON") from None
    return [pr for pr in prs if pr_events(pr, since, until)]


@dataclass(frozen=True)
class ParkedAdvisory:
    """A parked no-fix advisory from the github-update-go-agent park list."""

    repo: str
    vuln_id: str
    package: str
    reason: str


def query_parked_advisories(
    park_list_dir: Path | None, log_func: Callable[..., None] = log_message
) -> list[ParkedAdvisory]:
    """Return parked advisories from the agent's park-list JSON files.

    Each file is shaped like the PlanOutput contract: an object with an
    optional "outcome", "reason", and a "vulns" list whose entries carry
    "action": "park" for parked no-fix advisories.

    Args:
        park_list_dir: Directory of park-list JSON files, or None for none
        log_func: Logging function to use

    Returns:
        One ParkedAdvisory per park action found

    Raises:
        DigestQueryError: If the directory is configured but missing, or a
            file is malformed (invalid JSON or not a dict)
    """
    if park_list_dir is None:
        return []
    if not park_list_dir.exists():
        raise DigestQueryError("park list", f"park-list dir not found: {park_list_dir}")

    advisories: list[ParkedAdvisory] = []
    malformed: list[str] = []
    for file in park_list_dir.glob("*.json"):
        try:
            data = json.loads(file.read_text())
        except json.JSONDecodeError, OSError:
            malformed.append(file.name)
            continue
        if not isinstance(data, dict):
            malformed.append(file.name)
            continue
        file_reason = data.get("reason")
        vulns = data.get("vulns", [])
        if not isinstance(vulns, list):
            continue
        for vuln in vulns:
            if not isinstance(vuln, dict) or vuln.get("action") != "park":
                continue
            advisories.append(
                ParkedAdvisory(
                    repo=file.stem,
                    vuln_id=vuln.get("id", ""),
                    package=vuln.get("package", ""),
                    reason=vuln.get("reason") or (file_reason or ""),
                )
            )
    if malformed:
        raise DigestQueryError("park list", f"{malformed[0]}: malformed park-list JSON")
    return advisories


@dataclass(frozen=True)
class HumanReviewTask:
    """A task file flagged human_review (status or phase) in the vault/OpenClaw dirs."""

    path: Path
    title: str


def _first_content_line(text: str) -> str:
    """Return the first non-empty line outside the leading YAML frontmatter.

    Args:
        text: A markdown file's text

    Returns:
        The first non-empty, non-frontmatter line, or an empty string
    """
    lines = text.splitlines()
    start = 0
    if lines and lines[0].strip() == "---":
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                start = i + 1
                break
    for line in lines[start:]:
        if line.strip():
            return line.strip()
    return ""


def parse_task_frontmatter(text: str) -> dict:
    """Extract and parse the YAML block between the leading --- fences.

    Args:
        text: A task file's text

    Returns:
        The parsed frontmatter dict, or {} when there is no frontmatter or
        the block is unparseable (never raises)
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    end = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end = i
            break
    if end is None:
        return {}
    try:
        data = yaml.safe_load("\n".join(lines[1:end]))
    except yaml.YAMLError:
        return {}
    return data if isinstance(data, dict) else {}


def query_human_review_tasks(
    human_review_dirs: list[Path], log_func: Callable[..., None] = log_message
) -> list[HumanReviewTask]:
    """Return task files flagged human_review (status or phase) under the given dirs.

    Args:
        human_review_dirs: Directories to scan recursively for *.md task files
        log_func: Logging function to use

    Returns:
        One HumanReviewTask per matching file

    Raises:
        DigestQueryError: If any configured directory is missing (the other
            dirs are still scanned)
    """
    tasks: list[HumanReviewTask] = []
    errors: list[str] = []
    for directory in human_review_dirs:
        if not directory.exists():
            errors.append(f"task dir not found: {directory}")
            continue
        for file in directory.rglob("*.md"):
            try:
                text = file.read_text()
            except OSError:
                continue
            frontmatter = parse_task_frontmatter(text)
            if (
                frontmatter.get("status") != "human_review"
                and frontmatter.get("phase") != "human_review"
            ):
                continue
            title = frontmatter.get("title")
            if not title:
                title = _first_content_line(text)
            tasks.append(HumanReviewTask(path=file, title=str(title)))
    if errors:
        raise DigestQueryError("human_review", errors[0])
    return tasks


@dataclass(frozen=True)
class ChainAbortInfo:
    """A chain-abort line from an updater run log within the window."""

    log_file: Path
    line: str


def query_chain_aborts(
    log_dir: Path,
    since: str,
    until: str,
    log_func: Callable[..., None] = log_message,
) -> list[ChainAbortInfo]:
    """Return chain-abort lines from in-window updater run logs.

    The log filename encodes the run timestamp in config.RUN_TIMESTAMP format
    (%Y-%m-%d-%H%M%S); a file is in the window iff its date portion (first 10
    chars) is within the inclusive window. Files whose prefix is not parseable
    are skipped.

    Args:
        log_dir: The updater log dir (config.LOG_DIR_NAME, e.g. .update-logs)
        since: Inclusive window start (YYYY-MM-DD)
        until: Inclusive window end (YYYY-MM-DD)
        log_func: Logging function to use

    Returns:
        One ChainAbortInfo per matching line; empty when the dir is missing
    """
    if not log_dir.exists():
        return []
    aborts: list[ChainAbortInfo] = []
    for file in log_dir.glob("*.log"):
        if not _in_window(file.name[:10], since, until):
            continue
        try:
            for line in file.read_text().splitlines():
                if "Chain aborted" in line:
                    aborts.append(ChainAbortInfo(log_file=file, line=line))
        except OSError:
            continue
    return aborts


@dataclass(frozen=True)
class FailedBuild:
    """A failed CI run on master within the window (github-build-watcher semantics)."""

    repo: str
    name: str
    created_at: str
    url: str


def query_failed_builds(
    repo: str,
    since: str,
    until: str,
    cwd: Path,
    log_func: Callable[..., None] = log_message,
) -> list[FailedBuild]:
    """Return the repo's failed master-branch CI runs within the window.

    Args:
        repo: GitHub repository in owner/name form (validated fleet constant)
        since: Inclusive window start (YYYY-MM-DD)
        until: Inclusive window end (YYYY-MM-DD)
        cwd: Working directory for the command
        log_func: Logging function to use

    Returns:
        The failed in-window runs; empty if none

    Raises:
        DigestQueryError: If the query fails or gh returns malformed JSON
    """
    cmd = (
        f"gh run list --repo {repo} --branch master --limit 100 "
        "--json name,conclusion,createdAt,url"
    )
    raw = _run_query(cmd, cwd=cwd, source=f"builds for {repo}", log_func=log_func)
    try:
        runs = json.loads(raw)
    except json.JSONDecodeError:
        raise DigestQueryError(f"builds for {repo}", "malformed gh run list JSON") from None
    builds: list[FailedBuild] = []
    for run in runs:
        if run.get("conclusion") != "failure":
            continue
        if not _in_window(run.get("createdAt"), since, until):
            continue
        builds.append(
            FailedBuild(
                repo=repo,
                name=run.get("name", ""),
                created_at=run.get("createdAt", ""),
                url=run.get("url", ""),
            )
        )
    return builds


def sort_tags(tags: list[str]) -> list[str]:
    """Sort version tags descending by numeric version, dropping non-version tags.

    Args:
        tags: Raw tag names

    Returns:
        Tags matching the v?X.Y.Z... shape, sorted descending numerically
    """
    version_tags = [t for t in tags if VERSION_TAG_RE.match(t)]
    if not version_tags:
        return []
    max_parts = max(len(t.lstrip("v").split(".")) for t in version_tags)

    def _version_key(tag: str) -> list[int]:
        parts = [int(p) for p in tag.lstrip("v").split(".")]
        return parts + [0] * (max_parts - len(parts))

    return sorted(version_tags, key=_version_key, reverse=True)


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
        """Initialize the digest.

        The repos/workdir/park_list_dir/human_review_dirs parameters are the
        testability seam — tests pass explicit tiny fleets and tmp dirs. They
        are not CLI flags.

        Args:
            since: Inclusive window start (YYYY-MM-DD)
            until: Inclusive window end (YYYY-MM-DD)
            repos: Fleet of repos to query; defaults to config.DIGEST_FLEET_REPOS
            dry_run: If True, print the digest and send nothing
            workdir: Working directory for queries; defaults to cwd
            park_list_dir: Park-list directory; defaults to config.DIGEST_PARK_LIST_DIR
            human_review_dirs: Task directories; defaults to config.DIGEST_HUMAN_REVIEW_DIRS
        """
        self._since = since
        self._until = until
        self._repos = list(repos) if repos is not None else list(config.DIGEST_FLEET_REPOS)
        self._dry_run = dry_run
        self._workdir = workdir if workdir is not None else Path.cwd()
        self._park_list_dir = (
            park_list_dir if park_list_dir is not None else config.DIGEST_PARK_LIST_DIR
        )
        self._human_review_dirs = (
            list(human_review_dirs)
            if human_review_dirs is not None
            else list(config.DIGEST_HUMAN_REVIEW_DIRS)
        )
        self._errors: list[str] = []

    def render(self) -> str:
        """Compose the full digest text, degrading gracefully per source.

        A DigestQueryError from any source becomes a named entry in the
        internal error list and rendering continues — never a raw traceback.

        Returns:
            The complete digest text
        """
        self._errors = []
        repo_tags: dict[str, list[str]] = {}
        repo_prs: dict[str, list[PullRequest]] = {}
        repo_builds: dict[str, list[FailedBuild]] = {}
        tag_failed_repos: set[str] = set()

        for repo in self._repos:
            try:
                repo_tags[repo] = query_tags(repo, self._workdir)
            except DigestQueryError as e:
                self._errors.append(str(e))
                tag_failed_repos.add(repo)
                repo_tags[repo] = []
            try:
                repo_prs[repo] = query_pull_requests(repo, self._since, self._until, self._workdir)
            except DigestQueryError as e:
                self._errors.append(str(e))
                repo_prs[repo] = []
            try:
                repo_builds[repo] = query_failed_builds(
                    repo, self._since, self._until, self._workdir
                )
            except DigestQueryError as e:
                self._errors.append(str(e))
                repo_builds[repo] = []

        updated_repos = [
            repo
            for repo in self._repos
            if any(
                "merged" in pr_events(pr, self._since, self._until) for pr in repo_prs.get(repo, [])
            )
        ]

        parked_error: DigestQueryError | None = None
        human_error: DigestQueryError | None = None
        abort_error: DigestQueryError | None = None
        try:
            parked = query_parked_advisories(self._park_list_dir)
        except DigestQueryError as e:
            self._errors.append(str(e))
            parked_error = e
            parked = []
        try:
            human_tasks = query_human_review_tasks(self._human_review_dirs)
        except DigestQueryError as e:
            self._errors.append(str(e))
            human_error = e
            human_tasks = []
        try:
            aborts = query_chain_aborts(
                self._workdir / config.LOG_DIR_NAME, self._since, self._until
            )
        except DigestQueryError as e:
            self._errors.append(str(e))
            abort_error = e
            aborts = []

        lines = [
            "Weekly Go Update Digest",
            f"Window: {self._since} .. {self._until}",
            "",
            f"Summary: {len(updated_repos)}/{len(self._repos)} repos updated this week",
            "",
            "## Go versions bumped",
        ]
        if updated_repos:
            for repo in updated_repos:
                if repo in tag_failed_repos:
                    continue
                sorted_tags = sort_tags(repo_tags.get(repo, []))
                current_tag = sorted_tags[0] if sorted_tags else None
                previous_tag = sorted_tags[1] if len(sorted_tags) > 1 else None
                if current_tag is None:
                    lines.append(f"  - {repo}: (no version tags)")
                elif previous_tag is None:
                    lines.append(f"  - {repo}: {current_tag}")
                else:
                    lines.append(f"  - {repo}: {previous_tag} -> {current_tag}")
        else:
            lines.append("  no updates this week")

        lines.append("")
        lines.append("## Pull requests")
        all_prs = [pr for prs in repo_prs.values() for pr in prs]
        opened = sum(1 for pr in all_prs if "opened" in pr_events(pr, self._since, self._until))
        merged = sum(1 for pr in all_prs if "merged" in pr_events(pr, self._since, self._until))
        closed = sum(1 for pr in all_prs if "closed" in pr_events(pr, self._since, self._until))
        lines.append(f"  opened: {opened}  merged: {merged}  closed: {closed}")
        if all_prs:
            for pr in all_prs:
                lines.append(f"  - {pr.repo} #{pr.number}: {pr.title} ({pr.state}) {pr.url}")
        else:
            lines.append("  no updates this week")

        lines.append("")
        lines.append("## Releases cut")
        if updated_repos:
            for repo in updated_repos:
                if repo in tag_failed_repos:
                    continue
                sorted_tags = sort_tags(repo_tags.get(repo, []))
                current_tag = sorted_tags[0] if sorted_tags else None
                if current_tag is None:
                    lines.append(f"  - {repo}: (no version tags)")
                else:
                    lines.append(f"  - {repo}: {current_tag}")
        else:
            lines.append("  no releases this week")

        lines.append("")
        lines.append("## Exceptions")
        lines.append("  Parked advisories:")
        if parked_error is not None:
            lines.append(f"    {parked_error.source} failed: {parked_error.message}")
        elif parked:
            for advisory in parked:
                lines.append(
                    f"    - {advisory.repo}: {advisory.vuln_id} in "
                    f"{advisory.package} — {advisory.reason}"
                )
        else:
            lines.append("    none")
        lines.append("  Failed builds:")
        all_builds = [build for builds in repo_builds.values() for build in builds]
        if all_builds:
            for build in all_builds:
                lines.append(f"    - {build.repo}: {build.name} ({build.url})")
        else:
            lines.append("    none")
        lines.append("  Chain aborts:")
        if abort_error is not None:
            lines.append(f"    {abort_error.source} failed: {abort_error.message}")
        elif aborts:
            for abort in aborts:
                lines.append(f"    - {abort.log_file.name}: {abort.line}")
        else:
            lines.append("    none")
        lines.append("  human_review tasks:")
        if human_error is not None:
            lines.append(f"    {human_error.source} failed: {human_error.message}")
        elif human_tasks:
            for task in human_tasks:
                lines.append(f"    - {task.path}: {task.title}")
        else:
            lines.append("    none")

        if self._errors:
            lines.append("")
            lines.append("## Query errors")
            lines.extend(f"  - {error}" for error in self._errors)

        return "\n".join(lines)

    def run(self) -> int:
        """Validate, render, and print the digest (the CLI entry).

        Returns:
            Exit code: 0 on success, 1 on invalid date range or empty fleet
        """
        if not validate_date(self._since) or not validate_date(self._until):
            log_message(
                f"✗ Invalid date range: {self._since!r} .. {self._until!r} (expected YYYY-MM-DD)",
                to_console=True,
            )
            return 1
        if not self._repos:
            log_message("✗ Empty fleet — check config.DIGEST_FLEET_REPOS", to_console=True)
            return 1
        log_message(self.render(), to_console=True)
        return 0
