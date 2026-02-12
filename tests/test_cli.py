"""Tests for CLI orchestration and workflow."""

from unittest.mock import AsyncMock, patch

import pytest

from updater import config
from updater.cli import main_async, process_module_with_retry, process_single_go_module


@pytest.fixture
def reset_config():
    """Reset global config before each test."""
    config.VERBOSE_MODE = False
    config.MODEL = "sonnet"
    config.REQUIRE_CONFIRM = False
    config.RUN_TIMESTAMP = "2024-01-01-120000"
    config.LOG_FILE_HANDLE = None
    yield
    config.LOG_FILE_HANDLE = None


@pytest.fixture
def mock_module_path(tmp_path):
    """Create a mock module directory with go.mod."""
    module_path = tmp_path / "test-module"
    module_path.mkdir()
    (module_path / "go.mod").write_text("module test\n")
    (module_path / ".git").mkdir()
    return module_path


class TestProcessSingleModule:
    """Tests for process_single_go_module function."""

    @pytest.mark.asyncio
    async def test_no_git_repo(self, tmp_path, reset_config):
        """Test process_single_go_module fails when no git repo found."""
        module_path = tmp_path / "no-git"
        module_path.mkdir()

        with patch("updater.cli.find_git_repo", return_value=None):
            success, status = await process_single_go_module(module_path)

        assert success is False
        assert status == "failed"

    @pytest.mark.asyncio
    async def test_no_updates_needed(self, mock_module_path, reset_config):
        """Test process_single_go_module succeeds when no updates needed."""
        with (
            patch("updater.cli.find_git_repo", return_value=mock_module_path),
            patch("updater.cli.setup_module_logging", return_value=None),
            patch("updater.cli.ensure_gitignore_entry"),
            patch("updater.cli.update_versions", return_value=False),
            patch("updater.cli.apply_gomod_excludes_and_replaces", return_value=False),
            patch("updater.cli.update_go_dependencies", return_value=False),
            patch("updater.cli.check_git_status", return_value=(0, [])),
            patch("updater.cli.close_module_logging"),
            patch("updater.cli.cleanup_old_logs"),
        ):
            success, status = await process_single_go_module(mock_module_path)

        assert success is True
        assert status == "up-to-date"

    @pytest.mark.asyncio
    async def test_updates_made_no_changes_after(self, mock_module_path, reset_config):
        """Test when updates are made but no git changes remain."""
        with (
            patch("updater.cli.find_git_repo", return_value=mock_module_path),
            patch("updater.cli.setup_module_logging", return_value=None),
            patch("updater.cli.ensure_gitignore_entry"),
            patch("updater.cli.update_versions", return_value=True),
            patch("updater.cli.apply_gomod_excludes_and_replaces", return_value=False),
            patch("updater.cli.update_go_dependencies", return_value=False),
            patch("updater.cli.check_git_status", return_value=(0, [])),
            patch("updater.cli.close_module_logging"),
            patch("updater.cli.cleanup_old_logs"),
        ):
            success, status = await process_single_go_module(mock_module_path)

        assert success is True
        assert status == "up-to-date"

    @pytest.mark.asyncio
    async def test_with_changes_and_changelog(self, mock_module_path, reset_config):
        """Test full workflow with changes, CHANGELOG, and tagging."""
        # Create CHANGELOG.md
        changelog = mock_module_path / "CHANGELOG.md"
        changelog.write_text("# Changelog\n\n## v1.0.0\n\n- Initial release\n")

        analysis = {
            "version_bump": "patch",
            "changelog": ["update dependencies"],
            "commit_message": "update deps",
        }

        with (
            patch("updater.cli.find_git_repo", return_value=mock_module_path),
            patch("updater.cli.setup_module_logging", return_value=None),
            patch("updater.cli.ensure_gitignore_entry"),
            patch("updater.cli.update_versions", return_value=True),
            patch("updater.cli.apply_gomod_excludes_and_replaces", return_value=False),
            patch("updater.cli.update_go_dependencies", return_value=False),
            patch(
                "updater.cli.check_git_status",
                side_effect=[(2, ["go.mod", "go.sum"]), (2, ["go.mod", "go.sum"])],
            ),
            patch("updater.cli.run_go_precommit"),
            patch(
                "updater.cli.analyze_changes_with_claude",
                new_callable=AsyncMock,
                return_value=analysis,
            ),
            patch("updater.cli.update_changelog_with_suggestions", return_value="v1.0.1"),
            patch("updater.cli.git_commit"),
            patch("updater.cli.git_tag_from_changelog"),
            patch("updater.cli.close_module_logging"),
            patch("updater.cli.cleanup_old_logs"),
            patch("builtins.print"),
        ):
            success, status = await process_single_go_module(mock_module_path)

        assert success is True
        assert status == "updated"

    @pytest.mark.asyncio
    async def test_no_changelog_with_version_bump(self, mock_module_path, reset_config):
        """Test workflow when no CHANGELOG.md exists but version bump requested."""
        analysis = {
            "version_bump": "patch",
            "changelog": ["update dependencies"],
            "commit_message": "update deps",
        }

        with (
            patch("updater.cli.find_git_repo", return_value=mock_module_path),
            patch("updater.cli.setup_module_logging", return_value=None),
            patch("updater.cli.ensure_gitignore_entry"),
            patch("updater.cli.update_versions", return_value=True),
            patch("updater.cli.apply_gomod_excludes_and_replaces", return_value=False),
            patch("updater.cli.update_go_dependencies", return_value=False),
            patch(
                "updater.cli.check_git_status",
                side_effect=[(2, ["go.mod", "go.sum"]), (2, ["go.mod", "go.sum"])],
            ),
            patch("updater.cli.run_go_precommit"),
            patch(
                "updater.cli.analyze_changes_with_claude",
                new_callable=AsyncMock,
                return_value=analysis,
            ),
            patch("updater.cli.git_commit"),
            patch("updater.cli.close_module_logging"),
            patch("updater.cli.cleanup_old_logs"),
            patch("builtins.print"),
        ):
            success, status = await process_single_go_module(mock_module_path)

        assert success is True
        assert status == "updated"

    @pytest.mark.asyncio
    async def test_no_version_bump_infrastructure_only(self, mock_module_path, reset_config):
        """Test workflow when only infrastructure changes (version_bump=none)."""
        analysis = {
            "version_bump": "none",
            "changelog": ["update .gitignore"],
            "commit_message": "update .gitignore",
        }

        with (
            patch("updater.cli.find_git_repo", return_value=mock_module_path),
            patch("updater.cli.setup_module_logging", return_value=None),
            patch("updater.cli.ensure_gitignore_entry"),
            patch("updater.cli.update_versions", return_value=False),
            patch("updater.cli.apply_gomod_excludes_and_replaces", return_value=False),
            patch("updater.cli.update_go_dependencies", return_value=False),
            patch(
                "updater.cli.check_git_status",
                side_effect=[(1, [".gitignore"]), (1, [".gitignore"])],
            ),
            patch("updater.cli.run_go_precommit"),
            patch(
                "updater.cli.analyze_changes_with_claude",
                new_callable=AsyncMock,
                return_value=analysis,
            ),
            patch("updater.cli.git_commit"),
            patch("updater.cli.close_module_logging"),
            patch("updater.cli.cleanup_old_logs"),
            patch("builtins.print"),
        ):
            success, status = await process_single_go_module(mock_module_path)

        assert success is True
        assert status == "updated"

    @pytest.mark.asyncio
    async def test_exception_handling(self, mock_module_path, reset_config):
        """Test exception handling returns False."""
        with (
            patch("updater.cli.find_git_repo", side_effect=RuntimeError("Test error")),
            patch("updater.cli.setup_module_logging", return_value=None),
            patch("updater.cli.close_module_logging"),
            patch("updater.cli.cleanup_old_logs"),
        ):
            success, status = await process_single_go_module(mock_module_path)

        assert success is False
        assert status == "failed"

    @pytest.mark.asyncio
    async def test_with_confirmation_accept(self, mock_module_path, reset_config):
        """Test workflow with user confirmation (accepted)."""
        config.REQUIRE_CONFIRM = True
        changelog = mock_module_path / "CHANGELOG.md"
        changelog.write_text("# Changelog\n\n## v1.0.0\n\n- Initial release\n")

        analysis = {
            "version_bump": "patch",
            "changelog": ["update dependencies"],
            "commit_message": "update deps",
        }

        with (
            patch("updater.cli.find_git_repo", return_value=mock_module_path),
            patch("updater.cli.setup_module_logging", return_value=None),
            patch("updater.cli.ensure_gitignore_entry"),
            patch("updater.cli.update_versions", return_value=True),
            patch("updater.cli.apply_gomod_excludes_and_replaces", return_value=False),
            patch("updater.cli.update_go_dependencies", return_value=False),
            patch(
                "updater.cli.check_git_status",
                side_effect=[(2, ["go.mod", "go.sum"]), (2, ["go.mod", "go.sum"])],
            ),
            patch("updater.cli.run_go_precommit"),
            patch(
                "updater.cli.analyze_changes_with_claude",
                new_callable=AsyncMock,
                return_value=analysis,
            ),
            patch("updater.cli.update_changelog_with_suggestions", return_value="v1.0.1"),
            patch("updater.cli.prompt_yes_no", return_value=True),
            patch("updater.cli.git_commit"),
            patch("updater.cli.git_tag_from_changelog"),
            patch("updater.cli.close_module_logging"),
            patch("updater.cli.cleanup_old_logs"),
            patch("builtins.print"),
        ):
            success, status = await process_single_go_module(mock_module_path)

        assert success is True
        assert status == "updated"

    @pytest.mark.asyncio
    async def test_with_confirmation_reject(self, mock_module_path, reset_config):
        """Test workflow with user confirmation (rejected)."""
        config.REQUIRE_CONFIRM = True
        changelog = mock_module_path / "CHANGELOG.md"
        changelog.write_text("# Changelog\n\n## v1.0.0\n\n- Initial release\n")

        analysis = {
            "version_bump": "patch",
            "changelog": ["update dependencies"],
            "commit_message": "update deps",
        }

        with (
            patch("updater.cli.find_git_repo", return_value=mock_module_path),
            patch("updater.cli.setup_module_logging", return_value=None),
            patch("updater.cli.ensure_gitignore_entry"),
            patch("updater.cli.update_versions", return_value=True),
            patch("updater.cli.apply_gomod_excludes_and_replaces", return_value=False),
            patch("updater.cli.update_go_dependencies", return_value=False),
            patch(
                "updater.cli.check_git_status",
                side_effect=[(2, ["go.mod", "go.sum"]), (2, ["go.mod", "go.sum"])],
            ),
            patch("updater.cli.run_go_precommit"),
            patch(
                "updater.cli.analyze_changes_with_claude",
                new_callable=AsyncMock,
                return_value=analysis,
            ),
            patch("updater.cli.update_changelog_with_suggestions", return_value="v1.0.1"),
            patch("updater.cli.prompt_yes_no", return_value=False),
            patch("updater.cli.close_module_logging"),
            patch("updater.cli.cleanup_old_logs"),
            patch("builtins.print"),
        ):
            success, status = await process_single_go_module(mock_module_path)

        # User rejected, but function returns True (changes staged but not committed)
        assert success is True
        assert status == "skipped"

    @pytest.mark.asyncio
    async def test_changes_cleared_after_precommit(self, mock_module_path, reset_config):
        """Test when precommit auto-fixes all issues."""
        with (
            patch("updater.cli.find_git_repo", return_value=mock_module_path),
            patch("updater.cli.setup_module_logging", return_value=None),
            patch("updater.cli.ensure_gitignore_entry"),
            patch("updater.cli.update_versions", return_value=True),
            patch("updater.cli.apply_gomod_excludes_and_replaces", return_value=False),
            patch("updater.cli.update_go_dependencies", return_value=False),
            # First check shows changes, precommit runs, second check shows no changes
            patch("updater.cli.check_git_status", side_effect=[(2, ["go.mod", "go.sum"]), (0, [])]),
            patch("updater.cli.run_go_precommit"),
            patch("updater.cli.close_module_logging"),
            patch("updater.cli.cleanup_old_logs"),
        ):
            success, status = await process_single_go_module(mock_module_path)

        assert success is True
        assert status == "up-to-date"


class TestProcessModuleWithRetry:
    """Tests for process_module_with_retry function."""

    @pytest.mark.asyncio
    async def test_success_first_try(self, mock_module_path):
        """Test successful processing on first attempt."""
        with patch(
            "updater.cli.process_single_go_module",
            new_callable=AsyncMock,
            return_value=(True, "updated"),
        ):
            success, status = await process_module_with_retry(mock_module_path)

        assert success is True
        assert status == "updated"

    @pytest.mark.asyncio
    async def test_retry_then_success(self, mock_module_path):
        """Test retry after failure, then success."""
        with (
            patch(
                "updater.cli.process_single_go_module",
                new_callable=AsyncMock,
                side_effect=[(False, "failed"), (True, "updated")],
            ),
            patch("updater.cli.prompt_skip_or_retry", return_value="retry"),
            patch("updater.cli.play_error_sound"),
            patch("builtins.print"),
        ):
            success, status = await process_module_with_retry(mock_module_path)

        assert success is True
        assert status == "updated"

    @pytest.mark.asyncio
    async def test_skip_after_failure(self, mock_module_path):
        """Test user chooses to skip after failure."""
        with (
            patch(
                "updater.cli.process_single_go_module",
                new_callable=AsyncMock,
                return_value=(False, "failed"),
            ),
            patch("updater.cli.prompt_skip_or_retry", return_value="skip"),
            patch("updater.cli.play_error_sound"),
            patch("builtins.print"),
        ):
            success, status = await process_module_with_retry(mock_module_path)

        assert success is False
        assert status == "skipped"

    @pytest.mark.asyncio
    async def test_multiple_retries(self, mock_module_path):
        """Test multiple retry attempts before success."""
        with (
            patch(
                "updater.cli.process_single_go_module",
                new_callable=AsyncMock,
                side_effect=[(False, "failed"), (False, "failed"), (True, "updated")],
            ),
            patch("updater.cli.prompt_skip_or_retry", return_value="retry"),
            patch("updater.cli.play_error_sound"),
            patch("builtins.print"),
        ):
            success, status = await process_module_with_retry(mock_module_path)

        assert success is True
        assert status == "updated"


class TestMainAsync:
    """Tests for main_async function."""

    @pytest.mark.asyncio
    async def test_no_modules_found(self, tmp_path, reset_config):
        """Test when no modules are found."""
        with (
            patch("sys.argv", ["update-deps", str(tmp_path)]),
            patch(
                "updater.cli.verify_claude_auth", new_callable=AsyncMock, return_value=(True, None)
            ),
            patch("updater.cli.play_completion_sound"),
        ):
            exit_code = await main_async()

        assert exit_code == 1

    @pytest.mark.asyncio
    async def test_nonexistent_path(self, tmp_path, reset_config):
        """Test with non-existent path."""
        nonexistent = tmp_path / "does-not-exist"

        with (
            patch("sys.argv", ["update-deps", str(nonexistent)]),
            patch(
                "updater.cli.verify_claude_auth", new_callable=AsyncMock, return_value=(True, None)
            ),
            patch("updater.cli.play_completion_sound"),
        ):
            exit_code = await main_async()

        assert exit_code == 1

    @pytest.mark.asyncio
    async def test_single_module_success(self, mock_module_path, reset_config):
        """Test successful processing of single module."""
        with (
            patch("sys.argv", ["update-deps", str(mock_module_path)]),
            patch(
                "updater.cli.verify_claude_auth", new_callable=AsyncMock, return_value=(True, None)
            ),
            patch("updater.cli.find_git_repo", return_value=mock_module_path.parent),
            patch("updater.cli.update_git_branch", return_value=True),
            patch("updater.cli.check_git_status", return_value=(0, [])),
            patch(
                "updater.cli.process_module_with_retry",
                new_callable=AsyncMock,
                return_value=(True, "updated"),
            ),
            patch("updater.cli.play_completion_sound"),
            patch("builtins.print"),
        ):
            exit_code = await main_async()

        assert exit_code == 0

    @pytest.mark.asyncio
    async def test_single_module_failure(self, mock_module_path, reset_config):
        """Test failed processing of single module."""
        with (
            patch("sys.argv", ["update-deps", str(mock_module_path)]),
            patch(
                "updater.cli.verify_claude_auth", new_callable=AsyncMock, return_value=(True, None)
            ),
            patch("updater.cli.find_git_repo", return_value=mock_module_path.parent),
            patch("updater.cli.update_git_branch", return_value=True),
            patch("updater.cli.check_git_status", return_value=(0, [])),
            patch(
                "updater.cli.process_module_with_retry",
                new_callable=AsyncMock,
                return_value=(False, "skipped"),
            ),
            patch("updater.cli.play_completion_sound"),
            patch("builtins.print"),
        ):
            exit_code = await main_async()

        assert exit_code == 1

    @pytest.mark.asyncio
    async def test_git_update_failure(self, mock_module_path, reset_config):
        """Test when git update fails."""
        with (
            patch("sys.argv", ["update-deps", str(mock_module_path)]),
            patch("updater.cli.find_git_repo", return_value=mock_module_path.parent),
            patch("updater.cli.update_git_branch", return_value=False),
            patch("updater.cli.check_git_status", return_value=(0, [])),
            patch(
                "updater.cli.verify_claude_auth", new_callable=AsyncMock, return_value=(True, None)
            ),
            patch("updater.cli.play_completion_sound"),
            patch("updater.cli.play_error_sound"),
            patch("builtins.print"),
        ):
            exit_code = await main_async()

        assert exit_code == 1

    @pytest.mark.asyncio
    async def test_uncommitted_changes_abort(self, mock_module_path, reset_config):
        """Test aborting when uncommitted changes detected."""
        with (
            patch("sys.argv", ["update-deps", str(mock_module_path)]),
            patch(
                "updater.cli.verify_claude_auth", new_callable=AsyncMock, return_value=(True, None)
            ),
            patch("updater.cli.find_git_repo", return_value=mock_module_path.parent),
            patch("updater.cli.update_git_branch", return_value=True),
            patch("updater.cli.check_git_status", return_value=(2, ["go.mod", "go.sum"])),
            patch("updater.cli.prompt_yes_no", return_value=False),
            patch("updater.cli.play_completion_sound"),
            patch("builtins.print"),
        ):
            exit_code = await main_async()

        assert exit_code == 1

    @pytest.mark.asyncio
    async def test_uncommitted_changes_continue(self, mock_module_path, reset_config):
        """Test continuing when uncommitted changes detected."""
        with (
            patch("sys.argv", ["update-deps", str(mock_module_path)]),
            patch(
                "updater.cli.verify_claude_auth", new_callable=AsyncMock, return_value=(True, None)
            ),
            patch("updater.cli.find_git_repo", return_value=mock_module_path.parent),
            patch("updater.cli.update_git_branch", return_value=True),
            patch("updater.cli.check_git_status", return_value=(2, ["go.mod", "go.sum"])),
            patch("updater.cli.prompt_yes_no", return_value=True),
            patch(
                "updater.cli.process_module_with_retry",
                new_callable=AsyncMock,
                return_value=(True, "updated"),
            ),
            patch("updater.cli.play_completion_sound"),
            patch("builtins.print"),
        ):
            exit_code = await main_async()

        assert exit_code == 0

    @pytest.mark.asyncio
    async def test_multi_module_success(self, tmp_path, reset_config):
        """Test successful processing of multiple modules."""
        # Create two modules
        mod1 = tmp_path / "mod1"
        mod1.mkdir()
        (mod1 / "go.mod").write_text("module mod1\n")

        mod2 = tmp_path / "mod2"
        mod2.mkdir()
        (mod2 / "go.mod").write_text("module mod2\n")

        with (
            patch("sys.argv", ["update-deps", str(mod1), str(mod2)]),
            patch(
                "updater.cli.verify_claude_auth", new_callable=AsyncMock, return_value=(True, None)
            ),
            patch("updater.cli.find_git_repo", return_value=tmp_path),
            patch("updater.cli.update_git_branch", return_value=True),
            patch("updater.cli.check_git_status", return_value=(0, [])),
            patch(
                "updater.cli.process_module_with_retry",
                new_callable=AsyncMock,
                return_value=(True, "updated"),
            ),
            patch("updater.cli.play_completion_sound"),
            patch("builtins.print"),
        ):
            exit_code = await main_async()

        assert exit_code == 0

    @pytest.mark.asyncio
    async def test_verbose_mode(self, mock_module_path, reset_config):
        """Test verbose mode sets config correctly."""
        with (
            patch("sys.argv", ["update-deps", str(mock_module_path), "--verbose"]),
            patch(
                "updater.cli.verify_claude_auth", new_callable=AsyncMock, return_value=(True, None)
            ),
            patch("updater.cli.find_git_repo", return_value=mock_module_path.parent),
            patch("updater.cli.update_git_branch", return_value=True),
            patch("updater.cli.check_git_status", return_value=(0, [])),
            patch(
                "updater.cli.process_module_with_retry",
                new_callable=AsyncMock,
                return_value=(True, "updated"),
            ),
            patch("updater.cli.play_completion_sound"),
            patch("builtins.print"),
        ):
            exit_code = await main_async()

        assert config.VERBOSE_MODE is True
        assert exit_code == 0

    @pytest.mark.asyncio
    async def test_model_selection(self, mock_module_path, reset_config):
        """Test model selection."""
        with (
            patch("sys.argv", ["update-deps", str(mock_module_path), "--model", "haiku"]),
            patch("updater.cli.find_git_repo", return_value=mock_module_path.parent),
            patch("updater.cli.update_git_branch", return_value=True),
            patch("updater.cli.check_git_status", return_value=(0, [])),
            patch(
                "updater.cli.verify_claude_auth", new_callable=AsyncMock, return_value=(True, None)
            ),
            patch(
                "updater.cli.process_module_with_retry",
                new_callable=AsyncMock,
                return_value=(True, "updated"),
            ),
            patch("updater.cli.play_completion_sound"),
            patch("updater.cli.play_error_sound"),
            patch("builtins.print"),
        ):
            exit_code = await main_async()

        assert config.MODEL == "haiku"
        assert exit_code == 0

    @pytest.mark.asyncio
    async def test_require_commit_confirm(self, mock_module_path, reset_config):
        """Test require-commit-confirm flag."""
        with (
            patch("sys.argv", ["update-deps", str(mock_module_path), "--require-commit-confirm"]),
            patch(
                "updater.cli.verify_claude_auth", new_callable=AsyncMock, return_value=(True, None)
            ),
            patch("updater.cli.find_git_repo", return_value=mock_module_path.parent),
            patch("updater.cli.update_git_branch", return_value=True),
            patch("updater.cli.check_git_status", return_value=(0, [])),
            patch(
                "updater.cli.process_module_with_retry",
                new_callable=AsyncMock,
                return_value=(True, "updated"),
            ),
            patch("updater.cli.play_completion_sound"),
            patch("builtins.print"),
        ):
            exit_code = await main_async()

        assert config.REQUIRE_CONFIRM is True
        assert exit_code == 0

    @pytest.mark.asyncio
    async def test_recursive_discovery(self, tmp_path, reset_config):
        """Test recursive module discovery."""
        # Create nested modules
        parent = tmp_path / "parent"
        parent.mkdir()

        mod1 = parent / "mod1"
        mod1.mkdir()
        (mod1 / "go.mod").write_text("module mod1\n")

        nested = parent / "nested"
        nested.mkdir()
        mod2 = nested / "mod2"
        mod2.mkdir()
        (mod2 / "go.mod").write_text("module mod2\n")

        with (
            patch("sys.argv", ["update-deps", str(parent)]),
            patch(
                "updater.cli.verify_claude_auth", new_callable=AsyncMock, return_value=(True, None)
            ),
            patch("updater.cli.find_git_repo", return_value=tmp_path),
            patch("updater.cli.update_git_branch", return_value=True),
            patch("updater.cli.check_git_status", return_value=(0, [])),
            patch(
                "updater.cli.process_module_with_retry",
                new_callable=AsyncMock,
                return_value=(True, "updated"),
            ),
            patch("updater.cli.play_completion_sound"),
            patch("builtins.print"),
        ):
            exit_code = await main_async()

        assert exit_code == 0
