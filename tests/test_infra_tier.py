"""Tests for the shared infra-tier patch-and-PR helper."""

import re
import subprocess
from unittest.mock import patch

import pytest

from updater.infra_tier import (
    InfraTargetError,
    patch_file,
    process_infra_target,
    read_current_value,
    require_clean_worktree,
    require_current_value,
    validate_claude_yolo_tag,
    validate_go_version,
)

GO_VERSION_PATTERN = re.compile(r"^ARG GO_VERSION=(\d+\.\d+\.\d+)$")


def _commit_file(repo_path, filename: str, content: str) -> None:
    """Write a file and commit it so the worktree is clean."""
    (repo_path / filename).write_text(content)
    subprocess.run(["git", "add", "."], cwd=repo_path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=repo_path, check=True, capture_output=True)


# --- validation boundary tests ---


@pytest.mark.parametrize("value", ["1.28.0", "1.0.0"])
def test_validate_go_version_accepts(value):
    """Test valid X.Y.Z Go versions are accepted."""
    assert validate_go_version(value) is True


@pytest.mark.parametrize(
    "value",
    ["1.28", "1.28.0-rc1", "go1.28.0", "v1.28.0", "1.28.0 ", "; rm -rf /", ""],
)
def test_validate_go_version_rejects(value):
    """Test malformed Go versions are rejected."""
    assert validate_go_version(value) is False


@pytest.mark.parametrize("value", ["v0.16.0", "v1.2.3"])
def test_validate_claude_yolo_tag_accepts(value):
    """Test valid vX.Y.Z release tags are accepted."""
    assert validate_claude_yolo_tag(value) is True


@pytest.mark.parametrize("value", ["0.16.0", "v0.16", "v0.16.0-rc1", "1.28.0", "v1.28.0 ", ""])
def test_validate_claude_yolo_tag_rejects(value):
    """Test malformed release tags are rejected."""
    assert validate_claude_yolo_tag(value) is False


def test_read_current_value_found(tmp_path):
    """Test read_current_value returns the captured value."""
    (tmp_path / "Dockerfile").write_text("ARG GO_VERSION=1.27.0\n")
    assert read_current_value(tmp_path, "Dockerfile", GO_VERSION_PATTERN) == "1.27.0"


def test_read_current_value_missing_file(tmp_path):
    """Test read_current_value returns None when the file is missing."""
    assert read_current_value(tmp_path, "Dockerfile", GO_VERSION_PATTERN) is None


def test_read_current_value_pattern_absent(tmp_path):
    """Test read_current_value returns None when the pattern does not match."""
    (tmp_path / "Dockerfile").write_text("ARG GO_VERSION = 1.27.0\n")
    assert read_current_value(tmp_path, "Dockerfile", GO_VERSION_PATTERN) is None


def test_require_current_value_raises_missing_file(tmp_path):
    """Test require_current_value raises naming the missing file."""
    with pytest.raises(InfraTargetError) as exc_info:
        require_current_value(tmp_path, "Dockerfile", GO_VERSION_PATTERN)
    assert "Dockerfile" in str(exc_info.value)


def test_require_current_value_raises_pattern_not_found(tmp_path):
    """Test require_current_value raises naming file and pattern when unmatched."""
    (tmp_path / "Dockerfile").write_text("ARG GO_VERSION = 1.27.0\n")
    with pytest.raises(InfraTargetError) as exc_info:
        require_current_value(tmp_path, "Dockerfile", GO_VERSION_PATTERN)
    message = str(exc_info.value)
    assert "Dockerfile" in message
    assert GO_VERSION_PATTERN.pattern in message


def test_patch_file_changes_value(tmp_path):
    """Test patch_file replaces the value and returns True."""
    dockerfile = tmp_path / "Dockerfile"
    dockerfile.write_text("ARG GO_VERSION=1.27.0\n")
    changed = patch_file(tmp_path, "Dockerfile", GO_VERSION_PATTERN, "1.28.0")
    assert changed is True
    assert dockerfile.read_text() == "ARG GO_VERSION=1.28.0\n"


def test_patch_file_no_op_when_current(tmp_path):
    """Test patch_file returns False and leaves content unchanged when current."""
    dockerfile = tmp_path / "Dockerfile"
    dockerfile.write_text("ARG GO_VERSION=1.28.0\n")
    changed = patch_file(tmp_path, "Dockerfile", GO_VERSION_PATTERN, "1.28.0")
    assert changed is False
    assert dockerfile.read_text() == "ARG GO_VERSION=1.28.0\n"


# --- worktree checks (real git subprocess) ---


def test_require_clean_worktree_clean(tmp_git_repo):
    """Test require_clean_worktree passes for a clean repo."""
    _commit_file(tmp_git_repo, "Dockerfile", "ARG GO_VERSION=1.27.0\n")
    require_clean_worktree(tmp_git_repo)  # no raise


def test_require_clean_worktree_dirty(tmp_git_repo):
    """Test require_clean_worktree raises for a dirty worktree."""
    _commit_file(tmp_git_repo, "Dockerfile", "ARG GO_VERSION=1.27.0\n")
    (tmp_git_repo / "uncommitted.txt").write_text("dirty\n")
    with pytest.raises(InfraTargetError):
        require_clean_worktree(tmp_git_repo)


def test_require_clean_worktree_not_repo(tmp_path):
    """Test require_clean_worktree raises for a non-git directory."""
    with pytest.raises(InfraTargetError):
        require_clean_worktree(tmp_path)


# --- process_infra_target flow ---


def test_process_infra_target_dry_run_patches_and_shows_diff(tmp_git_repo):
    """Test dry-run patches the file, shows the diff, and touches no PR machinery."""
    _commit_file(tmp_git_repo, "Dockerfile", "ARG GO_VERSION=1.27.0\n")

    with (
        patch("updater.infra_tier.git_checkout_new_branch") as mock_checkout,
        patch("updater.infra_tier.git_commit") as mock_commit,
        patch("updater.infra_tier.git_push") as mock_push,
        patch("updater.infra_tier.create_pull_request") as mock_pr,
        patch("updater.infra_tier.add_to_unreleased") as mock_changelog,
    ):
        rc = process_infra_target(
            tmp_git_repo,
            repo="bborbe/claude-yolo",
            target_file="Dockerfile",
            pattern=GO_VERSION_PATTERN,
            new_value="1.28.0",
            branch_name="updater/claude-yolo-1.28.0",
            title="chore: bump Go version to 1.28.0 in Dockerfile",
            body="Bump ARG GO_VERSION to 1.28.0.",
            changelog_bullet="chore: bump Go version to 1.28.0 in Dockerfile",
            dry_run=True,
        )

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
    mock_changelog.assert_not_called()


def test_process_infra_target_dry_run_up_to_date(tmp_git_repo):
    """Test dry-run against an already-current target produces no diff."""
    _commit_file(tmp_git_repo, "Dockerfile", "ARG GO_VERSION=1.28.0\n")

    with (
        patch("updater.infra_tier.git_checkout_new_branch") as mock_checkout,
        patch("updater.infra_tier.git_commit") as mock_commit,
        patch("updater.infra_tier.git_push") as mock_push,
        patch("updater.infra_tier.create_pull_request") as mock_pr,
    ):
        rc = process_infra_target(
            tmp_git_repo,
            repo="bborbe/claude-yolo",
            target_file="Dockerfile",
            pattern=GO_VERSION_PATTERN,
            new_value="1.28.0",
            branch_name="updater/claude-yolo-1.28.0",
            title="chore: bump Go version to 1.28.0 in Dockerfile",
            body="Bump ARG GO_VERSION to 1.28.0.",
            changelog_bullet="chore: bump Go version to 1.28.0 in Dockerfile",
            dry_run=True,
        )

    assert rc == 0
    result = subprocess.run(
        ["git", "diff", "--name-only"], cwd=tmp_git_repo, capture_output=True, text=True
    )
    assert result.stdout.strip() == ""
    mock_checkout.assert_not_called()
    mock_commit.assert_not_called()
    mock_push.assert_not_called()
    mock_pr.assert_not_called()


def test_process_infra_target_dry_run_dirty_aborts(tmp_git_repo):
    """Test a dirty worktree aborts before touching the target file."""
    _commit_file(tmp_git_repo, "Dockerfile", "ARG GO_VERSION=1.27.0\n")
    (tmp_git_repo / "uncommitted.txt").write_text("dirty\n")

    with (
        patch("updater.infra_tier.git_checkout_new_branch") as mock_checkout,
        patch("updater.infra_tier.git_commit") as mock_commit,
        patch("updater.infra_tier.git_push") as mock_push,
        patch("updater.infra_tier.create_pull_request") as mock_pr,
    ):
        rc = process_infra_target(
            tmp_git_repo,
            repo="bborbe/claude-yolo",
            target_file="Dockerfile",
            pattern=GO_VERSION_PATTERN,
            new_value="1.28.0",
            branch_name="updater/claude-yolo-1.28.0",
            title="chore: bump Go version to 1.28.0 in Dockerfile",
            body="Bump ARG GO_VERSION to 1.28.0.",
            changelog_bullet="chore: bump Go version to 1.28.0 in Dockerfile",
            dry_run=True,
        )

    assert rc == 1
    assert "1.27.0" in (tmp_git_repo / "Dockerfile").read_text()
    mock_checkout.assert_not_called()
    mock_commit.assert_not_called()
    mock_push.assert_not_called()
    mock_pr.assert_not_called()


def test_process_infra_target_real_opens_pr(tmp_git_repo):
    """Test a real run patches, adds the changelog bullet, and opens a PR."""
    _commit_file(tmp_git_repo, "Dockerfile", "ARG GO_VERSION=1.27.0\n")

    with (
        patch("updater.infra_tier.find_existing_pull_request", return_value=None),
        patch("updater.infra_tier.git_checkout_new_branch") as mock_checkout,
        patch("updater.infra_tier.add_to_unreleased") as mock_changelog,
        patch("updater.infra_tier.git_commit") as mock_commit,
        patch("updater.infra_tier.git_push") as mock_push,
        patch(
            "updater.infra_tier.create_pull_request",
            return_value="https://github.com/bborbe/claude-yolo/pull/7",
        ) as mock_pr,
    ):
        rc = process_infra_target(
            tmp_git_repo,
            repo="bborbe/claude-yolo",
            target_file="Dockerfile",
            pattern=GO_VERSION_PATTERN,
            new_value="1.28.0",
            branch_name="updater/claude-yolo-1.28.0",
            title="chore: bump Go version to 1.28.0 in Dockerfile",
            body="Bump ARG GO_VERSION to 1.28.0.",
            changelog_bullet="chore: bump Go version to 1.28.0 in Dockerfile",
            dry_run=False,
        )

    assert rc == 0
    assert "1.28.0" in (tmp_git_repo / "Dockerfile").read_text()
    mock_changelog.assert_called_once()
    mock_checkout.assert_called_once()
    mock_commit.assert_called_once()
    mock_push.assert_called_once()
    mock_pr.assert_called_once()
    args, _ = mock_pr.call_args
    assert args[1] == "bborbe/claude-yolo"
    assert args[2] == "updater/claude-yolo-1.28.0"
    assert args[3] == "chore: bump Go version to 1.28.0 in Dockerfile"
    assert args[4] == "Bump ARG GO_VERSION to 1.28.0."


def test_process_infra_target_real_existing_pr_skips(tmp_git_repo):
    """Test a real run with an existing updater PR opens nothing and patches nothing."""
    _commit_file(tmp_git_repo, "Dockerfile", "ARG GO_VERSION=1.27.0\n")

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
        rc = process_infra_target(
            tmp_git_repo,
            repo="bborbe/claude-yolo",
            target_file="Dockerfile",
            pattern=GO_VERSION_PATTERN,
            new_value="1.28.0",
            branch_name="updater/claude-yolo-1.28.0",
            title="chore: bump Go version to 1.28.0 in Dockerfile",
            body="Bump ARG GO_VERSION to 1.28.0.",
            changelog_bullet="chore: bump Go version to 1.28.0 in Dockerfile",
            dry_run=False,
        )

    assert rc == 0
    assert "1.27.0" in (tmp_git_repo / "Dockerfile").read_text()
    mock_checkout.assert_not_called()
    mock_commit.assert_not_called()
    mock_push.assert_not_called()
    mock_pr.assert_not_called()


def test_process_infra_target_real_up_to_date_skips(tmp_git_repo):
    """Test a real run against an already-current target makes no network calls."""
    _commit_file(tmp_git_repo, "Dockerfile", "ARG GO_VERSION=1.28.0\n")

    with patch("updater.infra_tier.find_existing_pull_request") as mock_find:
        rc = process_infra_target(
            tmp_git_repo,
            repo="bborbe/claude-yolo",
            target_file="Dockerfile",
            pattern=GO_VERSION_PATTERN,
            new_value="1.28.0",
            branch_name="updater/claude-yolo-1.28.0",
            title="chore: bump Go version to 1.28.0 in Dockerfile",
            body="Bump ARG GO_VERSION to 1.28.0.",
            changelog_bullet="chore: bump Go version to 1.28.0 in Dockerfile",
            dry_run=False,
        )

    assert rc == 0
    mock_find.assert_not_called()


def test_process_infra_target_real_pr_failure(tmp_git_repo):
    """Test a failing PR creation returns 1 (no partial PR)."""
    _commit_file(tmp_git_repo, "Dockerfile", "ARG GO_VERSION=1.27.0\n")

    with (
        patch("updater.infra_tier.find_existing_pull_request", return_value=None),
        patch("updater.infra_tier.git_checkout_new_branch"),
        patch("updater.infra_tier.add_to_unreleased"),
        patch("updater.infra_tier.git_commit"),
        patch("updater.infra_tier.git_push"),
        patch("updater.infra_tier.create_pull_request", side_effect=RuntimeError("gh failed")),
    ):
        rc = process_infra_target(
            tmp_git_repo,
            repo="bborbe/claude-yolo",
            target_file="Dockerfile",
            pattern=GO_VERSION_PATTERN,
            new_value="1.28.0",
            branch_name="updater/claude-yolo-1.28.0",
            title="chore: bump Go version to 1.28.0 in Dockerfile",
            body="Bump ARG GO_VERSION to 1.28.0.",
            changelog_bullet="chore: bump Go version to 1.28.0 in Dockerfile",
            dry_run=False,
        )

    assert rc == 1
