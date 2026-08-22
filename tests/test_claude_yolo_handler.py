"""Tests for the claude-yolo infra-tier handler."""

import subprocess
from unittest.mock import patch

from updater.claude_yolo_handler import ClaudeYoloHandler


def _commit_dockerfile(repo_path, version: str) -> None:
    """Write and commit a Dockerfile with the given GO_VERSION."""
    (repo_path / "Dockerfile").write_text(f"ARG GO_VERSION={version}\n")
    subprocess.run(["git", "add", "."], cwd=repo_path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=repo_path, check=True, capture_output=True)


def test_run_dry_run_bumps_dockerfile(tmp_git_repo):
    """Test dry-run bumps the Dockerfile and leaves only it changed."""
    _commit_dockerfile(tmp_git_repo, "1.27.0")

    with (
        patch("updater.infra_tier.git_checkout_new_branch") as mock_checkout,
        patch("updater.infra_tier.git_commit") as mock_commit,
        patch("updater.infra_tier.git_push") as mock_push,
        patch("updater.infra_tier.create_pull_request") as mock_pr,
    ):
        rc = ClaudeYoloHandler().run(tmp_git_repo, dry_run=True, go_version="1.28.0")

    assert rc == 0
    assert "1.28.0" in (tmp_git_repo / "Dockerfile").read_text()
    result = subprocess.run(
        ["git", "diff", "--name-only"], cwd=tmp_git_repo, capture_output=True, text=True
    )
    assert result.stdout.strip().split() == ["Dockerfile"]
    mock_checkout.assert_not_called()
    mock_commit.assert_not_called()
    mock_push.assert_not_called()
    mock_pr.assert_not_called()


def test_run_dry_run_up_to_date(tmp_git_repo):
    """Test dry-run against an already-current target is a no-op."""
    _commit_dockerfile(tmp_git_repo, "1.28.0")

    rc = ClaudeYoloHandler().run(tmp_git_repo, dry_run=True, go_version="1.28.0")

    assert rc == 0
    result = subprocess.run(
        ["git", "diff", "--name-only"], cwd=tmp_git_repo, capture_output=True, text=True
    )
    assert result.stdout.strip() == ""


def test_run_invalid_go_version(tmp_git_repo):
    """Test an invalid Go version is rejected and the file is untouched."""
    _commit_dockerfile(tmp_git_repo, "1.27.0")

    rc = ClaudeYoloHandler().run(tmp_git_repo, dry_run=True, go_version="1.28")

    assert rc == 1
    assert "1.27.0" in (tmp_git_repo / "Dockerfile").read_text()


def test_run_real_opens_pr(tmp_git_repo):
    """Test a real run opens a PR with the expected branch and title."""
    _commit_dockerfile(tmp_git_repo, "1.27.0")

    with (
        patch("updater.infra_tier.find_existing_pull_request", return_value=None),
        patch("updater.infra_tier.git_checkout_new_branch"),
        patch("updater.infra_tier.add_to_unreleased"),
        patch("updater.infra_tier.git_commit"),
        patch("updater.infra_tier.git_push"),
        patch(
            "updater.infra_tier.create_pull_request",
            return_value="https://github.com/bborbe/claude-yolo/pull/7",
        ) as mock_pr,
    ):
        rc = ClaudeYoloHandler().run(tmp_git_repo, dry_run=False, go_version="1.28.0")

    assert rc == 0
    mock_pr.assert_called_once()
    args, _ = mock_pr.call_args
    assert args[1] == "bborbe/claude-yolo"
    assert args[2] == "updater/claude-yolo-1.28.0"
    assert args[3] == "chore: bump Go version to 1.28.0 in Dockerfile"


def test_run_real_already_current(tmp_git_repo):
    """Test a real run against an already-current target opens no PR."""
    _commit_dockerfile(tmp_git_repo, "1.28.0")

    with patch("updater.infra_tier.create_pull_request") as mock_pr:
        rc = ClaudeYoloHandler().run(tmp_git_repo, dry_run=False, go_version="1.28.0")

    assert rc == 0
    mock_pr.assert_not_called()


def test_run_real_existing_pr(tmp_git_repo):
    """Test a real run with an existing updater PR opens no new PR and patches nothing."""
    _commit_dockerfile(tmp_git_repo, "1.27.0")

    with (
        patch(
            "updater.infra_tier.find_existing_pull_request",
            return_value="https://github.com/bborbe/claude-yolo/pull/5",
        ),
        patch("updater.infra_tier.git_checkout_new_branch") as mock_checkout,
        patch("updater.infra_tier.git_commit") as mock_commit,
        patch("updater.infra_tier.git_push") as mock_push,
        patch("updater.infra_tier.create_pull_request") as mock_pr,
    ):
        rc = ClaudeYoloHandler().run(tmp_git_repo, dry_run=False, go_version="1.28.0")

    assert rc == 0
    assert "1.27.0" in (tmp_git_repo / "Dockerfile").read_text()
    mock_checkout.assert_not_called()
    mock_commit.assert_not_called()
    mock_push.assert_not_called()
    mock_pr.assert_not_called()


def test_run_pattern_not_found(tmp_git_repo, capsys):
    """Test a Dockerfile whose constant does not match the pattern fails loudly."""
    (tmp_git_repo / "Dockerfile").write_text("ARG GO_VERSION = 1.27.0\n")
    subprocess.run(["git", "add", "."], cwd=tmp_git_repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-qm", "init"], cwd=tmp_git_repo, check=True, capture_output=True
    )

    rc = ClaudeYoloHandler().run(tmp_git_repo, dry_run=True, go_version="1.28.0")

    assert rc == 1
    captured = capsys.readouterr().out
    assert "Dockerfile" in captured
    assert "pattern not found" in captured
    assert "ARG GO_VERSION" in captured


def test_run_dirty_checkout_aborts(tmp_git_repo):
    """Test a dirty checkout aborts before touching the Dockerfile."""
    _commit_dockerfile(tmp_git_repo, "1.27.0")
    (tmp_git_repo / "uncommitted.txt").write_text("dirty\n")

    rc = ClaudeYoloHandler().run(tmp_git_repo, dry_run=True, go_version="1.28.0")

    assert rc == 1
    assert "1.27.0" in (tmp_git_repo / "Dockerfile").read_text()
