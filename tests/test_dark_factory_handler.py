"""Tests for the dark-factory infra-tier handler."""

import subprocess
from unittest.mock import Mock, patch

import pytest

from updater.dark_factory_handler import DarkFactoryHandler, resolve_latest_claude_yolo_tag
from updater.infra_tier import InfraTargetError


def _commit_const(repo_path, version: str) -> None:
    """Write and commit pkg/const.go with the given claude-yolo tag."""
    (repo_path / "pkg").mkdir(exist_ok=True)
    (repo_path / "pkg" / "const.go").write_text(
        f'const DefaultContainerImage = "docker.io/bborbe/claude-yolo:{version}"\n'
    )
    subprocess.run(["git", "add", "."], cwd=repo_path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=repo_path, check=True, capture_output=True)


def test_run_dry_run_with_tag_bumps_const(tmp_git_repo):
    """Test dry-run with an explicit tag bumps pkg/const.go and touches no PR machinery."""
    _commit_const(tmp_git_repo, "v0.15.1")

    with (
        patch("updater.infra_tier.find_existing_pull_request") as mock_find,
        patch("updater.infra_tier.git_checkout_new_branch") as mock_checkout,
        patch("updater.infra_tier.git_commit") as mock_commit,
        patch("updater.infra_tier.git_push") as mock_push,
        patch("updater.infra_tier.create_pull_request") as mock_pr,
        patch("updater.infra_tier.add_to_unreleased") as mock_changelog,
    ):
        rc = DarkFactoryHandler().run(tmp_git_repo, dry_run=True, claude_yolo_tag="v0.16.0")

    assert rc == 0
    assert ":v0.16.0" in (tmp_git_repo / "pkg" / "const.go").read_text()
    result = subprocess.run(
        ["git", "diff", "--name-only"], cwd=tmp_git_repo, capture_output=True, text=True
    )
    assert result.stdout.strip().split() == ["pkg/const.go"]
    mock_find.assert_not_called()
    mock_checkout.assert_not_called()
    mock_commit.assert_not_called()
    mock_push.assert_not_called()
    mock_pr.assert_not_called()
    mock_changelog.assert_not_called()


def test_run_dry_run_up_to_date(tmp_git_repo):
    """Test dry-run against an already-current target produces no diff."""
    _commit_const(tmp_git_repo, "v0.16.0")

    rc = DarkFactoryHandler().run(tmp_git_repo, dry_run=True, claude_yolo_tag="v0.16.0")

    assert rc == 0
    result = subprocess.run(
        ["git", "diff", "--name-only"], cwd=tmp_git_repo, capture_output=True, text=True
    )
    assert result.stdout.strip() == ""


def test_run_invalid_tag(tmp_git_repo):
    """Test a tag without the v prefix is rejected and the file is untouched."""
    _commit_const(tmp_git_repo, "v0.15.1")

    rc = DarkFactoryHandler().run(tmp_git_repo, dry_run=True, claude_yolo_tag="0.16.0")

    assert rc == 1
    assert ":v0.15.1" in (tmp_git_repo / "pkg" / "const.go").read_text()


def test_resolve_latest_claude_yolo_tag_success(tmp_path):
    """Test resolve_latest_claude_yolo_tag returns the gh tag and uses the right command."""
    mock_result = Mock()
    mock_result.stdout = "v0.16.0\n"
    with patch("updater.dark_factory_handler.run_command", return_value=mock_result) as mock_run:
        tag = resolve_latest_claude_yolo_tag(tmp_path)

    assert tag == "v0.16.0"
    command = mock_run.call_args.args[0]
    assert "gh release view -R bborbe/claude-yolo" in command


def test_resolve_latest_claude_yolo_tag_invalid(tmp_path):
    """Test a non-vX.Y.Z tag from gh raises InfraTargetError."""
    mock_result = Mock()
    mock_result.stdout = "0.16.0\n"
    with patch("updater.dark_factory_handler.run_command", return_value=mock_result):
        with pytest.raises(InfraTargetError):
            resolve_latest_claude_yolo_tag(tmp_path)


def test_resolve_latest_claude_yolo_tag_gh_failure(tmp_path):
    """Test a gh failure propagates as RuntimeError."""
    with patch("updater.dark_factory_handler.run_command", side_effect=RuntimeError("gh failed")):
        with pytest.raises(RuntimeError):
            resolve_latest_claude_yolo_tag(tmp_path)


def test_run_resolves_tag_from_gh(tmp_git_repo):
    """Test run with no explicit tag resolves claude-yolo's latest release."""
    _commit_const(tmp_git_repo, "v0.15.1")

    with patch(
        "updater.dark_factory_handler.resolve_latest_claude_yolo_tag", return_value="v0.16.0"
    ):
        rc = DarkFactoryHandler().run(tmp_git_repo, dry_run=True, claude_yolo_tag=None)

    assert rc == 0
    assert ":v0.16.0" in (tmp_git_repo / "pkg" / "const.go").read_text()


def test_run_resolution_failure(tmp_git_repo):
    """Test a gh resolution failure returns 1 and touches nothing."""
    _commit_const(tmp_git_repo, "v0.15.1")

    with patch(
        "updater.dark_factory_handler.resolve_latest_claude_yolo_tag",
        side_effect=RuntimeError("gh: not authenticated"),
    ):
        rc = DarkFactoryHandler().run(tmp_git_repo, dry_run=True, claude_yolo_tag=None)

    assert rc == 1
    assert ":v0.15.1" in (tmp_git_repo / "pkg" / "const.go").read_text()


def test_run_real_opens_pr(tmp_git_repo):
    """Test a real run opens a PR with the expected branch and title."""
    _commit_const(tmp_git_repo, "v0.15.1")

    with (
        patch("updater.infra_tier.find_existing_pull_request", return_value=None),
        patch("updater.infra_tier.git_checkout_new_branch"),
        patch("updater.infra_tier.add_to_unreleased"),
        patch("updater.infra_tier.git_commit"),
        patch("updater.infra_tier.git_push"),
        patch(
            "updater.infra_tier.create_pull_request",
            return_value="https://github.com/bborbe/dark-factory/pull/8",
        ) as mock_pr,
    ):
        rc = DarkFactoryHandler().run(tmp_git_repo, dry_run=False, claude_yolo_tag="v0.16.0")

    assert rc == 0
    mock_pr.assert_called_once()
    args, _ = mock_pr.call_args
    assert args[1] == "bborbe/dark-factory"
    assert args[2] == "updater/dark-factory-v0.16.0"
    assert args[3] == "chore: bump DefaultContainerImage to claude-yolo:v0.16.0"


def test_run_real_already_current(tmp_git_repo):
    """Test a real run against an already-current target opens no PR."""
    _commit_const(tmp_git_repo, "v0.16.0")

    with patch("updater.infra_tier.create_pull_request") as mock_pr:
        rc = DarkFactoryHandler().run(tmp_git_repo, dry_run=False, claude_yolo_tag="v0.16.0")

    assert rc == 0
    mock_pr.assert_not_called()


def test_run_real_existing_pr(tmp_git_repo):
    """Test a real run with an existing updater PR opens no new PR and patches nothing."""
    _commit_const(tmp_git_repo, "v0.15.1")

    with (
        patch(
            "updater.infra_tier.find_existing_pull_request",
            return_value="https://github.com/bborbe/dark-factory/pull/5",
        ),
        patch("updater.infra_tier.git_checkout_new_branch") as mock_checkout,
        patch("updater.infra_tier.git_commit") as mock_commit,
        patch("updater.infra_tier.git_push") as mock_push,
        patch("updater.infra_tier.create_pull_request") as mock_pr,
    ):
        rc = DarkFactoryHandler().run(tmp_git_repo, dry_run=False, claude_yolo_tag="v0.16.0")

    assert rc == 0
    assert ":v0.15.1" in (tmp_git_repo / "pkg" / "const.go").read_text()
    mock_checkout.assert_not_called()
    mock_commit.assert_not_called()
    mock_push.assert_not_called()
    mock_pr.assert_not_called()


def test_run_pattern_not_found(tmp_git_repo, capsys):
    """Test a const.go line that does not match the pattern fails loudly."""
    (tmp_git_repo / "pkg").mkdir()
    (tmp_git_repo / "pkg" / "const.go").write_text(
        'const DefaultContainerImage = "docker.io/bborbe/claude-yolo:v0.15.1-extra"\n'
    )
    subprocess.run(["git", "add", "."], cwd=tmp_git_repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-qm", "init"], cwd=tmp_git_repo, check=True, capture_output=True
    )

    rc = DarkFactoryHandler().run(tmp_git_repo, dry_run=True, claude_yolo_tag="v0.16.0")

    assert rc == 1
    captured = capsys.readouterr().out
    assert "pkg/const.go" in captured
    assert "pattern not found" in captured
    assert "DefaultContainerImage" in captured


def test_run_dirty_checkout_aborts(tmp_git_repo):
    """Test a dirty checkout aborts before touching pkg/const.go."""
    _commit_const(tmp_git_repo, "v0.15.1")
    (tmp_git_repo / "uncommitted.txt").write_text("dirty\n")

    rc = DarkFactoryHandler().run(tmp_git_repo, dry_run=True, claude_yolo_tag="v0.16.0")

    assert rc == 1
    assert ":v0.15.1" in (tmp_git_repo / "pkg" / "const.go").read_text()
