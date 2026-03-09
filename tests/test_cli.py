"""Tests for CLI orchestration and workflow."""

from unittest.mock import AsyncMock, patch

import pytest

from updater import config
from updater.cli import (
    main_async,
    process_module_with_retry,
    process_release_module,
    process_release_with_retry,
    process_single_go_module,
    process_single_python_module,
)


@pytest.fixture
def reset_config():
    """Reset global config before each test."""
    config.VERBOSE_MODE = False
    config.MODEL = "sonnet"
    config.REQUIRE_CONFIRM = False
    config.RUN_TIMESTAMP = "2024-01-01-120000"
    config.LOG_FILE_HANDLE = None
    config.YES_MODE = False
    config.NO_TAG = False
    config.CHECK_COMMAND = ""
    yield
    config.LOG_FILE_HANDLE = None
    config.YES_MODE = False
    config.NO_TAG = False
    config.CHECK_COMMAND = ""


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
            patch("updater.pipeline.update_git_branch", return_value=True),
            patch("updater.pipeline.update_versions", return_value=False),
            patch("updater.pipeline.apply_gomod_excludes_and_replaces", return_value=False),
            patch("updater.pipeline.update_go_dependencies", return_value=False),
            patch("updater.pipeline.check_git_status", return_value=(0, [])),
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
            patch("updater.pipeline.update_git_branch", return_value=True),
            patch("updater.pipeline.update_versions", return_value=True),
            patch("updater.pipeline.apply_gomod_excludes_and_replaces", return_value=False),
            patch("updater.pipeline.update_go_dependencies", return_value=False),
            patch("updater.pipeline.check_git_status", return_value=(0, [])),
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
            patch("updater.pipeline.update_git_branch", return_value=True),
            patch("updater.pipeline.update_versions", return_value=True),
            patch("updater.pipeline.apply_gomod_excludes_and_replaces", return_value=False),
            patch("updater.pipeline.update_go_dependencies", return_value=False),
            patch(
                "updater.pipeline.check_git_status",
                side_effect=[(2, ["go.mod", "go.sum"]), (2, ["go.mod", "go.sum"])],
            ),
            patch("updater.pipeline.run_go_precommit"),
            patch(
                "updater.pipeline.analyze_changes_with_claude",
                new_callable=AsyncMock,
                return_value=analysis,
            ),
            patch("updater.pipeline.update_changelog_with_suggestions", return_value="v1.0.1"),
            patch("updater.pipeline.git_commit"),
            patch("updater.pipeline.git_tag_from_changelog"),
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
            patch("updater.pipeline.update_git_branch", return_value=True),
            patch("updater.pipeline.update_versions", return_value=True),
            patch("updater.pipeline.apply_gomod_excludes_and_replaces", return_value=False),
            patch("updater.pipeline.update_go_dependencies", return_value=False),
            patch(
                "updater.pipeline.check_git_status",
                side_effect=[(2, ["go.mod", "go.sum"]), (2, ["go.mod", "go.sum"])],
            ),
            patch("updater.pipeline.run_go_precommit"),
            patch(
                "updater.pipeline.analyze_changes_with_claude",
                new_callable=AsyncMock,
                return_value=analysis,
            ),
            patch("updater.pipeline.git_commit"),
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
            patch("updater.pipeline.update_git_branch", return_value=True),
            patch("updater.pipeline.update_versions", return_value=False),
            patch("updater.pipeline.apply_gomod_excludes_and_replaces", return_value=False),
            patch("updater.pipeline.update_go_dependencies", return_value=False),
            patch(
                "updater.pipeline.check_git_status",
                side_effect=[(1, [".gitignore"]), (1, [".gitignore"])],
            ),
            patch("updater.pipeline.run_go_precommit"),
            patch(
                "updater.pipeline.analyze_changes_with_claude",
                new_callable=AsyncMock,
                return_value=analysis,
            ),
            patch("updater.pipeline.git_commit"),
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
            patch("updater.pipeline.update_git_branch", return_value=True),
            patch("updater.pipeline.update_versions", return_value=True),
            patch("updater.pipeline.apply_gomod_excludes_and_replaces", return_value=False),
            patch("updater.pipeline.update_go_dependencies", return_value=False),
            patch(
                "updater.pipeline.check_git_status",
                side_effect=[(2, ["go.mod", "go.sum"]), (2, ["go.mod", "go.sum"])],
            ),
            patch("updater.pipeline.run_go_precommit"),
            patch(
                "updater.pipeline.analyze_changes_with_claude",
                new_callable=AsyncMock,
                return_value=analysis,
            ),
            patch("updater.pipeline.update_changelog_with_suggestions", return_value="v1.0.1"),
            patch("updater.pipeline.prompt_yes_no", return_value=True),
            patch("updater.pipeline.git_commit"),
            patch("updater.pipeline.git_tag_from_changelog"),
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
            patch("updater.pipeline.update_git_branch", return_value=True),
            patch("updater.pipeline.update_versions", return_value=True),
            patch("updater.pipeline.apply_gomod_excludes_and_replaces", return_value=False),
            patch("updater.pipeline.update_go_dependencies", return_value=False),
            patch(
                "updater.pipeline.check_git_status",
                side_effect=[(2, ["go.mod", "go.sum"]), (2, ["go.mod", "go.sum"])],
            ),
            patch("updater.pipeline.run_go_precommit"),
            patch(
                "updater.pipeline.analyze_changes_with_claude",
                new_callable=AsyncMock,
                return_value=analysis,
            ),
            patch("updater.pipeline.update_changelog_with_suggestions", return_value="v1.0.1"),
            patch("updater.pipeline.prompt_yes_no", return_value=False),
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
            patch("updater.pipeline.update_git_branch", return_value=True),
            patch("updater.pipeline.update_versions", return_value=True),
            patch("updater.pipeline.apply_gomod_excludes_and_replaces", return_value=False),
            patch("updater.pipeline.update_go_dependencies", return_value=False),
            # First check shows changes, precommit runs, second check shows no changes
            patch(
                "updater.pipeline.check_git_status",
                side_effect=[(2, ["go.mod", "go.sum"]), (0, [])],
            ),
            patch("updater.pipeline.run_go_precommit"),
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

    @pytest.mark.asyncio
    async def test_yes_mode_auto_skip_after_max_retries(self, mock_module_path):
        """Test YES_MODE auto-skips after max_retries failures."""
        config.YES_MODE = True
        try:
            with (
                patch(
                    "updater.cli.process_single_go_module",
                    new_callable=AsyncMock,
                    return_value=(False, "failed"),
                ),
                patch("updater.cli.play_error_sound"),
                patch("builtins.print"),
            ):
                success, status = await process_module_with_retry(mock_module_path, max_retries=3)
        finally:
            config.YES_MODE = False

        assert success is False
        assert status == "skipped"

    @pytest.mark.asyncio
    async def test_yes_mode_succeeds_before_max_retries(self, mock_module_path):
        """Test YES_MODE succeeds on retry before hitting limit."""
        config.YES_MODE = True
        try:
            with (
                patch(
                    "updater.cli.process_single_go_module",
                    new_callable=AsyncMock,
                    side_effect=[(False, "failed"), (True, "updated")],
                ),
                patch("updater.cli.play_error_sound"),
                patch("builtins.print"),
            ):
                success, status = await process_module_with_retry(mock_module_path, max_retries=3)
        finally:
            config.YES_MODE = False

        assert success is True
        assert status == "updated"

    @pytest.mark.asyncio
    async def test_interactive_mode_prompts_past_max_retries(self, mock_module_path):
        """Test interactive mode prompts regardless of attempt count (no auto-skip)."""
        config.YES_MODE = False
        with (
            patch(
                "updater.cli.process_single_go_module",
                new_callable=AsyncMock,
                side_effect=[
                    (False, "failed"),
                    (False, "failed"),
                    (False, "failed"),
                    (False, "failed"),
                ],
            ),
            patch(
                "updater.cli.prompt_skip_or_retry",
                side_effect=["retry", "retry", "retry", "skip"],
            ),
            patch("updater.cli.play_error_sound"),
            patch("builtins.print"),
        ):
            success, status = await process_module_with_retry(mock_module_path, max_retries=3)

        assert success is False
        assert status == "skipped"


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
    async def test_log_file_created_before_auth(self, mock_module_path, reset_config):
        """Test that setup_module_logging is called before verify_claude_auth."""
        call_order = []

        def mock_setup_logging(path):
            call_order.append("setup_logging")
            return None

        async def mock_auth():
            call_order.append("verify_auth")
            return (True, "")

        with (
            patch("sys.argv", ["update-deps", str(mock_module_path)]),
            patch("updater.cli.setup_module_logging", side_effect=mock_setup_logging),
            patch("updater.cli.close_module_logging"),
            patch("updater.cli.verify_claude_auth", side_effect=mock_auth),
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
            await main_async()

        assert "setup_logging" in call_order
        assert "verify_auth" in call_order
        assert call_order.index("setup_logging") < call_order.index("verify_auth")

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


class TestProcessSinglePythonModule:
    """Tests for process_single_python_module function."""

    @pytest.mark.asyncio
    async def test_no_git_repo(self, tmp_path, reset_config):
        """Test process_single_python_module fails when no git repo found."""
        module_path = tmp_path / "pymod"
        module_path.mkdir()

        with (
            patch("updater.cli.find_git_repo", return_value=None),
            patch("updater.cli.setup_module_logging", return_value=None),
            patch("updater.cli.ensure_gitignore_entry"),
            patch("updater.cli.close_module_logging"),
            patch("updater.cli.cleanup_old_logs"),
        ):
            success, status = await process_single_python_module(module_path)

        assert success is False
        assert status == "failed"

    @pytest.mark.asyncio
    async def test_up_to_date(self, tmp_path, reset_config):
        """Test process_single_python_module returns up-to-date when pipeline signals so."""
        from updater.pipeline import StepResult, StepStatus

        module_path = tmp_path / "pymod"
        module_path.mkdir()

        with (
            patch("updater.cli.find_git_repo", return_value=module_path),
            patch("updater.cli.setup_module_logging", return_value=None),
            patch("updater.cli.ensure_gitignore_entry"),
            patch(
                "updater.pipeline.Pipeline.run",
                new_callable=AsyncMock,
                return_value=StepResult(StepStatus.UP_TO_DATE),
            ),
            patch("updater.cli.close_module_logging"),
            patch("updater.cli.cleanup_old_logs"),
        ):
            success, status = await process_single_python_module(module_path)

        assert success is True
        assert status == "up-to-date"

    @pytest.mark.asyncio
    async def test_updated(self, tmp_path, reset_config):
        """Test process_single_python_module returns updated on success."""
        from updater.pipeline import StepResult, StepStatus

        module_path = tmp_path / "pymod"
        module_path.mkdir()

        with (
            patch("updater.cli.find_git_repo", return_value=module_path),
            patch("updater.cli.setup_module_logging", return_value=None),
            patch("updater.cli.ensure_gitignore_entry"),
            patch(
                "updater.pipeline.Pipeline.run",
                new_callable=AsyncMock,
                return_value=StepResult(StepStatus.SUCCESS),
            ),
            patch("updater.cli.close_module_logging"),
            patch("updater.cli.cleanup_old_logs"),
        ):
            success, status = await process_single_python_module(module_path)

        assert success is True
        assert status == "updated"

    @pytest.mark.asyncio
    async def test_skipped(self, tmp_path, reset_config):
        """Test process_single_python_module returns skipped when pipeline skips."""
        from updater.pipeline import StepResult, StepStatus

        module_path = tmp_path / "pymod"
        module_path.mkdir()

        with (
            patch("updater.cli.find_git_repo", return_value=module_path),
            patch("updater.cli.setup_module_logging", return_value=None),
            patch("updater.cli.ensure_gitignore_entry"),
            patch(
                "updater.pipeline.Pipeline.run",
                new_callable=AsyncMock,
                return_value=StepResult(StepStatus.SKIP),
            ),
            patch("updater.cli.close_module_logging"),
            patch("updater.cli.cleanup_old_logs"),
        ):
            success, status = await process_single_python_module(module_path)

        assert success is True
        assert status == "skipped"

    @pytest.mark.asyncio
    async def test_exception_handling(self, tmp_path, reset_config):
        """Test exception handling returns failed."""
        module_path = tmp_path / "pymod"
        module_path.mkdir()

        with (
            patch("updater.cli.find_git_repo", side_effect=RuntimeError("Test error")),
            patch("updater.cli.setup_module_logging", return_value=None),
            patch("updater.cli.close_module_logging"),
            patch("updater.cli.cleanup_old_logs"),
        ):
            success, status = await process_single_python_module(module_path)

        assert success is False
        assert status == "failed"


class TestProcessModuleWithRetryDocker:
    """Tests for docker project_type in process_module_with_retry."""

    @pytest.mark.asyncio
    async def test_docker_up_to_date(self, tmp_path):
        """Test docker project_type returns up-to-date when pipeline signals so."""
        from updater.pipeline import StepResult, StepStatus

        module_path = tmp_path / "docker-proj"
        module_path.mkdir()

        with (
            patch(
                "updater.pipeline.Pipeline.run",
                new_callable=AsyncMock,
                return_value=StepResult(StepStatus.UP_TO_DATE),
            ),
            patch("builtins.print"),
        ):
            success, status = await process_module_with_retry(module_path, project_type="docker")

        assert success is True
        assert status == "up-to-date"

    @pytest.mark.asyncio
    async def test_docker_updated(self, tmp_path):
        """Test docker project_type returns updated on success."""
        from updater.pipeline import StepResult, StepStatus

        module_path = tmp_path / "docker-proj"
        module_path.mkdir()

        with (
            patch(
                "updater.pipeline.Pipeline.run",
                new_callable=AsyncMock,
                return_value=StepResult(StepStatus.SUCCESS),
            ),
            patch("builtins.print"),
        ):
            success, status = await process_module_with_retry(module_path, project_type="docker")

        assert success is True
        assert status == "updated"


class TestMainAsyncAdditional:
    """Additional tests for main_async covering previously uncovered paths."""

    @pytest.mark.asyncio
    async def test_auth_failure(self, tmp_path, reset_config):
        """Test main_async returns 1 when Claude auth fails."""
        with (
            patch("sys.argv", ["update-deps", str(tmp_path)]),
            patch(
                "updater.cli.verify_claude_auth",
                new_callable=AsyncMock,
                return_value=(False, "Auth failed: no credentials"),
            ),
            patch("updater.cli.setup_module_logging", return_value=None),
            patch("updater.cli.close_module_logging"),
            patch("updater.cli.play_completion_sound"),
            patch("builtins.print"),
        ):
            exit_code = await main_async()

        assert exit_code == 1

    @pytest.mark.asyncio
    async def test_python_module_discovery(self, tmp_path, reset_config):
        """Test Python module (pyproject.toml + uv.lock) is discovered and processed."""
        mod = tmp_path / "pymod"
        mod.mkdir()
        (mod / "pyproject.toml").write_text("[project]\nname='test'\n")
        (mod / "uv.lock").write_text("")

        with (
            patch("sys.argv", ["update-deps", str(mod)]),
            patch(
                "updater.cli.verify_claude_auth",
                new_callable=AsyncMock,
                return_value=(True, None),
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
    async def test_docker_project_discovery(self, tmp_path, reset_config):
        """Test Docker project (Dockerfile) is discovered and processed."""
        mod = tmp_path / "docker-proj"
        mod.mkdir()
        (mod / "Dockerfile").write_text("FROM ubuntu:22.04\n")

        with (
            patch("sys.argv", ["update-deps", str(mod)]),
            patch(
                "updater.cli.verify_claude_auth",
                new_callable=AsyncMock,
                return_value=(True, None),
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
    async def test_skip_git_update_flag(self, mock_module_path, reset_config):
        """Test --skip-git-update flag bypasses git update step."""
        with (
            patch("sys.argv", ["update-deps", str(mock_module_path), "--skip-git-update"]),
            patch(
                "updater.cli.verify_claude_auth",
                new_callable=AsyncMock,
                return_value=(True, None),
            ),
            patch("updater.cli.find_git_repo", return_value=mock_module_path.parent),
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
    async def test_git_status_error(self, mock_module_path, reset_config):
        """Test main_async returns 1 when check_git_status returns -1."""
        with (
            patch("sys.argv", ["update-deps", str(mock_module_path)]),
            patch(
                "updater.cli.verify_claude_auth",
                new_callable=AsyncMock,
                return_value=(True, None),
            ),
            patch("updater.cli.find_git_repo", return_value=mock_module_path.parent),
            patch("updater.cli.update_git_branch", return_value=True),
            patch("updater.cli.check_git_status", return_value=(-1, [])),
            patch("updater.cli.play_completion_sound"),
            patch("builtins.print"),
        ):
            exit_code = await main_async()

        assert exit_code == 1

    @pytest.mark.asyncio
    async def test_docker_single_module_lang_label(self, tmp_path, reset_config):
        """Test Docker lang label when processing a single docker module."""
        mod = tmp_path / "docker-app"
        mod.mkdir()
        (mod / "Dockerfile").write_text("FROM ubuntu:22.04\n")

        printed = []

        with (
            patch("sys.argv", ["update-deps", str(mod)]),
            patch(
                "updater.cli.verify_claude_auth",
                new_callable=AsyncMock,
                return_value=(True, None),
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
            patch("builtins.print", side_effect=lambda *a, **kw: printed.append(str(a))),
        ):
            exit_code = await main_async()

        assert exit_code == 0
        assert any("Docker" in line for line in printed)

    @pytest.mark.asyncio
    async def test_multi_module_summary_mixed_results(self, tmp_path, reset_config):
        """Test multi-module summary correctly categorizes results."""
        mod1 = tmp_path / "mod1"
        mod1.mkdir()
        (mod1 / "go.mod").write_text("module mod1\n")

        mod2 = tmp_path / "mod2"
        mod2.mkdir()
        (mod2 / "go.mod").write_text("module mod2\n")

        mod3 = tmp_path / "mod3"
        mod3.mkdir()
        (mod3 / "go.mod").write_text("module mod3\n")

        mod4 = tmp_path / "mod4"
        mod4.mkdir()
        (mod4 / "go.mod").write_text("module mod4\n")

        with (
            patch("sys.argv", ["update-deps", str(mod1), str(mod2), str(mod3), str(mod4)]),
            patch(
                "updater.cli.verify_claude_auth",
                new_callable=AsyncMock,
                return_value=(True, None),
            ),
            patch("updater.cli.find_git_repo", return_value=tmp_path),
            patch("updater.cli.update_git_branch", return_value=True),
            patch("updater.cli.check_git_status", return_value=(0, [])),
            patch(
                "updater.cli.process_module_with_retry",
                new_callable=AsyncMock,
                side_effect=[
                    (True, "updated"),
                    (True, "up-to-date"),
                    (False, "skipped"),
                    (False, "failed"),
                ],
            ),
            patch("updater.cli.play_completion_sound"),
            patch("builtins.print"),
        ):
            exit_code = await main_async()

        # Multi-module always returns 0 regardless of individual results
        assert exit_code == 0

    @pytest.mark.asyncio
    async def test_recursive_discovery_no_modules(self, tmp_path, reset_config):
        """Test main_async returns 1 when recursive discovery finds nothing."""
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()

        with (
            patch("sys.argv", ["update-deps", str(empty_dir)]),
            patch(
                "updater.cli.verify_claude_auth",
                new_callable=AsyncMock,
                return_value=(True, None),
            ),
            patch("updater.cli.play_completion_sound"),
            patch("builtins.print"),
        ):
            exit_code = await main_async()

        assert exit_code == 1


class TestProcessReleaseModule:
    """Tests for process_release_module function."""

    @pytest.mark.asyncio
    async def test_no_git_repo(self, tmp_path, reset_config):
        """Test process_release_module fails when no git repo found."""
        module_path = tmp_path / "mod"
        module_path.mkdir()

        with (
            patch("updater.cli.find_git_repo", return_value=None),
            patch("updater.cli.setup_module_logging", return_value=None),
            patch("updater.cli.ensure_gitignore_entry"),
            patch("updater.cli.close_module_logging"),
            patch("updater.cli.cleanup_old_logs"),
        ):
            success, status = await process_release_module(module_path)

        assert success is False
        assert status == "failed"

    @pytest.mark.asyncio
    async def test_success_released(self, tmp_path, reset_config):
        """Test process_release_module returns released on success."""
        from updater.pipeline import StepResult, StepStatus

        module_path = tmp_path / "mod"
        module_path.mkdir()

        with (
            patch("updater.cli.find_git_repo", return_value=module_path),
            patch("updater.cli.setup_module_logging", return_value=None),
            patch("updater.cli.ensure_gitignore_entry"),
            patch(
                "updater.pipeline.Pipeline.run",
                new_callable=AsyncMock,
                return_value=StepResult(StepStatus.SUCCESS),
            ),
            patch("updater.cli.close_module_logging"),
            patch("updater.cli.cleanup_old_logs"),
            patch("builtins.print"),
        ):
            success, status = await process_release_module(module_path)

        assert success is True
        assert status == "released"

    @pytest.mark.asyncio
    async def test_nothing_to_release(self, tmp_path, reset_config):
        """Test process_release_module returns nothing-to-release when up-to-date."""
        from updater.pipeline import StepResult, StepStatus

        module_path = tmp_path / "mod"
        module_path.mkdir()

        with (
            patch("updater.cli.find_git_repo", return_value=module_path),
            patch("updater.cli.setup_module_logging", return_value=None),
            patch("updater.cli.ensure_gitignore_entry"),
            patch(
                "updater.pipeline.Pipeline.run",
                new_callable=AsyncMock,
                return_value=StepResult(StepStatus.UP_TO_DATE),
            ),
            patch("updater.cli.close_module_logging"),
            patch("updater.cli.cleanup_old_logs"),
        ):
            success, status = await process_release_module(module_path)

        assert success is True
        assert status == "nothing-to-release"

    @pytest.mark.asyncio
    async def test_skipped(self, tmp_path, reset_config):
        """Test process_release_module returns skipped when pipeline skips."""
        from updater.pipeline import StepResult, StepStatus

        module_path = tmp_path / "mod"
        module_path.mkdir()

        with (
            patch("updater.cli.find_git_repo", return_value=module_path),
            patch("updater.cli.setup_module_logging", return_value=None),
            patch("updater.cli.ensure_gitignore_entry"),
            patch(
                "updater.pipeline.Pipeline.run",
                new_callable=AsyncMock,
                return_value=StepResult(StepStatus.SKIP),
            ),
            patch("updater.cli.close_module_logging"),
            patch("updater.cli.cleanup_old_logs"),
        ):
            success, status = await process_release_module(module_path)

        assert success is True
        assert status == "skipped"

    @pytest.mark.asyncio
    async def test_exception_handling(self, tmp_path, reset_config):
        """Test exception handling returns failed."""
        module_path = tmp_path / "mod"
        module_path.mkdir()

        with (
            patch("updater.cli.find_git_repo", side_effect=RuntimeError("Test error")),
            patch("updater.cli.setup_module_logging", return_value=None),
            patch("updater.cli.close_module_logging"),
            patch("updater.cli.cleanup_old_logs"),
        ):
            success, status = await process_release_module(module_path)

        assert success is False
        assert status == "failed"


class TestProcessReleaseWithRetry:
    """Tests for process_release_with_retry function."""

    @pytest.mark.asyncio
    async def test_success_first_try(self, tmp_path):
        """Test successful release on first attempt."""
        module_path = tmp_path / "mod"
        module_path.mkdir()

        with patch(
            "updater.cli.process_release_module",
            new_callable=AsyncMock,
            return_value=(True, "released"),
        ):
            success, status = await process_release_with_retry(module_path)

        assert success is True
        assert status == "released"

    @pytest.mark.asyncio
    async def test_skip_after_failure(self, tmp_path):
        """Test user skips after release failure."""
        module_path = tmp_path / "mod"
        module_path.mkdir()

        with (
            patch(
                "updater.cli.process_release_module",
                new_callable=AsyncMock,
                return_value=(False, "failed"),
            ),
            patch("updater.cli.prompt_skip_or_retry", return_value="skip"),
            patch("updater.cli.play_error_sound"),
            patch("builtins.print"),
        ):
            success, status = await process_release_with_retry(module_path)

        assert success is False
        assert status == "skipped"

    @pytest.mark.asyncio
    async def test_retry_then_success(self, tmp_path):
        """Test retry after failure then success."""
        module_path = tmp_path / "mod"
        module_path.mkdir()

        with (
            patch(
                "updater.cli.process_release_module",
                new_callable=AsyncMock,
                side_effect=[(False, "failed"), (True, "released")],
            ),
            patch("updater.cli.prompt_skip_or_retry", return_value="retry"),
            patch("updater.cli.play_error_sound"),
            patch("builtins.print"),
        ):
            success, status = await process_release_with_retry(module_path)

        assert success is True
        assert status == "released"

    @pytest.mark.asyncio
    async def test_yes_mode_auto_skip_after_max_retries(self, tmp_path):
        """Test YES_MODE auto-skips after max_retries in release workflow."""
        module_path = tmp_path / "mod"
        module_path.mkdir()

        config.YES_MODE = True
        try:
            with (
                patch(
                    "updater.cli.process_release_module",
                    new_callable=AsyncMock,
                    return_value=(False, "failed"),
                ),
                patch("updater.cli.play_error_sound"),
                patch("builtins.print"),
            ):
                success, status = await process_release_with_retry(module_path, max_retries=3)
        finally:
            config.YES_MODE = False

        assert success is False
        assert status == "skipped"


class TestMainReleaseAsync:
    """Tests for main_release_async function."""

    @pytest.mark.asyncio
    async def test_auth_failure(self, tmp_path, reset_config):
        """Test main_release_async returns 1 when Claude auth fails."""
        from updater.cli import main_release_async

        with (
            patch("sys.argv", ["update-release", str(tmp_path)]),
            patch(
                "updater.cli.verify_claude_auth",
                new_callable=AsyncMock,
                return_value=(False, "Auth error"),
            ),
            patch("updater.cli.play_completion_sound"),
            patch("builtins.print"),
        ):
            exit_code = await main_release_async()

        assert exit_code == 1

    @pytest.mark.asyncio
    async def test_nonexistent_path(self, tmp_path, reset_config):
        """Test main_release_async returns 1 for nonexistent path."""
        from updater.cli import main_release_async

        nonexistent = tmp_path / "does-not-exist"

        with (
            patch("sys.argv", ["update-release", str(nonexistent)]),
            patch(
                "updater.cli.verify_claude_auth",
                new_callable=AsyncMock,
                return_value=(True, None),
            ),
            patch("updater.cli.play_completion_sound"),
            patch("builtins.print"),
        ):
            exit_code = await main_release_async()

        assert exit_code == 1

    @pytest.mark.asyncio
    async def test_no_modules_with_changelog(self, tmp_path, reset_config):
        """Test main_release_async returns 1 when no modules have CHANGELOG.md."""
        from updater.cli import main_release_async

        with (
            patch("sys.argv", ["update-release", str(tmp_path)]),
            patch(
                "updater.cli.verify_claude_auth",
                new_callable=AsyncMock,
                return_value=(True, None),
            ),
            patch("updater.cli.play_completion_sound"),
            patch("builtins.print"),
        ):
            exit_code = await main_release_async()

        assert exit_code == 1

    @pytest.mark.asyncio
    async def test_single_module_released(self, tmp_path, reset_config):
        """Test main_release_async processes a module with CHANGELOG.md."""
        from updater.cli import main_release_async

        (tmp_path / "CHANGELOG.md").write_text(
            "# Changelog\n\n## Unreleased\n\n- feat: something\n"
        )

        with (
            patch("sys.argv", ["update-release", str(tmp_path)]),
            patch(
                "updater.cli.verify_claude_auth",
                new_callable=AsyncMock,
                return_value=(True, None),
            ),
            patch(
                "updater.cli.process_release_with_retry",
                new_callable=AsyncMock,
                return_value=(True, "released"),
            ),
            patch("updater.cli.play_completion_sound"),
            patch("builtins.print"),
        ):
            exit_code = await main_release_async()

        assert exit_code == 0

    @pytest.mark.asyncio
    async def test_multi_module_summary(self, tmp_path, reset_config):
        """Test main_release_async shows summary for multiple modules."""
        from updater.cli import main_release_async

        mod1 = tmp_path / "mod1"
        mod1.mkdir()
        (mod1 / "CHANGELOG.md").write_text("# Changelog\n\n## Unreleased\n\n- feat: a\n")
        (mod1 / "go.mod").write_text("module mod1\n")

        mod2 = tmp_path / "mod2"
        mod2.mkdir()
        (mod2 / "CHANGELOG.md").write_text("# Changelog\n\n## Unreleased\n\n- feat: b\n")
        (mod2 / "go.mod").write_text("module mod2\n")

        with (
            patch("sys.argv", ["update-release", str(mod1), str(mod2)]),
            patch(
                "updater.cli.verify_claude_auth",
                new_callable=AsyncMock,
                return_value=(True, None),
            ),
            patch(
                "updater.cli.process_release_with_retry",
                new_callable=AsyncMock,
                side_effect=[(True, "released"), (True, "nothing-to-release")],
            ),
            patch("updater.cli.play_completion_sound"),
            patch("builtins.print"),
        ):
            exit_code = await main_release_async()

        assert exit_code == 0


class TestMainGoAsync:
    """Tests for main_go_async function."""

    @pytest.mark.asyncio
    async def test_nonexistent_path(self, tmp_path):
        """Test main_go_async returns 1 for nonexistent path."""
        from updater.cli import main_go_async

        nonexistent = tmp_path / "does-not-exist"

        with (
            patch("sys.argv", ["update-go", str(nonexistent)]),
            patch("builtins.print"),
        ):
            exit_code = await main_go_async()

        assert exit_code == 1

    @pytest.mark.asyncio
    async def test_no_modules_found(self, tmp_path):
        """Test main_go_async returns 1 when no Go modules found."""
        from updater.cli import main_go_async

        with (
            patch("sys.argv", ["update-go", str(tmp_path)]),
            patch("builtins.print"),
        ):
            exit_code = await main_go_async()

        assert exit_code == 1

    @pytest.mark.asyncio
    async def test_single_module_success(self, mock_module_path):
        """Test main_go_async processes a single Go module successfully."""
        from updater.cli import main_go_async

        with (
            patch("sys.argv", ["update-go", str(mock_module_path)]),
            patch(
                "updater.cli.process_module_with_retry",
                new_callable=AsyncMock,
                return_value=(True, "updated"),
            ),
            patch("updater.cli.play_completion_sound"),
            patch("builtins.print"),
        ):
            exit_code = await main_go_async()

        assert exit_code == 0

    @pytest.mark.asyncio
    async def test_single_module_failure(self, mock_module_path):
        """Test main_go_async returns 1 on module failure."""
        from updater.cli import main_go_async

        with (
            patch("sys.argv", ["update-go", str(mock_module_path)]),
            patch(
                "updater.cli.process_module_with_retry",
                new_callable=AsyncMock,
                return_value=(False, "failed"),
            ),
            patch("updater.cli.play_completion_sound"),
            patch("builtins.print"),
        ):
            exit_code = await main_go_async()

        assert exit_code == 1

    @pytest.mark.asyncio
    async def test_multi_module(self, tmp_path):
        """Test main_go_async processes multiple modules with progress display."""
        from updater.cli import main_go_async

        mod1 = tmp_path / "mod1"
        mod1.mkdir()
        (mod1 / "go.mod").write_text("module mod1\n")

        mod2 = tmp_path / "mod2"
        mod2.mkdir()
        (mod2 / "go.mod").write_text("module mod2\n")

        with (
            patch("sys.argv", ["update-go", str(mod1), str(mod2)]),
            patch(
                "updater.cli.process_module_with_retry",
                new_callable=AsyncMock,
                return_value=(True, "updated"),
            ),
            patch("updater.cli.play_completion_sound"),
            patch("builtins.print"),
        ):
            exit_code = await main_go_async()

        assert exit_code == 0


class TestMainGoOnlyAsync:
    """Tests for main_go_only_async function."""

    @pytest.mark.asyncio
    async def test_no_modules_found(self, tmp_path):
        """Test main_go_only_async returns 1 when no Go modules found."""
        from updater.cli import main_go_only_async

        with (
            patch("sys.argv", ["update-go-only", str(tmp_path)]),
            patch("builtins.print"),
        ):
            exit_code = await main_go_only_async()

        assert exit_code == 1

    @pytest.mark.asyncio
    async def test_single_module_success(self, mock_module_path):
        """Test main_go_only_async processes a module with update_deps=False."""
        from updater.cli import main_go_only_async

        with (
            patch("sys.argv", ["update-go-only", str(mock_module_path)]),
            patch(
                "updater.cli.process_module_with_retry",
                new_callable=AsyncMock,
                return_value=(True, "updated"),
            ),
            patch("updater.cli.play_completion_sound"),
            patch("builtins.print"),
        ):
            exit_code = await main_go_only_async()

        assert exit_code == 0

    @pytest.mark.asyncio
    async def test_nonexistent_path(self, tmp_path):
        """Test main_go_only_async returns 1 for nonexistent path."""
        from updater.cli import main_go_only_async

        nonexistent = tmp_path / "does-not-exist"

        with (
            patch("sys.argv", ["update-go-only", str(nonexistent)]),
            patch("builtins.print"),
        ):
            exit_code = await main_go_only_async()

        assert exit_code == 1


class TestMainGoWithDepsAsync:
    """Tests for main_go_with_deps_async function."""

    @pytest.mark.asyncio
    async def test_no_modules_found(self, tmp_path):
        """Test main_go_with_deps_async returns 1 when no Go modules found."""
        from updater.cli import main_go_with_deps_async

        with (
            patch("sys.argv", ["update-go-with-deps", str(tmp_path)]),
            patch("builtins.print"),
        ):
            exit_code = await main_go_with_deps_async()

        assert exit_code == 1

    @pytest.mark.asyncio
    async def test_single_module_success(self, mock_module_path):
        """Test main_go_with_deps_async processes a module successfully."""
        from updater.cli import main_go_with_deps_async

        with (
            patch("sys.argv", ["update-go-with-deps", str(mock_module_path)]),
            patch(
                "updater.cli.process_module_with_retry",
                new_callable=AsyncMock,
                return_value=(True, "updated"),
            ),
            patch("updater.cli.play_completion_sound"),
            patch("builtins.print"),
        ):
            exit_code = await main_go_with_deps_async()

        assert exit_code == 0


class TestMainPythonAsync:
    """Tests for main_python_async function."""

    @pytest.mark.asyncio
    async def test_no_modules_found(self, tmp_path):
        """Test main_python_async returns 1 when no Python modules found."""
        from updater.cli import main_python_async

        with (
            patch("sys.argv", ["update-python", str(tmp_path)]),
            patch("builtins.print"),
        ):
            exit_code = await main_python_async()

        assert exit_code == 1

    @pytest.mark.asyncio
    async def test_nonexistent_path(self, tmp_path):
        """Test main_python_async returns 1 for nonexistent path."""
        from updater.cli import main_python_async

        nonexistent = tmp_path / "does-not-exist"

        with (
            patch("sys.argv", ["update-python", str(nonexistent)]),
            patch("builtins.print"),
        ):
            exit_code = await main_python_async()

        assert exit_code == 1

    @pytest.mark.asyncio
    async def test_single_module_success(self, tmp_path):
        """Test main_python_async processes a Python module successfully."""
        from updater.cli import main_python_async

        mod = tmp_path / "pymod"
        mod.mkdir()
        (mod / "pyproject.toml").write_text("[project]\n")
        (mod / "uv.lock").write_text("")

        with (
            patch("sys.argv", ["update-python", str(mod)]),
            patch(
                "updater.cli.process_module_with_retry",
                new_callable=AsyncMock,
                return_value=(True, "updated"),
            ),
            patch("updater.cli.play_completion_sound"),
            patch("builtins.print"),
        ):
            exit_code = await main_python_async()

        assert exit_code == 0

    @pytest.mark.asyncio
    async def test_single_module_failure(self, tmp_path):
        """Test main_python_async returns 1 on module failure."""
        from updater.cli import main_python_async

        mod = tmp_path / "pymod"
        mod.mkdir()
        (mod / "pyproject.toml").write_text("[project]\n")
        (mod / "uv.lock").write_text("")

        with (
            patch("sys.argv", ["update-python", str(mod)]),
            patch(
                "updater.cli.process_module_with_retry",
                new_callable=AsyncMock,
                return_value=(False, "failed"),
            ),
            patch("updater.cli.play_completion_sound"),
            patch("builtins.print"),
        ):
            exit_code = await main_python_async()

        assert exit_code == 1


class TestMainDockerAsync:
    """Tests for main_docker_async function."""

    @pytest.mark.asyncio
    async def test_nonexistent_path_continues(self, tmp_path):
        """Test main_docker_async continues (not fails) for nonexistent path."""
        from updater.cli import main_docker_async

        nonexistent = tmp_path / "does-not-exist"

        with (
            patch("sys.argv", ["update-docker", str(nonexistent)]),
            patch("builtins.print"),
        ):
            exit_code = await main_docker_async()

        assert exit_code == 0

    @pytest.mark.asyncio
    async def test_with_dockerfile_no_updates(self, tmp_path):
        """Test main_docker_async with a Dockerfile that is up to date."""
        from updater.cli import main_docker_async

        (tmp_path / "Dockerfile").write_text("FROM ubuntu:22.04\n")

        with (
            patch("sys.argv", ["update-docker", str(tmp_path)]),
            patch("updater.cli.update_dockerfile_images", return_value=(False, [])),
            patch("builtins.print"),
        ):
            exit_code = await main_docker_async()

        assert exit_code == 0

    @pytest.mark.asyncio
    async def test_with_dockerfile_updated(self, tmp_path):
        """Test main_docker_async with a Dockerfile that gets updated."""
        from updater.cli import main_docker_async

        (tmp_path / "Dockerfile").write_text("FROM ubuntu:20.04\n")

        with (
            patch("sys.argv", ["update-docker", str(tmp_path)]),
            patch("updater.cli.update_dockerfile_images", return_value=(True, [])),
            patch("builtins.print"),
        ):
            exit_code = await main_docker_async()

        assert exit_code == 0

    @pytest.mark.asyncio
    async def test_search_subdirectories(self, tmp_path):
        """Test main_docker_async searches subdirectories for Dockerfiles."""
        from updater.cli import main_docker_async

        subdir = tmp_path / "service"
        subdir.mkdir()
        (subdir / "Dockerfile").write_text("FROM ubuntu:22.04\n")

        with (
            patch("sys.argv", ["update-docker", str(tmp_path)]),
            patch("updater.cli.update_dockerfile_images", return_value=(False, [])),
            patch("builtins.print"),
        ):
            exit_code = await main_docker_async()

        assert exit_code == 0
