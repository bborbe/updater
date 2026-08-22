"""Tests for the trading infra-tier handler (replicates update-go-version.sh)."""

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from updater.log_manager import run_command as real_run
from updater.trading_handler import TradingHandler, apply_version_updates


def _write_versioned_repo(repo_path: Path, version: str) -> None:
    """Write go.mod + Dockerfile + workflow pinned to ``version`` and commit."""
    subprocess.run(["git", "init", "-b", "master"], cwd=repo_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=repo_path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=repo_path,
        check=True,
        capture_output=True,
    )
    (repo_path / "go.mod").write_text(f"module example.com/root\n\ngo {version}\n")
    (repo_path / "Dockerfile").write_text(f"FROM golang:{version} AS build\nRUN go build\n")
    wf = repo_path / ".github" / "workflows"
    wf.mkdir(parents=True)
    (wf / "ci.yml").write_text(
        f"jobs:\n  test:\n    steps:\n      - uses: actions/setup-go@v5\n        with:\n          go-version: '{version}'\n"
    )
    submodule = repo_path / "sub" / "module"
    submodule.mkdir(parents=True)
    (submodule / "go.mod").write_text(
        f"module example.com/sub\n\ngo {version}\n\ntoolchain go{version}\n"
    )
    vendored = repo_path / "vendor" / "dep"
    vendored.mkdir(parents=True)
    (vendored / "go.mod").write_text("module example.com/vendored\n\ngo 1.20.0\n")
    subprocess.run(["git", "add", "."], cwd=repo_path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=repo_path, check=True, capture_output=True)


@pytest.fixture
def tmp_git_repo_master(tmp_path: Path) -> Path:
    """Create a temp git repository whose default branch is master.

    The worktree flow creates its feature worktree from ``master``, so the
    fixture must pin the default branch name (bare ``git init`` may default to
    ``main`` depending on the host's init.defaultBranch).

    Args:
        tmp_path: Pytest temporary directory fixture

    Returns:
        Path to temporary git repository
    """
    repo_path = tmp_path / "test_repo"
    repo_path.mkdir()
    subprocess.run(
        ["git", "init", "-b", "master"],
        cwd=repo_path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=repo_path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=repo_path,
        check=True,
        capture_output=True,
    )
    return repo_path


def test_apply_version_updates_all_file_types(tmp_path):
    """Test the patch walk bumps go.mod, Dockerfile, and workflow, skipping vendor/."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _write_versioned_repo(repo, "1.27.0")

    changed = apply_version_updates(repo, "1.28.0")

    assert changed == 4
    assert (repo / "go.mod").read_text() == "module example.com/root\n\ngo 1.28.0\n"
    assert (repo / "Dockerfile").read_text() == "FROM golang:1.28.0 AS build\nRUN go build\n"
    assert "go-version: '1.28.0'" in (repo / ".github" / "workflows" / "ci.yml").read_text()
    nested = repo / "sub" / "module" / "go.mod"
    assert "go 1.28.0" in nested.read_text()
    assert "toolchain go1.28.0" in nested.read_text()
    # vendor/ is excluded
    assert "go 1.20.0" in (repo / "vendor" / "dep" / "go.mod").read_text()


def test_apply_version_updates_up_to_date(tmp_path):
    """Test the patch walk is a no-op when everything is already at the target."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _write_versioned_repo(repo, "1.28.0")

    changed = apply_version_updates(repo, "1.28.0")

    assert changed == 0


def test_run_dry_run_patches_and_shows_diff(tmp_git_repo_master):
    """Test dry-run applies the walk and leaves the changed files uncommitted."""
    _write_versioned_repo(tmp_git_repo_master, "1.27.0")

    rc = TradingHandler().run(tmp_git_repo_master, dry_run=True, go_version="1.28.0")

    assert rc == 0
    assert "go 1.28.0" in (tmp_git_repo_master / "go.mod").read_text()
    assert "FROM golang:1.28.0" in (tmp_git_repo_master / "Dockerfile").read_text()
    result = subprocess.run(
        ["git", "diff", "--name-only"],
        cwd=tmp_git_repo_master,
        capture_output=True,
        text=True,
    )
    changed = set(result.stdout.split())
    assert changed == {
        "go.mod",
        "Dockerfile",
        ".github/workflows/ci.yml",
        "sub/module/go.mod",
    }
    assert "vendor/dep/go.mod" not in changed


def test_run_dry_run_up_to_date(tmp_git_repo_master):
    """Test dry-run against an already-current target is a no-op."""
    _write_versioned_repo(tmp_git_repo_master, "1.28.0")

    rc = TradingHandler().run(tmp_git_repo_master, dry_run=True, go_version="1.28.0")

    assert rc == 0
    result = subprocess.run(
        ["git", "diff", "--name-only"],
        cwd=tmp_git_repo_master,
        capture_output=True,
        text=True,
    )
    assert result.stdout.strip() == ""


def test_run_invalid_go_version(tmp_git_repo_master):
    """Test an invalid Go version is rejected and the tree is untouched."""
    _write_versioned_repo(tmp_git_repo_master, "1.27.0")

    rc = TradingHandler().run(tmp_git_repo_master, dry_run=True, go_version="1.28")

    assert rc == 1
    result = subprocess.run(
        ["git", "diff", "--name-only"],
        cwd=tmp_git_repo_master,
        capture_output=True,
        text=True,
    )
    assert result.stdout.strip() == ""


def test_run_real_opens_pr(tmp_git_repo_master):
    """Test a real run creates the worktree, patches, commits, and opens a PR."""
    _write_versioned_repo(tmp_git_repo_master, "1.27.0")

    worktree_adds = []
    created_worktrees = []

    def fake_run(cmd, cwd=None, capture_output=False, quiet=False, log_func=None):
        if cmd.startswith("git worktree add"):
            worktree_adds.append(cmd)
            created_worktrees.append(Path(cmd.split()[-2]))
        return real_run(cmd, cwd=cwd, capture_output=capture_output, quiet=quiet, log_func=log_func)

    with (
        patch("updater.trading_handler.run_command", side_effect=fake_run),
        patch("updater.trading_handler.find_existing_pull_request", return_value=None),
        patch("updater.trading_handler.git_commit"),
        patch("updater.trading_handler.git_push"),
        patch(
            "updater.trading_handler.create_pull_request",
            return_value="https://github.com/bborbe/trading/pull/9",
        ) as mock_pr,
    ):
        rc = TradingHandler().run(tmp_git_repo_master, dry_run=False, go_version="1.28.0")

    assert rc == 0
    assert len(worktree_adds) == 1
    assert "updater/trading-go-1.28.0" in worktree_adds[0]
    assert "master" in worktree_adds[0]
    assert created_worktrees
    assert not created_worktrees[0].exists()

    mock_pr.assert_called_once()
    args, _ = mock_pr.call_args
    assert args[1] == "bborbe/trading"
    assert args[2] == "updater/trading-go-1.28.0"
    assert args[3] == "chore: bump Go version to 1.28.0"


def test_run_real_already_current(tmp_git_repo_master):
    """Test a real run against an already-current target creates no worktree or PR."""
    _write_versioned_repo(tmp_git_repo_master, "1.28.0")

    with (
        patch("updater.trading_handler.run_command") as mock_run,
        patch("updater.trading_handler.create_pull_request") as mock_pr,
    ):
        rc = TradingHandler().run(tmp_git_repo_master, dry_run=False, go_version="1.28.0")

    assert rc == 0
    mock_pr.assert_not_called()
    for call in mock_run.call_args_list:
        cmd = call.args[0]
        assert "worktree" not in cmd
        assert "gh" not in cmd


def test_run_real_existing_pr(tmp_git_repo_master):
    """Test a real run with an existing updater PR opens no new PR and patches nothing."""
    _write_versioned_repo(tmp_git_repo_master, "1.27.0")

    with (
        patch(
            "updater.trading_handler.find_existing_pull_request",
            return_value="https://github.com/bborbe/trading/pull/5",
        ),
        patch("updater.trading_handler.run_command") as mock_run,
        patch("updater.trading_handler.git_commit") as mock_commit,
        patch("updater.trading_handler.git_push") as mock_push,
        patch("updater.trading_handler.create_pull_request") as mock_pr,
    ):
        rc = TradingHandler().run(tmp_git_repo_master, dry_run=False, go_version="1.28.0")

    assert rc == 0
    assert "go 1.27.0" in (tmp_git_repo_master / "go.mod").read_text()
    mock_commit.assert_not_called()
    mock_push.assert_not_called()
    mock_pr.assert_not_called()
    assert not any("worktree" in c.args[0] for c in mock_run.call_args_list)


def test_run_real_dirty_checkout_aborts(tmp_git_repo_master):
    """Test a dirty checkout aborts before creating any worktree."""
    _write_versioned_repo(tmp_git_repo_master, "1.27.0")
    (tmp_git_repo_master / "uncommitted.txt").write_text("dirty\n")

    with patch("updater.trading_handler.run_command") as mock_run:
        rc = TradingHandler().run(tmp_git_repo_master, dry_run=False, go_version="1.28.0")

    assert rc == 1
    assert "go 1.27.0" in (tmp_git_repo_master / "go.mod").read_text()
    assert not any("worktree" in c.args[0] for c in mock_run.call_args_list)


def test_run_real_worktree_flow_with_real_git(tmp_git_repo_master):
    """Test the real run against real git: worktree, patch, commit, and cleanup."""
    _write_versioned_repo(tmp_git_repo_master, "1.27.0")

    created_worktrees = []

    def fake_run(cmd, cwd=None, capture_output=False, quiet=False, log_func=None):
        if cmd.startswith("git worktree add"):
            created_worktrees.append(Path(cmd.split()[-2]))
        return real_run(cmd, cwd=cwd, capture_output=capture_output, quiet=quiet, log_func=log_func)

    with (
        patch("updater.trading_handler.run_command", side_effect=fake_run),
        patch("updater.trading_handler.find_existing_pull_request", return_value=None),
        patch("updater.trading_handler.git_push"),
        patch(
            "updater.trading_handler.create_pull_request",
            return_value="https://github.com/bborbe/trading/pull/9",
        ),
    ):
        rc = TradingHandler().run(tmp_git_repo_master, dry_run=False, go_version="1.28.0")

    assert rc == 0
    assert created_worktrees
    worktree = created_worktrees[0]
    assert not worktree.exists()

    branch_list = subprocess.run(
        ["git", "branch", "--list", "updater/trading-go-1.28.0"],
        cwd=tmp_git_repo_master,
        capture_output=True,
        text=True,
    )
    assert "updater/trading-go-1.28.0" in branch_list.stdout

    show = subprocess.run(
        ["git", "show", "updater/trading-go-1.28.0:go.mod"],
        cwd=tmp_git_repo_master,
        capture_output=True,
        text=True,
    )
    assert "go 1.28.0" in show.stdout
