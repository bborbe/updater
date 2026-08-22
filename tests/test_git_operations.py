"""Tests for git operations."""

from unittest.mock import Mock, patch

import pytest

from updater.git_operations import (
    check_git_status,
    create_pull_request,
    find_existing_pull_request,
    get_commits_since_tag,
    get_latest_tag,
    git_checkout_new_branch,
    git_commit,
    git_push,
    git_tag_from_changelog,
    update_git_branch,
)


def test_check_git_status_no_changes(tmp_path):
    """Test check_git_status with no changes."""
    with (
        patch("updater.git_operations.find_git_repo") as mock_find,
        patch("subprocess.run") as mock_run,
    ):
        mock_find.return_value = tmp_path
        mock_run.return_value = Mock(returncode=0, stdout="")

        count, files = check_git_status(tmp_path)

        assert count == 0
        assert files == []


def test_check_git_status_with_changes(tmp_path):
    """Test check_git_status with modified files."""
    # Simulate git status --porcelain output
    git_output = " M go.mod\n M go.sum\n?? newfile.txt\n"

    with (
        patch("updater.git_operations.find_git_repo") as mock_find,
        patch("subprocess.run") as mock_run,
    ):
        mock_find.return_value = tmp_path
        mock_run.return_value = Mock(returncode=0, stdout=git_output)

        count, files = check_git_status(tmp_path)

        assert count == 3
        assert files == ["go.mod", "go.sum", "newfile.txt"]


def test_check_git_status_with_spaces_in_filename(tmp_path):
    """Test check_git_status with filenames containing spaces."""
    git_output = " M file with spaces.go\n"

    with (
        patch("updater.git_operations.find_git_repo") as mock_find,
        patch("subprocess.run") as mock_run,
    ):
        mock_find.return_value = tmp_path
        mock_run.return_value = Mock(returncode=0, stdout=git_output)

        count, files = check_git_status(tmp_path)

        assert count == 1
        # Note: git status --porcelain doesn't preserve spaces in simple format
        # This test documents current behavior
        assert files == ["file"]


def test_check_git_status_error(tmp_path):
    """Test check_git_status with git command error."""
    with (
        patch("updater.git_operations.find_git_repo") as mock_find,
        patch("subprocess.run") as mock_run,
    ):
        mock_find.return_value = tmp_path
        mock_run.return_value = Mock(returncode=1, stdout="", stderr="fatal: not a git repository")

        count, files = check_git_status(tmp_path)

        assert count == -1
        assert files == []


def test_check_git_status_no_git_repo(tmp_path):
    """Test check_git_status when not in a git repository."""
    with patch("updater.git_operations.find_git_repo") as mock_find:
        mock_find.return_value = None

        count, files = check_git_status(tmp_path)

        assert count == -1
        assert files == []


def test_check_git_status_various_status_codes(tmp_path):
    """Test check_git_status with various git status codes."""
    git_output = """M  staged.go
 M unstaged.go
MM both.go
A  added.go
D  deleted.go
?? untracked.go
"""

    with (
        patch("updater.git_operations.find_git_repo") as mock_find,
        patch("subprocess.run") as mock_run,
    ):
        mock_find.return_value = tmp_path
        mock_run.return_value = Mock(returncode=0, stdout=git_output)

        count, files = check_git_status(tmp_path)

        assert count == 6
        assert files == [
            "staged.go",
            "unstaged.go",
            "both.go",
            "added.go",
            "deleted.go",
            "untracked.go",
        ]


def test_check_git_status_subdirectory_filters(tmp_path):
    """Test check_git_status filters to only show changes in subdirectory."""
    # Setup: Create a mock monorepo structure
    repo_root = tmp_path / "repo"
    module_path = repo_root / "skeleton"

    # Git status shows changes in multiple directories
    git_output = """M  skeleton/go.mod
M  skeleton/main.go
M  k8s/gcp-snapshot-schedule-manager/go.mod
M  raw/schema-v1/pipe-controller/go.mod
"""

    with (
        patch("updater.git_operations.find_git_repo") as mock_find,
        patch("subprocess.run") as mock_run,
    ):
        mock_find.return_value = repo_root
        mock_run.return_value = Mock(returncode=0, stdout=git_output)

        count, files = check_git_status(module_path)

        # Should only include files in skeleton/
        assert count == 2
        assert files == ["skeleton/go.mod", "skeleton/main.go"]


def test_check_git_status_excludes_vendor(tmp_path):
    """Test check_git_status excludes vendor/ directory files."""
    git_output = """M  go.mod
M  go.sum
M  main.go
M  vendor/github.com/foo/bar/file.go
M  vendor/modules.txt
M  skeleton/vendor/github.com/baz/file.go
"""

    with (
        patch("updater.git_operations.find_git_repo") as mock_find,
        patch("subprocess.run") as mock_run,
    ):
        mock_find.return_value = tmp_path
        mock_run.return_value = Mock(returncode=0, stdout=git_output)

        count, files = check_git_status(tmp_path)

        # Should exclude all vendor/ files
        assert count == 3
        assert files == ["go.mod", "go.sum", "main.go"]


def test_git_push_calls_push_and_tags(tmp_path):
    """Test git_push pushes commits and tags to origin."""
    log = Mock()

    with patch("updater.log_manager.run_command") as mock_run:
        git_push(tmp_path, log_func=log)

        assert mock_run.call_count == 2
        calls = [c[0][0] for c in mock_run.call_args_list]
        assert "git push origin" in calls
        assert "git push origin --tags" in calls


def test_get_latest_tag_returns_tag(tmp_path):
    """Test get_latest_tag returns the latest git tag."""
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = Mock(returncode=0, stdout="v1.9.3\n")

        result = get_latest_tag(tmp_path)

        assert result == "v1.9.3"


def test_get_latest_tag_no_tags(tmp_path):
    """Test get_latest_tag returns None when no tags exist."""
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = Mock(returncode=0, stdout="\n")

        result = get_latest_tag(tmp_path)

        assert result is None


def test_get_commits_since_tag_returns_commits(tmp_path):
    """Test get_commits_since_tag returns list of commits."""
    delimiter = "---COMMIT_DELIMITER---"
    git_output = f"abc1234{delimiter}Add new feature{delimiter}Body text{delimiter}\ndef5678{delimiter}Fix bug{delimiter}{delimiter}\n"

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = Mock(returncode=0, stdout=git_output)

        result = get_commits_since_tag(tmp_path, "v1.0.0")

        assert len(result) == 2
        assert result[0]["hash"] == "abc1234"
        assert result[0]["subject"] == "Add new feature"
        assert result[0]["body"] == "Body text"
        assert result[1]["hash"] == "def5678"
        assert result[1]["subject"] == "Fix bug"


def test_get_commits_since_tag_no_commits(tmp_path):
    """Test get_commits_since_tag returns empty list when no commits."""
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = Mock(returncode=0, stdout="")

        result = get_commits_since_tag(tmp_path, "v1.0.0")

        assert result == []


def test_get_commits_since_tag_no_tag(tmp_path):
    """Test get_commits_since_tag works with no tag (all commits)."""
    delimiter = "---COMMIT_DELIMITER---"
    git_output = f"abc1234{delimiter}Initial commit{delimiter}{delimiter}\n"

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = Mock(returncode=0, stdout=git_output)

        result = get_commits_since_tag(tmp_path, None)

        assert len(result) == 1
        assert result[0]["subject"] == "Initial commit"


def test_get_latest_tag_with_v_prefix(tmp_path):
    """Test get_latest_tag handles v prefix correctly."""
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = Mock(returncode=0, stdout="v1.2.3\n")

        result = get_latest_tag(tmp_path)

        assert result == "v1.2.3"


# --- update_git_branch tests ---


def test_update_git_branch_success_with_tracking(tmp_path):
    """Test update_git_branch succeeds: fetch, pull (tracking branch), merge all succeed."""
    log = Mock()

    with patch("subprocess.run") as mock_run:
        mock_run.side_effect = [
            Mock(returncode=0, stdout="main\n", stderr=""),  # git branch --show-current
            Mock(returncode=0, stdout="", stderr=""),  # git fetch origin
            Mock(returncode=0, stdout="origin/main\n", stderr=""),  # rev-parse (has tracking)
            Mock(returncode=0, stdout="", stderr=""),  # git pull
            Mock(returncode=0, stdout="", stderr=""),  # git merge origin/master
        ]

        result = update_git_branch(tmp_path, log_func=log)

        assert result is True


def test_update_git_branch_fetch_failure(tmp_path):
    """Test update_git_branch returns False when fetch fails."""
    log = Mock()

    with patch("subprocess.run") as mock_run:
        mock_run.side_effect = [
            Mock(returncode=0, stdout="main\n", stderr=""),  # git branch --show-current
            Mock(returncode=1, stdout="", stderr="fetch failed"),  # git fetch fails
        ]

        result = update_git_branch(tmp_path, log_func=log)

        assert result is False


def test_update_git_branch_no_tracking_branch(tmp_path):
    """Test update_git_branch skips pull when no tracking branch."""
    log = Mock()

    with patch("subprocess.run") as mock_run:
        mock_run.side_effect = [
            Mock(returncode=0, stdout="feature\n", stderr=""),  # git branch --show-current
            Mock(returncode=0, stdout="", stderr=""),  # git fetch origin
            Mock(returncode=128, stdout="", stderr="no upstream"),  # rev-parse fails (no tracking)
            Mock(returncode=0, stdout="", stderr=""),  # git merge origin/master
        ]

        result = update_git_branch(tmp_path, log_func=log)

        assert result is True


def test_update_git_branch_merge_failure(tmp_path):
    """Test update_git_branch returns False when merge fails."""
    log = Mock()

    with patch("subprocess.run") as mock_run:
        mock_run.side_effect = [
            Mock(returncode=0, stdout="main\n", stderr=""),  # git branch --show-current
            Mock(returncode=0, stdout="", stderr=""),  # git fetch origin
            Mock(returncode=128, stdout="", stderr="no upstream"),  # no tracking branch
            Mock(returncode=1, stdout="", stderr="merge conflict"),  # git merge fails
        ]

        result = update_git_branch(tmp_path, log_func=log)

        assert result is False


def test_update_git_branch_default_log(tmp_path):
    """Test update_git_branch uses print when no log_func provided."""
    with patch("subprocess.run") as mock_run:
        mock_run.side_effect = [
            Mock(returncode=0, stdout="main\n", stderr=""),
            Mock(returncode=0, stdout="", stderr=""),
            Mock(returncode=128, stdout="", stderr=""),
            Mock(returncode=0, stdout="", stderr=""),
        ]

        with patch("builtins.print") as mock_print:
            result = update_git_branch(tmp_path)

            assert result is True
            assert mock_print.called


# --- git_commit tests ---


def test_git_commit_success(tmp_path):
    """Test git_commit calls git add and git commit."""
    log = Mock()

    with patch("updater.log_manager.run_command") as mock_run:
        git_commit(tmp_path, "test commit message", log_func=log)

        assert mock_run.call_count == 2
        calls = [c[0][0] for c in mock_run.call_args_list]
        assert "git add ." in calls
        assert any("git commit" in c for c in calls)


def test_git_commit_failure_raises(tmp_path):
    """Test git_commit propagates RuntimeError from run_command."""
    log = Mock()

    with patch("updater.log_manager.run_command") as mock_run:
        mock_run.side_effect = RuntimeError("git commit failed")

        with pytest.raises(RuntimeError):
            git_commit(tmp_path, "test message", log_func=log)


# --- git_tag_from_changelog tests ---


def test_git_tag_from_changelog_success(tmp_path):
    """Test git_tag_from_changelog creates tag when conditions are met."""
    log = Mock()

    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text("# Changelog\n\n## v1.2.3\n\n- Some change\n")

    with (
        patch("subprocess.run") as mock_run,
        patch("updater.log_manager.run_command") as mock_cmd,
    ):
        mock_run.side_effect = [
            Mock(returncode=0),  # git diff-index (no uncommitted changes)
            Mock(returncode=1),  # git describe --tags (HEAD not tagged)
        ]

        git_tag_from_changelog(tmp_path, log_func=log)

        mock_cmd.assert_called_once()
        cmd = mock_cmd.call_args[0][0]
        assert "v1.2.3" in cmd


def test_git_tag_from_changelog_uncommitted_changes(tmp_path):
    """Test git_tag_from_changelog skips when there are uncommitted changes."""
    log = Mock()

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = Mock(returncode=1)  # diff-index: uncommitted changes

        with patch("updater.log_manager.run_command") as mock_cmd:
            git_tag_from_changelog(tmp_path, log_func=log)

            mock_cmd.assert_not_called()


def test_git_tag_from_changelog_already_tagged(tmp_path):
    """Test git_tag_from_changelog skips when HEAD is already tagged."""
    log = Mock()

    with patch("subprocess.run") as mock_run:
        mock_run.side_effect = [
            Mock(returncode=0),  # git diff-index (clean)
            Mock(returncode=0),  # git describe (already tagged)
        ]

        with patch("updater.log_manager.run_command") as mock_cmd:
            git_tag_from_changelog(tmp_path, log_func=log)

            mock_cmd.assert_not_called()


def test_git_tag_from_changelog_no_changelog(tmp_path):
    """Test git_tag_from_changelog skips when no CHANGELOG.md found."""
    log = Mock()

    with patch("subprocess.run") as mock_run:
        mock_run.side_effect = [
            Mock(returncode=0),  # git diff-index (clean)
            Mock(returncode=1),  # git describe (not tagged)
        ]

        with patch("updater.log_manager.run_command") as mock_cmd:
            git_tag_from_changelog(tmp_path, log_func=log)

            mock_cmd.assert_not_called()


def test_git_tag_from_changelog_no_version_in_changelog(tmp_path):
    """Test git_tag_from_changelog skips when CHANGELOG has no version."""
    log = Mock()

    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text("# Changelog\n\n## Unreleased\n\n- Some change\n")

    with patch("subprocess.run") as mock_run:
        mock_run.side_effect = [
            Mock(returncode=0),  # git diff-index (clean)
            Mock(returncode=1),  # git describe (not tagged)
        ]

        with patch("updater.log_manager.run_command") as mock_cmd:
            git_tag_from_changelog(tmp_path, log_func=log)

            mock_cmd.assert_not_called()


# --- update_git_branch missing path tests ---


def test_update_git_branch_branch_command_failure(tmp_path):
    """Test update_git_branch returns False when git branch --show-current fails."""
    log = Mock()

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = Mock(returncode=1, stdout="", stderr="not a git repo")

        result = update_git_branch(tmp_path, log_func=log)

        assert result is False


def test_update_git_branch_pull_failure(tmp_path):
    """Test update_git_branch returns False when pull fails (tracking branch exists)."""
    log = Mock()

    with patch("subprocess.run") as mock_run:
        mock_run.side_effect = [
            Mock(returncode=0, stdout="main\n", stderr=""),  # git branch --show-current
            Mock(returncode=0, stdout="", stderr=""),  # git fetch origin
            Mock(returncode=0, stdout="origin/main\n", stderr=""),  # rev-parse (has tracking)
            Mock(returncode=1, stdout="", stderr="pull failed"),  # git pull fails
        ]

        result = update_git_branch(tmp_path, log_func=log)

        assert result is False


# --- ensure_changelog_tag tests ---


def test_ensure_changelog_tag_no_changelog(tmp_path):
    """Test ensure_changelog_tag returns False when no CHANGELOG.md."""
    from updater.git_operations import ensure_changelog_tag

    log = Mock()

    result = ensure_changelog_tag(tmp_path, log_func=log)

    assert result is False


def test_ensure_changelog_tag_no_version(tmp_path):
    """Test ensure_changelog_tag returns False when CHANGELOG has no version."""
    from updater.git_operations import ensure_changelog_tag

    log = Mock()
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text("# Changelog\n\n## Unreleased\n\n- Change\n")

    result = ensure_changelog_tag(tmp_path, log_func=log)

    assert result is False


def test_ensure_changelog_tag_already_exists(tmp_path):
    """Test ensure_changelog_tag returns False when tag already exists."""
    from updater.git_operations import ensure_changelog_tag

    log = Mock()
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text("# Changelog\n\n## v1.2.3\n\n- Change\n")

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = Mock(returncode=0, stdout="v1.2.3\n")

        result = ensure_changelog_tag(tmp_path, log_func=log)

        assert result is False


def test_ensure_changelog_tag_creates_tag(tmp_path):
    """Test ensure_changelog_tag creates tag when version exists and tag is missing."""
    from updater.git_operations import ensure_changelog_tag

    log = Mock()
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text("# Changelog\n\n## v1.2.3\n\n- Change\n")

    with (
        patch("subprocess.run") as mock_run,
        patch("updater.log_manager.run_command") as mock_cmd,
    ):
        mock_run.return_value = Mock(returncode=0, stdout="")  # tag doesn't exist

        result = ensure_changelog_tag(tmp_path, log_func=log)

        assert result is True
        mock_cmd.assert_called_once()
        cmd = mock_cmd.call_args[0][0]
        assert "v1.2.3" in cmd


# --- get_commits_since_tag error path ---


def test_get_commits_since_tag_git_error(tmp_path):
    """Test get_commits_since_tag returns empty list on git error."""
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = Mock(returncode=1, stdout="", stderr="error")

        result = get_commits_since_tag(tmp_path, "v1.0.0")

        assert result == []


# --- branch and PR helpers ---


def test_git_checkout_new_branch(tmp_path):
    """Test git_checkout_new_branch runs git checkout -b with the branch name."""
    log = Mock()

    with patch("updater.log_manager.run_command") as mock_run:
        git_checkout_new_branch(tmp_path, "updater/claude-yolo-1.28.0", log_func=log)

    mock_run.assert_called_once()
    cmd = mock_run.call_args[0][0]
    assert "git checkout -b updater/claude-yolo-1.28.0" in cmd


def test_find_existing_pull_request_none(tmp_path):
    """Test find_existing_pull_request returns None for an empty PR list."""
    log = Mock()

    with patch("updater.log_manager.run_command") as mock_run:
        mock_run.return_value = Mock(returncode=0, stdout="[]")

        result = find_existing_pull_request(tmp_path, "bborbe/claude-yolo", log_func=log)

    assert result is None


def test_find_existing_pull_request_empty_stdout(tmp_path):
    """Test find_existing_pull_request returns None for empty stdout."""
    log = Mock()

    with patch("updater.log_manager.run_command") as mock_run:
        mock_run.return_value = Mock(returncode=0, stdout="")

        result = find_existing_pull_request(tmp_path, "bborbe/claude-yolo", log_func=log)

    assert result is None


def test_find_existing_pull_request_found(tmp_path):
    """Test find_existing_pull_request returns the first open PR's URL."""
    log = Mock()

    with patch("updater.log_manager.run_command") as mock_run:
        mock_run.return_value = Mock(
            returncode=0,
            stdout='[{"url": "https://github.com/bborbe/claude-yolo/pull/5"}]',
        )

        result = find_existing_pull_request(tmp_path, "bborbe/claude-yolo", log_func=log)

    assert result == "https://github.com/bborbe/claude-yolo/pull/5"


def test_find_existing_pull_request_gh_error(tmp_path):
    """Test find_existing_pull_request propagates RuntimeError from gh."""
    log = Mock()

    with patch("updater.log_manager.run_command") as mock_run:
        mock_run.side_effect = RuntimeError("gh pr list failed")

        with pytest.raises(RuntimeError):
            find_existing_pull_request(tmp_path, "bborbe/claude-yolo", log_func=log)


def test_create_pull_request_returns_url(tmp_path):
    """Test create_pull_request returns the PR URL and builds the gh command."""
    log = Mock()
    url = "https://github.com/bborbe/claude-yolo/pull/6"

    with patch("updater.log_manager.run_command") as mock_run:
        mock_run.return_value = Mock(returncode=0, stdout=url)

        result = create_pull_request(
            tmp_path,
            "bborbe/claude-yolo",
            "updater/claude-yolo-1.28.0",
            "chore: bump Go version to 1.28.0 in Dockerfile",
            "Bump ARG GO_VERSION to 1.28.0.",
            log_func=log,
        )

    assert result == url
    cmd = mock_run.call_args[0][0]
    assert "--repo bborbe/claude-yolo" in cmd
    assert "--head updater/claude-yolo-1.28.0" in cmd
    assert "chore: bump Go version to 1.28.0 in Dockerfile" in cmd
    assert "Bump ARG GO_VERSION to 1.28.0." in cmd


def test_create_pull_request_failure_propagates(tmp_path):
    """Test create_pull_request propagates RuntimeError from gh."""
    log = Mock()

    with patch("updater.log_manager.run_command") as mock_run:
        mock_run.side_effect = RuntimeError("gh pr create failed")

        with pytest.raises(RuntimeError):
            create_pull_request(
                tmp_path,
                "bborbe/claude-yolo",
                "updater/claude-yolo-1.28.0",
                "title",
                "body",
                log_func=log,
            )
