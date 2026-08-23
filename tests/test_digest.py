"""Tests for the weekly Go-update digest module."""

import json
import subprocess
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from updater.digest import (
    ChainAbortInfo,
    Digest,
    DigestQueryError,
    FailedBuild,
    HumanReviewTask,
    ParkedAdvisory,
    PullRequest,
    _in_window,
    _run_query,
    default_week_window,
    parse_pull_requests,
    parse_tags,
    parse_task_frontmatter,
    pr_events,
    query_chain_aborts,
    query_failed_builds,
    query_human_review_tasks,
    query_parked_advisories,
    query_pull_requests,
    query_tags,
    sort_tags,
    validate_date,
)


def _completed(returncode: int, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess:
    """Build a CompletedProcess with the given result for use as a query result."""
    return subprocess.CompletedProcess(
        args=["probe"], returncode=returncode, stdout=stdout, stderr=stderr
    )


def _capture_messages() -> tuple[list[str], object]:
    """Return a message list and a log side-effect that fills it."""
    messages: list[str] = []

    def _log(message: str, *args, **kwargs) -> None:
        messages.append(message)

    return messages, _log


def _make_pr(
    *,
    number: int,
    state: str,
    created_at: str,
    merged_at: str | None = None,
    closed_at: str | None = None,
) -> PullRequest:
    """Build a PullRequest for the bborbe/a repo with the given event timestamps."""
    return PullRequest(
        repo="bborbe/a",
        number=number,
        title="Bump Go",
        state=state,
        created_at=created_at,
        merged_at=merged_at,
        closed_at=closed_at,
        url=f"https://github.com/bborbe/a/pull/{number}",
    )


def test_default_week_window():
    """Test the trailing-7-day window defaults to (7 days ago, today)."""
    assert default_week_window(now=datetime(2026, 8, 21, 12, 0, 0)) == (
        "2026-08-14",
        "2026-08-21",
    )


def test_default_week_window_defaults_to_now():
    """Test the now=None path uses the current time and yields a valid window."""
    since, until = default_week_window()
    assert validate_date(since)
    assert validate_date(until)
    assert since <= until


def test_validate_date_accepts():
    """Test a valid YYYY-MM-DD date is accepted."""
    assert validate_date("2026-08-21")


def test_validate_date_rejects():
    """Test malformed and impossible dates are rejected."""
    assert not validate_date("2026-8-21")
    assert not validate_date("2026-13-01")
    assert not validate_date("not-a-date")
    assert not validate_date("")


def test_in_window_inclusive():
    """Test the window is inclusive on both ends and rejects outside/None/malformed."""
    since, until = "2026-08-14", "2026-08-21"
    assert _in_window("2026-08-14T00:00:00Z", since, until)
    assert _in_window("2026-08-21T23:59:59Z", since, until)
    assert not _in_window("2026-08-13T23:59:59Z", since, until)
    assert not _in_window("2026-08-22T00:00:00Z", since, until)
    assert not _in_window(None, since, until)
    assert not _in_window("", since, until)
    assert not _in_window("not-a-timestamp", since, until)


def test_parse_tags():
    """Test ls-remote tag parsing skips peeled lines and strips refs/tags/."""
    raw = (
        "abc123\trefs/tags/v1.25.2\n"
        "def456\trefs/tags/v1.25.3\n"
        "ghi789\trefs/tags/v1.25.3^{}\n"
        "jkl012\trefs/tags/nightly\n"
    )
    assert parse_tags(raw) == ["v1.25.2", "v1.25.3", "nightly"]


def test_sort_tags_descending():
    """Test version tags sort descending numerically with non-version tags dropped."""
    assert sort_tags(["v1.25.2", "v1.25.3", "v1.9.0", "nightly"]) == [
        "v1.25.3",
        "v1.25.2",
        "v1.9.0",
    ]


def test_sort_tags_pads_parts():
    """Test tags with differing part counts sort numerically (v1.2 < v1.2.3)."""
    assert sort_tags(["v1.2", "v1.9.0", "v1.2.3"]) == ["v1.9.0", "v1.2.3", "v1.2"]


def test_sort_tags_no_version_tags():
    """Test an all-non-version tag list sorts to empty."""
    assert sort_tags(["nightly", "latest"]) == []


def test_parse_pull_requests():
    """Test gh pr list JSON parses into PullRequest objects with all seven keys."""
    raw = json.dumps(
        [
            {
                "number": 42,
                "title": "Bump Go 1.28.0",
                "state": "MERGED",
                "createdAt": "2026-08-15T10:00:00Z",
                "mergedAt": "2026-08-16T10:00:00Z",
                "closedAt": None,
                "url": "https://github.com/bborbe/a/pull/42",
            }
        ]
    )
    prs = parse_pull_requests("bborbe/a", raw)
    assert len(prs) == 1
    assert prs[0].repo == "bborbe/a"
    assert prs[0].number == 42
    assert prs[0].title == "Bump Go 1.28.0"
    assert prs[0].state == "MERGED"
    assert prs[0].created_at == "2026-08-15T10:00:00Z"
    assert prs[0].merged_at == "2026-08-16T10:00:00Z"
    assert prs[0].closed_at is None
    assert prs[0].url == "https://github.com/bborbe/a/pull/42"


def test_pr_events():
    """Test pr_events returns the in-window event subset."""
    since, until = "2026-08-14", "2026-08-21"
    assert pr_events(
        _make_pr(
            number=1,
            state="MERGED",
            created_at="2026-08-15T10:00:00Z",
            merged_at="2026-08-16T10:00:00Z",
        ),
        since,
        until,
    ) == {"opened", "merged"}
    assert pr_events(
        _make_pr(
            number=2,
            state="MERGED",
            created_at="2026-08-15T10:00:00Z",
            merged_at="2026-09-01T10:00:00Z",
        ),
        since,
        until,
    ) == {"opened"}
    assert (
        pr_events(
            _make_pr(
                number=3,
                state="CLOSED",
                created_at="2026-09-01T10:00:00Z",
                closed_at="2026-09-02T10:00:00Z",
            ),
            since,
            until,
        )
        == set()
    )
    assert pr_events(
        _make_pr(
            number=4,
            state="CLOSED",
            created_at="2026-08-15T10:00:00Z",
            closed_at="2026-08-17T10:00:00Z",
        ),
        since,
        until,
    ) == {"opened", "closed"}


def test_query_pull_requests_malformed_json(tmp_path):
    """Test malformed gh JSON raises a DigestQueryError naming the PR source."""
    with patch("updater.digest._run_query", return_value="not json"):
        with pytest.raises(DigestQueryError) as exc_info:
            query_pull_requests("bborbe/a", "2026-08-14", "2026-08-21", tmp_path)
    assert "PRs for" in str(exc_info.value)


def test_query_tags_repo_missing(tmp_path):
    """Test a repo-missing git failure propagates as a DigestQueryError naming tags."""
    with patch(
        "updater.digest._run_query",
        side_effect=DigestQueryError("tags for bborbe/a", "fatal: repository not found"),
    ):
        with pytest.raises(DigestQueryError) as exc_info:
            query_tags("bborbe/a", tmp_path)
    assert "tags for" in str(exc_info.value)


def test_run_query_nonzero_exit_raises(tmp_path):
    """Test a non-zero exit with stderr raises a DigestQueryError with the stderr."""
    with patch(
        "updater.digest.subprocess.run",
        return_value=_completed(128, stderr="fatal: repository not found"),
    ):
        with pytest.raises(DigestQueryError) as exc_info:
            _run_query("git ls-remote", cwd=tmp_path, source="tags for bborbe/a")
    assert "fatal: repository not found" in str(exc_info.value)


def test_run_query_command_failed_fallback(tmp_path):
    """Test a non-zero exit with no output uses the 'command failed' fallback."""
    with patch("updater.digest.subprocess.run", return_value=_completed(1)):
        with pytest.raises(DigestQueryError) as exc_info:
            _run_query("some-cmd", cwd=tmp_path, source="builds for bborbe/a")
    assert "command failed" in str(exc_info.value)


def test_run_query_timeout_raises(tmp_path):
    """Test a hung query raises a DigestQueryError naming the timeout."""
    with patch(
        "updater.digest.subprocess.run",
        side_effect=subprocess.TimeoutExpired(cmd="gh pr list", timeout=300),
    ):
        with pytest.raises(DigestQueryError) as exc_info:
            _run_query("gh pr list", cwd=tmp_path, source="PRs for bborbe/a")
    assert "timed out" in str(exc_info.value)


def test_rate_limit_retries_then_succeeds(tmp_path):
    """Test a 403 rate limit backs off with jitter and retries until success."""
    messages, log_side_effect = _capture_messages()
    results = [
        _completed(1, stderr="API rate limit exceeded (403)"),
        _completed(0, stdout="[ok]"),
    ]
    with (
        patch("updater.digest.subprocess.run", side_effect=results),
        patch("updater.digest.random.uniform", return_value=0.0),
        patch("updater.digest.time.sleep") as mock_sleep,
    ):
        stdout = _run_query(
            "gh pr list", cwd=tmp_path, source="PRs for bborbe/a", log_func=log_side_effect
        )

    assert stdout == "[ok]"
    assert mock_sleep.call_count == 1
    assert any("rate limit on PRs for bborbe/a" in m and "backing off" in m for m in messages)


def test_rate_limit_exhausted_raises(tmp_path):
    """Test persistent rate limiting raises a DigestQueryError after bounded retries."""
    always_limited = _completed(1, stderr="API rate limit exceeded (403)")
    with (
        patch("updater.digest.subprocess.run", return_value=always_limited),
        patch("updater.digest.random.uniform", return_value=0.0),
        patch("updater.digest.time.sleep"),
    ):
        with pytest.raises(DigestQueryError) as exc_info:
            _run_query("gh pr list", cwd=tmp_path, source="PRs for bborbe/a")
    assert "rate limit" in str(exc_info.value)


def test_run_id_containing_429_in_stdout_is_not_rate_limit(tmp_path):
    """Test a run ID like .../runs/22642940905 in stdout is NOT a rate limit.

    Regression: RATE_LIMIT_RE matches bare 403|429 anywhere, and gh run list JSON
    legitimately contains run IDs with 429 — a healthy query was misclassified as
    rate-limited and degraded instead of returning data. Detection now checks stderr
    only (gh/git errors go to stderr; data goes to stdout).
    """
    messages, log_side_effect = _capture_messages()
    healthy = _completed(
        0,
        stdout='[{"name":"CI","url":"https://github.com/bborbe/a/actions/runs/22642940905"}]',
    )
    with patch("updater.digest.subprocess.run", return_value=healthy):
        stdout = _run_query(
            "gh run list", cwd=tmp_path, source="builds for bborbe/a", log_func=log_side_effect
        )

    assert "22642940905" in stdout
    assert not any("rate limit" in m for m in messages)


def test_query_parked_advisories(tmp_path):
    """Test park-list JSON files yield one advisory per park action with repo=file stem."""
    (tmp_path / "bborbe-a.json").write_text(
        json.dumps(
            {
                "outcome": "needs_input",
                "vulns": [
                    {
                        "id": "GO-2026-1",
                        "package": "golang.org/x/foo",
                        "action": "park",
                        "reason": "no upstream fix",
                    }
                ],
            }
        )
    )
    (tmp_path / "bborbe-b.json").write_text(json.dumps({"action": "fix"}))
    advisories = query_parked_advisories(tmp_path)
    assert len(advisories) == 1
    assert advisories[0].repo == "bborbe-a"
    assert advisories[0].vuln_id == "GO-2026-1"
    assert advisories[0].package == "golang.org/x/foo"
    assert advisories[0].reason == "no upstream fix"


def test_query_parked_advisories_file_reason_fallback(tmp_path):
    """Test a park vuln without its own reason falls back to the file-level reason."""
    (tmp_path / "bborbe-a.json").write_text(
        json.dumps(
            {
                "outcome": "needs_input",
                "reason": "no upstream fix",
                "vulns": [{"id": "GO-2026-2", "package": "golang.org/x/bar", "action": "park"}],
            }
        )
    )
    advisories = query_parked_advisories(tmp_path)
    assert len(advisories) == 1
    assert advisories[0].reason == "no upstream fix"


def test_query_parked_advisories_malformed(tmp_path):
    """Test an invalid-JSON park file raises a DigestQueryError naming the file."""
    (tmp_path / "broken.json").write_text("{not json")
    with pytest.raises(DigestQueryError) as exc_info:
        query_parked_advisories(tmp_path)
    assert "broken.json" in str(exc_info.value)


def test_query_parked_advisories_not_a_dict(tmp_path):
    """Test a non-dict park file raises a DigestQueryError naming the file."""
    (tmp_path / "list.json").write_text("[1, 2, 3]")
    with pytest.raises(DigestQueryError) as exc_info:
        query_parked_advisories(tmp_path)
    assert "list.json" in str(exc_info.value)


def test_query_parked_advisories_missing_dir(tmp_path):
    """Test a configured-but-missing park-list dir raises a DigestQueryError."""
    with pytest.raises(DigestQueryError) as exc_info:
        query_parked_advisories(tmp_path / "missing")
    assert "park-list dir not found" in str(exc_info.value)


def test_query_parked_advisories_none_dir():
    """Test a None park-list dir yields no advisories."""
    assert query_parked_advisories(None) == []


def test_parse_task_frontmatter():
    """Test frontmatter extraction returns the parsed dict."""
    assert parse_task_frontmatter("---\ntitle: Task\nstatus: human_review\n---\nBody") == {
        "title": "Task",
        "status": "human_review",
    }


def test_parse_task_frontmatter_edge_cases():
    """Test unparseable / absent / non-dict frontmatter yields {}."""
    assert parse_task_frontmatter("no frontmatter") == {}
    assert parse_task_frontmatter("---\n: : : bad\n---") == {}
    assert parse_task_frontmatter("---\n- a\n- b\n---") == {}
    assert parse_task_frontmatter("---\nno closing fence") == {}


def test_query_human_review_tasks(tmp_path):
    """Test human_review-flagged task files yield tasks; others are skipped."""
    tasks_dir = tmp_path / "24 Tasks"
    tasks_dir.mkdir()
    (tasks_dir / "phase.md").write_text(
        "---\ntitle: Phase task\nphase: human_review\n---\n# Body\n"
    )
    (tasks_dir / "status.md").write_text(
        "---\ntitle: Status task\nstatus: human_review\n---\n# Body\n"
    )
    (tasks_dir / "inprogress.md").write_text(
        "---\ntitle: In progress\nstatus: in_progress\n---\n# Body\n"
    )
    (tasks_dir / "no-title.md").write_text("---\nphase: human_review\n---\nFirst content line\n")
    (tasks_dir / "no-frontmatter.md").write_text("No frontmatter here\n")
    nested = tasks_dir / "sub"
    nested.mkdir()
    (nested / "nested.md").write_text("---\nstatus: human_review\n---\nNested task\n")

    tasks = query_human_review_tasks([tasks_dir])
    names = {t.path.name for t in tasks}
    assert {"phase.md", "status.md", "no-title.md", "nested.md"} <= names
    assert "inprogress.md" not in names
    assert "no-frontmatter.md" not in names
    by_name = {t.path.name: t for t in tasks}
    assert by_name["phase.md"].title == "Phase task"
    assert by_name["no-title.md"].title == "First content line"


def test_query_human_review_tasks_missing_dir(tmp_path):
    """Test a missing task dir raises a DigestQueryError but other dirs still scan."""
    valid = tmp_path / "valid"
    valid.mkdir()
    (valid / "ok.md").write_text("---\nstatus: human_review\n---\nOk task\n")
    with pytest.raises(DigestQueryError) as exc_info:
        query_human_review_tasks([tmp_path / "missing", valid])
    assert "task dir not found" in str(exc_info.value)


def test_query_human_review_tasks_empty_dir(tmp_path):
    """Test an existing dir with no task files yields no tasks."""
    assert query_human_review_tasks([tmp_path]) == []


def test_query_chain_aborts(tmp_path):
    """Test in-window run logs yield chain-abort lines; others are skipped."""
    log_dir = tmp_path / ".update-logs"
    log_dir.mkdir()
    (log_dir / "2026-08-20-090000.log").write_text(
        "Update Log - 2026-08-20-090000\n✗ Chain aborted at step manifest-verify: boom\n"
    )
    (log_dir / "2026-08-01-090000.log").write_text("✗ Chain aborted at step claude-yolo: old\n")
    (log_dir / "notes.log").write_text("✗ Chain aborted at step trading: unparseable\n")
    (log_dir / "2026-08-20-100000.log").write_text("no aborts here\n")

    aborts = query_chain_aborts(log_dir, "2026-08-14", "2026-08-21")
    assert len(aborts) == 1
    assert aborts[0].log_file.name == "2026-08-20-090000.log"
    assert "manifest-verify" in aborts[0].line


def test_query_chain_aborts_missing_dir(tmp_path):
    """Test a missing log dir yields no aborts (no chain runs yet)."""
    assert query_chain_aborts(tmp_path / "missing", "2026-08-14", "2026-08-21") == []


def test_query_failed_builds(tmp_path):
    """Test gh run list JSON keeps only in-window failure-conclusion runs."""
    raw = json.dumps(
        [
            {
                "name": "ci-fail",
                "conclusion": "failure",
                "createdAt": "2026-08-15T10:00:00Z",
                "url": "https://github.com/bborbe/a/actions/runs/1",
            },
            {
                "name": "ci-old",
                "conclusion": "failure",
                "createdAt": "2026-08-01T10:00:00Z",
                "url": "https://github.com/bborbe/a/actions/runs/2",
            },
            {
                "name": "ci-ok",
                "conclusion": "success",
                "createdAt": "2026-08-15T10:00:00Z",
                "url": "https://github.com/bborbe/a/actions/runs/3",
            },
        ]
    )
    with patch("updater.digest._run_query", return_value=raw):
        builds = query_failed_builds("bborbe/a", "2026-08-14", "2026-08-21", tmp_path)
    assert len(builds) == 1
    assert builds[0].repo == "bborbe/a"
    assert builds[0].name == "ci-fail"
    assert builds[0].url == "https://github.com/bborbe/a/actions/runs/1"


def test_query_failed_builds_malformed_json(tmp_path):
    """Test malformed gh run list JSON raises a DigestQueryError naming builds."""
    with patch("updater.digest._run_query", return_value="not json"):
        with pytest.raises(DigestQueryError) as exc_info:
            query_failed_builds("bborbe/a", "2026-08-14", "2026-08-21", tmp_path)
    assert "builds for" in str(exc_info.value)


def test_render_full_digest(tmp_path):
    """Test a full render contains all sections and no Query errors section."""
    since, until = "2026-08-14", "2026-08-21"
    pr = _make_pr(
        number=42,
        state="MERGED",
        created_at="2026-08-15T10:00:00Z",
        merged_at="2026-08-16T10:00:00Z",
    )
    build = FailedBuild(
        repo="bborbe/b",
        name="ci",
        created_at="2026-08-15T10:00:00Z",
        url="https://github.com/bborbe/b/actions/runs/9",
    )
    advisory = ParkedAdvisory(
        repo="bborbe/b", vuln_id="GO-2026-1", package="golang.org/x/foo", reason="no upstream fix"
    )
    task = HumanReviewTask(path=Path("/tasks/t.md"), title="Fix vault task")
    abort = ChainAbortInfo(
        log_file=Path(".update-logs/2026-08-15-000000.log"),
        line="✗ Chain aborted at step manifest-verify: boom",
    )

    def _tags(repo, *args, **kwargs):
        return {"bborbe/a": ["v1.25.3", "v1.25.2"], "bborbe/b": ["v2.0.0"]}[repo]

    def _prs(repo, *a, **kw):
        return {"bborbe/a": [pr], "bborbe/b": []}[repo]

    def _builds(repo, *a, **kw):
        return {"bborbe/a": [], "bborbe/b": [build]}[repo]

    with (
        patch("updater.digest.query_tags", side_effect=_tags),
        patch("updater.digest.query_pull_requests", side_effect=_prs),
        patch("updater.digest.query_failed_builds", side_effect=_builds),
        patch("updater.digest.query_parked_advisories", return_value=[advisory]),
        patch("updater.digest.query_human_review_tasks", return_value=[task]),
        patch("updater.digest.query_chain_aborts", return_value=[abort]),
    ):
        text = Digest(
            since=since, until=until, repos=["bborbe/a", "bborbe/b"], workdir=tmp_path
        ).render()

    assert "## Go versions bumped" in text
    assert "## Pull requests" in text
    assert "## Releases cut" in text
    assert "## Exceptions" in text
    assert "Summary: 1/2 repos updated this week" in text
    assert "a: v1.25.2 -> v1.25.3" in text
    assert "#42" in text and "Bump Go" in text
    assert "bborbe/b: GO-2026-1 in golang.org/x/foo — no upstream fix" in text
    assert "bborbe/b: ci (https://github.com/bborbe/b/actions/runs/9)" in text
    assert "2026-08-15-000000.log" in text
    assert "/tasks/t.md" in text and "Fix vault task" in text
    assert "## Query errors" not in text


def test_render_no_updates_this_week(tmp_path):
    """Test a week with no in-window PR activity renders the negative signal + exceptions."""
    since, until = "2026-08-14", "2026-08-21"
    advisory = ParkedAdvisory(
        repo="bborbe/b", vuln_id="GO-2026-1", package="golang.org/x/foo", reason="no upstream fix"
    )
    with (
        patch("updater.digest.query_tags", return_value=["v1.25.2"]),
        patch("updater.digest.query_pull_requests", return_value=[]),
        patch("updater.digest.query_failed_builds", return_value=[]),
        patch("updater.digest.query_parked_advisories", return_value=[advisory]),
        patch("updater.digest.query_human_review_tasks", return_value=[]),
        patch("updater.digest.query_chain_aborts", return_value=[]),
    ):
        text = Digest(
            since=since, until=until, repos=["bborbe/a", "bborbe/b"], workdir=tmp_path
        ).render()

    assert "Summary: 0/2 repos updated this week" in text
    assert text.count("no updates this week") == 2
    assert "no releases this week" in text
    assert "## Exceptions" in text
    assert "bborbe/b: GO-2026-1 in golang.org/x/foo — no upstream fix" in text
    assert "## Query errors" not in text


def test_render_source_error_degrades(tmp_path):
    """Test a failing tags query records the error while the PR section still renders."""
    since, until = "2026-08-14", "2026-08-21"
    pr = _make_pr(number=7, state="OPEN", created_at="2026-08-15T10:00:00Z")

    def _tags(repo, *args, **kwargs):
        raise DigestQueryError(f"tags for {repo}", "fatal: repository not found")

    def _prs(repo, *a, **kw):
        return [pr] if repo == "bborbe/a" else []

    with (
        patch("updater.digest.query_tags", side_effect=_tags),
        patch("updater.digest.query_pull_requests", side_effect=_prs),
        patch("updater.digest.query_failed_builds", return_value=[]),
        patch("updater.digest.query_parked_advisories", return_value=[]),
        patch("updater.digest.query_human_review_tasks", return_value=[]),
        patch("updater.digest.query_chain_aborts", return_value=[]),
    ):
        text = Digest(since=since, until=until, repos=["bborbe/a"], workdir=tmp_path).render()

    assert "## Query errors" in text
    assert "tags for bborbe/a" in text
    assert "## Pull requests" in text
    assert "#7" in text


def test_render_exception_source_failure(tmp_path):
    """Test a failing park-list source renders a named failure, not a silent empty section."""
    since, until = "2026-08-14", "2026-08-21"
    with (
        patch("updater.digest.query_tags", return_value=["v1.25.2"]),
        patch("updater.digest.query_pull_requests", return_value=[]),
        patch("updater.digest.query_failed_builds", return_value=[]),
        patch(
            "updater.digest.query_parked_advisories",
            side_effect=DigestQueryError("park list", "park-list dir not found: /none"),
        ),
        patch("updater.digest.query_human_review_tasks", return_value=[]),
        patch("updater.digest.query_chain_aborts", return_value=[]),
    ):
        text = Digest(since=since, until=until, repos=["bborbe/a"], workdir=tmp_path).render()

    assert "park list failed: park-list dir not found: /none" in text
    assert "## Query errors" in text


def test_run_dry_run_prints_no_send(tmp_path):
    """Test run() prints the full digest text and returns 0 (no delivery)."""
    since, until = "2026-08-14", "2026-08-21"
    messages, log_side_effect = _capture_messages()
    with (
        patch("updater.digest.query_tags", return_value=["v1.25.2"]),
        patch("updater.digest.query_pull_requests", return_value=[]),
        patch("updater.digest.query_failed_builds", return_value=[]),
        patch("updater.digest.query_parked_advisories", return_value=[]),
        patch("updater.digest.query_human_review_tasks", return_value=[]),
        patch("updater.digest.query_chain_aborts", return_value=[]),
        patch("updater.digest.log_message", side_effect=log_side_effect),
    ):
        rc = Digest(
            since=since,
            until=until,
            repos=["bborbe/a"],
            workdir=tmp_path,
            dry_run=True,
        ).run()

    assert rc == 0
    assert any("Summary: 0/1 repos updated this week" in m for m in messages)


def test_run_invalid_date(tmp_path):
    """Test an invalid date range returns 1 and names the range."""
    messages, log_side_effect = _capture_messages()
    with patch("updater.digest.log_message", side_effect=log_side_effect):
        rc = Digest(
            since="not-a-date", until="2026-08-21", repos=["bborbe/a"], workdir=tmp_path
        ).run()

    assert rc == 1
    assert any("Invalid date range" in m and "not-a-date" in m for m in messages)


def test_run_empty_fleet(tmp_path):
    """Test an empty fleet returns 1 and mentions DIGEST_FLEET_REPOS."""
    messages, log_side_effect = _capture_messages()
    with patch("updater.digest.log_message", side_effect=log_side_effect):
        rc = Digest(since="2026-08-14", until="2026-08-21", repos=[], workdir=tmp_path).run()

    assert rc == 1
    assert any("DIGEST_FLEET_REPOS" in m for m in messages)


def test_query_pull_requests_command_boundary(tmp_path):
    """Test the PR query uses the exact single-quoted head:updater gh invocation."""
    raw = json.dumps(
        [
            {
                "number": 1,
                "title": "Bump",
                "state": "MERGED",
                "createdAt": "2026-08-15T10:00:00Z",
                "mergedAt": "2026-08-16T10:00:00Z",
                "closedAt": None,
                "url": "https://github.com/bborbe/a/pull/1",
            },
            {
                "number": 2,
                "title": "Old",
                "state": "MERGED",
                "createdAt": "2026-08-01T10:00:00Z",
                "mergedAt": "2026-08-02T10:00:00Z",
                "closedAt": None,
                "url": "https://github.com/bborbe/a/pull/2",
            },
        ]
    )
    with patch("updater.digest._run_query", return_value=raw) as mock_run:
        prs = query_pull_requests("bborbe/a", "2026-08-14", "2026-08-21", tmp_path)

    cmd = mock_run.call_args.args[0]
    assert cmd == (
        "gh pr list --repo bborbe/a --search 'head:updater' --state all --limit 100 "
        "--json number,title,state,createdAt,mergedAt,closedAt,url"
    )
    assert len(prs) == 1
    assert prs[0].number == 1


def test_query_tags_command_boundary(tmp_path):
    """Test the tags query uses the exact git ls-remote invocation."""
    raw = "abc123\trefs/tags/v1.25.2\ndef456\trefs/tags/v1.25.3\n"
    with patch("updater.digest._run_query", return_value=raw) as mock_run:
        tags = query_tags("bborbe/a", tmp_path)

    cmd = mock_run.call_args.args[0]
    assert cmd == "git ls-remote --tags https://github.com/bborbe/a.git"
    assert tags == ["v1.25.2", "v1.25.3"]


def test_render_pull_request_source_failure(tmp_path):
    """Test a failing PR query degrades: repo not updated, error recorded, render continues."""
    since, until = "2026-08-14", "2026-08-21"

    def _prs(repo, *a, **kw):
        raise DigestQueryError(f"PRs for {repo}", "gh: not authenticated")

    with (
        patch("updater.digest.query_tags", return_value=["v1.25.3", "v1.25.2"]),
        patch("updater.digest.query_pull_requests", side_effect=_prs),
        patch("updater.digest.query_failed_builds", return_value=[]),
        patch("updater.digest.query_parked_advisories", return_value=[]),
        patch("updater.digest.query_human_review_tasks", return_value=[]),
        patch("updater.digest.query_chain_aborts", return_value=[]),
    ):
        text = Digest(since=since, until=until, repos=["bborbe/a"], workdir=tmp_path).render()

    assert "## Query errors" in text
    assert "PRs for bborbe/a" in text
    assert "Summary: 0/1 repos updated this week" in text
    assert "no updates this week" in text


def test_render_single_tag_current_only(tmp_path):
    """Test an updated repo with a single version tag renders the tag without an arrow."""
    since, until = "2026-08-14", "2026-08-21"
    pr = _make_pr(
        number=1,
        state="MERGED",
        created_at="2026-08-15T10:00:00Z",
        merged_at="2026-08-16T10:00:00Z",
    )
    with (
        patch("updater.digest.query_tags", return_value=["v1.0.0"]),
        patch("updater.digest.query_pull_requests", return_value=[pr]),
        patch("updater.digest.query_failed_builds", return_value=[]),
        patch("updater.digest.query_parked_advisories", return_value=[]),
        patch("updater.digest.query_human_review_tasks", return_value=[]),
        patch("updater.digest.query_chain_aborts", return_value=[]),
    ):
        text = Digest(since=since, until=until, repos=["bborbe/a"], workdir=tmp_path).render()

    assert "  - bborbe/a: v1.0.0" in text
    assert "->" not in text


def test_render_human_review_source_failure(tmp_path):
    """Test a failing human_review query renders a named failure in its section."""
    since, until = "2026-08-14", "2026-08-21"
    with (
        patch("updater.digest.query_tags", return_value=["v1.25.2"]),
        patch("updater.digest.query_pull_requests", return_value=[]),
        patch("updater.digest.query_failed_builds", return_value=[]),
        patch("updater.digest.query_parked_advisories", return_value=[]),
        patch(
            "updater.digest.query_human_review_tasks",
            side_effect=DigestQueryError("human_review", "task dir not found: /none"),
        ),
        patch("updater.digest.query_chain_aborts", return_value=[]),
    ):
        text = Digest(since=since, until=until, repos=["bborbe/a"], workdir=tmp_path).render()

    assert "human_review failed: task dir not found: /none" in text
    assert "## Query errors" in text
