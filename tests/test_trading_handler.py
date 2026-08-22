"""Tests for the trading infra-tier handler."""

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from updater.log_manager import run_command as real_run
from updater.trading_handler import TRADING_PATTERN, TradingHandler


def _commit_makefile(repo_path, version: str) -> None:
    """Write and commit Makefile.folder with the given go version."""
    (repo_path / "Makefile.folder").write_text(f"go {version}\n")
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


def test_run_dry_run_bumps_makefile_folder(tmp_git_repo):
    """Test dry-run bumps Makefile.folder and leaves only it changed (no ensurecommit)."""
    _commit_makefile(tmp_git_repo, "1.27.0")

    commands = []

    def recording_run(cmd, cwd=None, capture_output=False, quiet=False, log_func=None):
        commands.append(cmd)
        return real_run(cmd, cwd=cwd, capture_output=capture_output, quiet=quiet, log_func=log_func)

    with patch("updater.infra_tier.run_command", side_effect=recording_run):
        rc = TradingHandler().run(tmp_git_repo, dry_run=True, go_version="1.28.0")

    assert rc == 0
    assert (tmp_git_repo / "Makefile.folder").read_text() == "go 1.28.0\n"
    result = subprocess.run(
        ["git", "diff", "--name-only"], cwd=tmp_git_repo, capture_output=True, text=True
    )
    assert result.stdout.strip().split() == ["Makefile.folder"]
    assert not any("make ensurecommit" in cmd for cmd in commands)


def test_run_dry_run_up_to_date(tmp_git_repo):
    """Test dry-run against an already-current target is a no-op."""
    _commit_makefile(tmp_git_repo, "1.28.0")

    rc = TradingHandler().run(tmp_git_repo, dry_run=True, go_version="1.28.0")

    assert rc == 0
    result = subprocess.run(
        ["git", "diff", "--name-only"], cwd=tmp_git_repo, capture_output=True, text=True
    )
    assert result.stdout.strip() == ""


def test_run_invalid_go_version(tmp_git_repo):
    """Test an invalid Go version is rejected and the file is untouched."""
    _commit_makefile(tmp_git_repo, "1.27.0")

    rc = TradingHandler().run(tmp_git_repo, dry_run=True, go_version="1.28")

    assert rc == 1
    assert (tmp_git_repo / "Makefile.folder").read_text() == "go 1.27.0\n"


def test_run_real_opens_pr(tmp_git_repo):
    """Test a real run creates the worktree, runs ensurecommit, and opens a PR."""
    _commit_makefile(tmp_git_repo, "1.27.0")

    with (
        patch("updater.trading_handler.run_command") as mock_run,
        patch("updater.trading_handler.find_existing_pull_request", return_value=None),
        patch("updater.trading_handler.patch_file"),
        patch("updater.trading_handler.git_commit"),
        patch("updater.trading_handler.git_push"),
        patch(
            "updater.trading_handler.create_pull_request",
            return_value="https://github.com/bborbe/trading/pull/9",
        ) as mock_pr,
    ):
        rc = TradingHandler().run(tmp_git_repo, dry_run=False, go_version="1.28.0")

    assert rc == 0

    worktree_add = [c for c in mock_run.call_args_list if c.args[0].startswith("git worktree add")]
    assert len(worktree_add) == 1
    assert "updater/trading-go-1.28.0" in worktree_add[0].args[0]
    assert "master" in worktree_add[0].args[0]
    worktree_path = Path(worktree_add[0].args[0].split()[-2])

    ensurecommit = [c for c in mock_run.call_args_list if c.args[0] == "make ensurecommit"]
    assert len(ensurecommit) == 1
    assert ensurecommit[0].kwargs["cwd"] == worktree_path

    remove = [
        c for c in mock_run.call_args_list if c.args[0].startswith("git worktree remove --force")
    ]
    assert len(remove) == 1
    assert worktree_path.name in remove[0].args[0]

    mock_pr.assert_called_once()
    args, _ = mock_pr.call_args
    assert args[1] == "bborbe/trading"
    assert args[2] == "updater/trading-go-1.28.0"
    assert args[3] == "chore: bump Go version to 1.28.0"
    assert (
        args[4]
        == "Bump the Go version constant in Makefile.folder to 1.28.0 and run make ensurecommit."
    )


def test_run_real_already_current(tmp_git_repo):
    """Test a real run against an already-current target creates no worktree or PR."""
    _commit_makefile(tmp_git_repo, "1.28.0")

    with (
        patch("updater.trading_handler.run_command") as mock_run,
        patch("updater.trading_handler.create_pull_request") as mock_pr,
    ):
        rc = TradingHandler().run(tmp_git_repo, dry_run=False, go_version="1.28.0")

    assert rc == 0
    mock_pr.assert_not_called()
    for call in mock_run.call_args_list:
        cmd = call.args[0]
        assert "worktree" not in cmd
        assert "gh" not in cmd


def test_run_real_existing_pr(tmp_git_repo):
    """Test a real run with an existing updater PR opens no new PR and patches nothing."""
    _commit_makefile(tmp_git_repo, "1.27.0")

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
        rc = TradingHandler().run(tmp_git_repo, dry_run=False, go_version="1.28.0")

    assert rc == 0
    assert (tmp_git_repo / "Makefile.folder").read_text() == "go 1.27.0\n"
    mock_commit.assert_not_called()
    mock_push.assert_not_called()
    mock_pr.assert_not_called()
    assert not any("worktree" in c.args[0] for c in mock_run.call_args_list)


def test_run_real_pattern_not_found(tmp_git_repo, capsys):
    """Test a Makefile.folder whose constant does not match the pattern fails loudly."""
    (tmp_git_repo / "Makefile.folder").write_text("GO_VERSION := 1.27.0\n")
    subprocess.run(["git", "add", "."], cwd=tmp_git_repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-qm", "init"], cwd=tmp_git_repo, check=True, capture_output=True
    )

    rc = TradingHandler().run(tmp_git_repo, dry_run=False, go_version="1.28.0")

    assert rc == 1
    captured = capsys.readouterr().out
    assert "Makefile.folder" in captured
    assert TRADING_PATTERN.pattern in captured


def test_run_real_dirty_checkout_aborts(tmp_git_repo):
    """Test a dirty checkout aborts before creating any worktree."""
    _commit_makefile(tmp_git_repo, "1.27.0")
    (tmp_git_repo / "uncommitted.txt").write_text("dirty\n")

    with patch("updater.trading_handler.run_command") as mock_run:
        rc = TradingHandler().run(tmp_git_repo, dry_run=False, go_version="1.28.0")

    assert rc == 1
    assert (tmp_git_repo / "Makefile.folder").read_text() == "go 1.27.0\n"
    assert not any("worktree" in c.args[0] for c in mock_run.call_args_list)


def test_run_real_ensurecommit_failure_removes_worktree(tmp_git_repo):
    """Test a failing make ensurecommit returns 1 and still removes the worktree."""
    _commit_makefile(tmp_git_repo, "1.27.0")

    def fake_run(cmd, cwd=None, capture_output=False, quiet=False, log_func=None):
        if cmd == "make ensurecommit":
            raise RuntimeError("make ensurecommit failed")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    with (
        patch("updater.trading_handler.run_command", side_effect=fake_run) as mock_run,
        patch("updater.trading_handler.find_existing_pull_request", return_value=None),
        patch("updater.trading_handler.patch_file"),
    ):
        rc = TradingHandler().run(tmp_git_repo, dry_run=False, go_version="1.28.0")

    assert rc == 1
    assert any(c.args[0].startswith("git worktree remove --force") for c in mock_run.call_args_list)


def test_run_real_worktree_flow_with_real_git(tmp_git_repo_master):
    """Test the real run against real git: worktree, patch, commit, and cleanup."""
    _commit_makefile(tmp_git_repo_master, "1.27.0")

    created_worktrees = []

    def fake_run(cmd, cwd=None, capture_output=False, quiet=False, log_func=None):
        if cmd.startswith("git worktree add"):
            created_worktrees.append(Path(cmd.split()[-2]))
        if cmd == "make ensurecommit":
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
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
        ["git", "show", "updater/trading-go-1.28.0:Makefile.folder"],
        cwd=tmp_git_repo_master,
        capture_output=True,
        text=True,
    )
    assert "go 1.28.0" in show.stdout
