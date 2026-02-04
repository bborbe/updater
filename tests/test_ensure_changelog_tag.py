"""Tests for ensure_changelog_tag function."""

from unittest.mock import MagicMock, patch

from updater.git_operations import ensure_changelog_tag


class TestEnsureChangelogTag:
    """Tests for ensure_changelog_tag function."""

    def test_no_changelog_returns_false(self, tmp_path):
        """Test that missing CHANGELOG.md returns False."""
        log_func = MagicMock()
        result = ensure_changelog_tag(tmp_path, log_func=log_func)
        assert result is False

    def test_changelog_without_version_returns_false(self, tmp_path):
        """Test that CHANGELOG without version returns False."""
        changelog = tmp_path / "CHANGELOG.md"
        changelog.write_text("# Changelog\n\nNo version here\n")

        log_func = MagicMock()
        result = ensure_changelog_tag(tmp_path, log_func=log_func)
        assert result is False

    def test_tag_already_exists_returns_false(self, tmp_path):
        """Test that existing tag returns False."""
        changelog = tmp_path / "CHANGELOG.md"
        changelog.write_text("# Changelog\n\n## v0.1.0\n\n- Initial release\n")

        log_func = MagicMock()

        with patch("subprocess.run") as mock_run:
            # Simulate tag already exists
            mock_run.return_value = MagicMock(stdout="v0.1.0\n", returncode=0)
            result = ensure_changelog_tag(tmp_path, log_func=log_func)

        assert result is False

    def test_creates_missing_tag(self, tmp_path):
        """Test that missing tag is created."""
        changelog = tmp_path / "CHANGELOG.md"
        changelog.write_text("# Changelog\n\n## v0.1.0\n\n- Initial release\n")

        log_func = MagicMock()

        with (
            patch("subprocess.run") as mock_subprocess,
            patch("updater.log_manager.run_command") as mock_run_cmd,
        ):
            # Simulate tag does not exist
            mock_subprocess.return_value = MagicMock(stdout="", returncode=0)
            result = ensure_changelog_tag(tmp_path, log_func=log_func)

        assert result is True
        # Verify git tag command was called
        mock_run_cmd.assert_called_once()
        call_args = str(mock_run_cmd.call_args)
        assert "git tag -a v0.1.0" in call_args

    def test_extracts_correct_version(self, tmp_path):
        """Test that correct version is extracted from CHANGELOG."""
        changelog = tmp_path / "CHANGELOG.md"
        changelog.write_text(
            """# Changelog

## v2.3.4

- Latest changes

## v2.3.3

- Previous changes
"""
        )

        log_func = MagicMock()

        with (
            patch("subprocess.run") as mock_subprocess,
            patch("updater.log_manager.run_command") as mock_run_cmd,
        ):
            mock_subprocess.return_value = MagicMock(stdout="", returncode=0)
            result = ensure_changelog_tag(tmp_path, log_func=log_func)

        assert result is True
        # Should use v2.3.4 (first/latest version)
        call_args = str(mock_run_cmd.call_args)
        assert "v2.3.4" in call_args
        assert "v2.3.3" not in call_args

    def test_logs_tag_creation(self, tmp_path):
        """Test that tag creation is logged."""
        changelog = tmp_path / "CHANGELOG.md"
        changelog.write_text("# Changelog\n\n## v1.0.0\n\n- Release\n")

        log_func = MagicMock()

        with (
            patch("subprocess.run") as mock_subprocess,
            patch("updater.log_manager.run_command"),
        ):
            mock_subprocess.return_value = MagicMock(stdout="", returncode=0)
            ensure_changelog_tag(tmp_path, log_func=log_func)

        # Check log messages
        log_calls = [str(c) for c in log_func.call_args_list]
        assert any("v1.0.0" in call for call in log_calls)
