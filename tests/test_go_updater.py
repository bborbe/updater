"""Tests for Go dependency updater."""

from unittest.mock import Mock, patch

import pytest

from updater import config
from updater.go_updater import run_precommit, update_go_dependencies


@pytest.fixture
def reset_config():
    """Reset global config before each test."""
    config.VERBOSE_MODE = False
    config.GO_MAX_ITERATIONS = 5
    yield


@pytest.fixture
def mock_module_path(tmp_path):
    """Create a mock module directory."""
    module_path = tmp_path / "test-module"
    module_path.mkdir()
    (module_path / "go.mod").write_text("module test\n\ngo 1.23\n")
    return module_path


class TestUpdateGoDependencies:
    """Tests for update_go_dependencies function."""

    def test_no_updates_available(self, mock_module_path, reset_config):
        """Test when no dependency updates are available."""
        # Mock run_command to return no outdated modules
        with patch("updater.go_updater.run_command") as mock_run:
            mock_run.return_value = Mock(returncode=0, stdout="", stderr="")

            result = update_go_dependencies(mock_module_path)

        assert result is False
        # Should call go list to check for updates
        mock_run.assert_called_once()

    def test_single_update_available(self, mock_module_path, reset_config):
        """Test updating a single dependency."""
        mock_stdout_check = "github.com/foo/bar"
        mock_stdout_detail = "github.com/foo/bar v1.0.0 [v1.1.0]"

        with patch("updater.go_updater.run_command") as mock_run:
            # First call: list outdated modules
            # Second call: check specific module
            # Third call: go get
            # Fourth call: check for more updates (none)
            # Fifth call: go mod tidy
            # Sixth call: go mod vendor
            mock_run.side_effect = [
                Mock(returncode=0, stdout=mock_stdout_check, stderr=""),  # list outdated
                Mock(returncode=0, stdout=mock_stdout_detail, stderr=""),  # check module
                Mock(returncode=0, stdout="", stderr=""),  # go get
                Mock(returncode=0, stdout="", stderr=""),  # check again (no more updates)
                Mock(returncode=0, stdout="", stderr=""),  # go mod tidy
                Mock(returncode=0, stdout="", stderr=""),  # go mod vendor
            ]

            result = update_go_dependencies(mock_module_path)

        assert result is True
        assert mock_run.call_count == 6

    def test_multiple_updates_single_iteration(self, mock_module_path, reset_config):
        """Test updating multiple dependencies in single iteration."""
        mock_stdout_check = "github.com/foo/bar\ngithub.com/baz/qux"

        with patch("updater.go_updater.run_command") as mock_run:
            mock_run.side_effect = [
                # Iteration 1: list outdated (2 modules)
                Mock(returncode=0, stdout=mock_stdout_check, stderr=""),
                # Check and update module 1
                Mock(returncode=0, stdout="github.com/foo/bar v1.0.0 [v1.1.0]", stderr=""),
                Mock(returncode=0, stdout="", stderr=""),  # go get
                # Check and update module 2
                Mock(returncode=0, stdout="github.com/baz/qux v2.0.0 [v2.1.0]", stderr=""),
                Mock(returncode=0, stdout="", stderr=""),  # go get
                # Iteration 2: check again (no more updates)
                Mock(returncode=0, stdout="", stderr=""),
                # Cleanup
                Mock(returncode=0, stdout="", stderr=""),  # go mod tidy
                Mock(returncode=0, stdout="", stderr=""),  # go mod vendor
            ]

            result = update_go_dependencies(mock_module_path)

        assert result is True

    def test_iterative_updates(self, mock_module_path, reset_config):
        """Test multiple iterations when updates reveal more updates."""
        with patch("updater.go_updater.run_command") as mock_run:
            mock_run.side_effect = [
                # Iteration 1
                Mock(returncode=0, stdout="github.com/foo/bar", stderr=""),
                Mock(returncode=0, stdout="github.com/foo/bar v1.0.0 [v1.1.0]", stderr=""),
                Mock(returncode=0, stdout="", stderr=""),  # go get
                # Iteration 2: new module needs update
                Mock(returncode=0, stdout="github.com/baz/qux", stderr=""),
                Mock(returncode=0, stdout="github.com/baz/qux v2.0.0 [v2.1.0]", stderr=""),
                Mock(returncode=0, stdout="", stderr=""),  # go get
                # Iteration 3: no more updates
                Mock(returncode=0, stdout="", stderr=""),
                # Cleanup
                Mock(returncode=0, stdout="", stderr=""),  # go mod tidy
                Mock(returncode=0, stdout="", stderr=""),  # go mod vendor
            ]

            result = update_go_dependencies(mock_module_path)

        assert result is True

    def test_max_iterations_reached(self, mock_module_path, reset_config):
        """Test that max iterations limit is respected."""
        config.GO_MAX_ITERATIONS = 2

        with patch("updater.go_updater.run_command") as mock_run:
            # Always return an update available
            mock_run.side_effect = [
                # Iteration 1
                Mock(returncode=0, stdout="github.com/foo/bar", stderr=""),
                Mock(returncode=0, stdout="github.com/foo/bar v1.0.0 [v1.1.0]", stderr=""),
                Mock(returncode=0, stdout="", stderr=""),  # go get
                # Iteration 2 (max reached)
                Mock(returncode=0, stdout="github.com/baz/qux", stderr=""),
                Mock(returncode=0, stdout="github.com/baz/qux v2.0.0 [v2.1.0]", stderr=""),
                Mock(returncode=0, stdout="", stderr=""),  # go get
                # Cleanup
                Mock(returncode=0, stdout="", stderr=""),  # go mod tidy
                Mock(returncode=0, stdout="", stderr=""),  # go mod vendor
            ]

            result = update_go_dependencies(mock_module_path)

        assert result is True
        # Should stop after max iterations, then run cleanup
        assert mock_run.call_count == 8

    def test_module_with_no_update_available(self, mock_module_path, reset_config):
        """Test skipping module when no update is actually available."""
        mock_stdout_check = "github.com/foo/bar"

        with patch("updater.go_updater.run_command") as mock_run:
            mock_run.side_effect = [
                # List shows module
                Mock(returncode=0, stdout=mock_stdout_check, stderr=""),
                # But detailed check shows no update (no brackets)
                Mock(returncode=0, stdout="github.com/foo/bar v1.0.0", stderr=""),
                # Check again (no more) - this call doesn't happen because no updates were made
            ]

            result = update_go_dependencies(mock_module_path)

        # No updates were made, so returns False and no cleanup commands
        assert result is False
        assert mock_run.call_count == 2  # Only the first two calls

    def test_verbose_mode_logging(self, mock_module_path, reset_config):
        """Test verbose mode produces console output."""
        config.VERBOSE_MODE = True

        with patch("updater.go_updater.run_command") as mock_run:
            mock_run.return_value = Mock(returncode=0, stdout="", stderr="")

            update_go_dependencies(mock_module_path)

        # Just verify it doesn't crash - actual logging checked by integration tests
        assert mock_run.call_count == 1

    def test_go_mod_tidy_and_vendor_called(self, mock_module_path, reset_config):
        """Test that go mod tidy and vendor are called after updates."""
        with patch("updater.go_updater.run_command") as mock_run:
            mock_run.side_effect = [
                Mock(returncode=0, stdout="github.com/foo/bar", stderr=""),
                Mock(returncode=0, stdout="github.com/foo/bar v1.0.0 [v1.1.0]", stderr=""),
                Mock(returncode=0, stdout="", stderr=""),  # go get
                Mock(returncode=0, stdout="", stderr=""),  # check again
                Mock(returncode=0, stdout="", stderr=""),  # go mod tidy
                Mock(returncode=0, stdout="", stderr=""),  # go mod vendor
            ]

            result = update_go_dependencies(mock_module_path)

        assert result is True

        # Verify the last two calls were tidy and vendor
        calls = [str(call) for call in mock_run.call_args_list]
        assert any("go mod tidy" in str(call) for call in calls)
        assert any("go mod vendor" in str(call) for call in calls)

    def test_command_failure_raises_error(self, mock_module_path, reset_config):
        """Test that command failures raise RuntimeError."""
        with (
            patch("updater.go_updater.run_command") as mock_run,
            pytest.raises(RuntimeError, match="Command failed"),
        ):
            mock_run.side_effect = RuntimeError("Command failed: go list")

            update_go_dependencies(mock_module_path)

    def test_custom_log_function(self, mock_module_path, reset_config):
        """Test using custom log function."""
        custom_log_calls = []

        def custom_log(msg, to_console=False):
            custom_log_calls.append((msg, to_console))

        with patch("updater.go_updater.run_command") as mock_run:
            mock_run.return_value = Mock(returncode=0, stdout="", stderr="")

            update_go_dependencies(mock_module_path, log_func=custom_log)

        # Verify custom log function was called
        assert len(custom_log_calls) > 0
        assert any("Phase 1c" in msg for msg, _ in custom_log_calls)


class TestRunPrecommit:
    """Tests for run_precommit function."""

    def test_successful_precommit(self, mock_module_path, reset_config):
        """Test successful precommit execution."""
        with patch("updater.go_updater.run_command") as mock_run:
            mock_run.return_value = Mock(returncode=0, stdout="All checks passed", stderr="")

            # Should not raise
            run_precommit(mock_module_path)

        mock_run.assert_called_once()
        call_args = mock_run.call_args
        assert "make precommit" in call_args[0][0]

    def test_precommit_with_custom_log_function(self, mock_module_path, reset_config):
        """Test precommit with custom log function."""
        custom_log_calls = []

        def custom_log(msg, to_console=False):
            custom_log_calls.append((msg, to_console))

        with patch("updater.go_updater.run_command") as mock_run:
            mock_run.return_value = Mock(returncode=0, stdout="", stderr="")

            run_precommit(mock_module_path, log_func=custom_log)

        # Verify custom log function was called
        assert len(custom_log_calls) > 0
        assert any("Phase 2" in msg for msg, _ in custom_log_calls)

    def test_precommit_failure_raises_error(self, mock_module_path, reset_config):
        """Test that precommit failure raises RuntimeError."""
        with (
            patch("updater.go_updater.run_command") as mock_run,
            pytest.raises(RuntimeError, match="Command failed"),
        ):
            mock_run.side_effect = RuntimeError("Command failed: make precommit")

            run_precommit(mock_module_path)

    def test_verbose_mode_logging_precommit(self, mock_module_path, reset_config):
        """Test verbose mode in precommit."""
        config.VERBOSE_MODE = True

        with patch("updater.go_updater.run_command") as mock_run:
            mock_run.return_value = Mock(returncode=0, stdout="output", stderr="")

            run_precommit(mock_module_path)

        # Just verify it doesn't crash
        mock_run.assert_called_once()

    def test_precommit_runs_in_correct_directory(self, mock_module_path, reset_config):
        """Test that precommit runs in the module directory."""
        with patch("updater.go_updater.run_command") as mock_run:
            mock_run.return_value = Mock(returncode=0, stdout="", stderr="")

            run_precommit(mock_module_path)

        # Verify cwd parameter was set to module_path
        call_args = mock_run.call_args
        assert call_args[1]["cwd"] == mock_module_path

    def test_precommit_quiet_mode(self, mock_module_path, reset_config):
        """Test that precommit runs in quiet mode by default."""
        with patch("updater.go_updater.run_command") as mock_run:
            mock_run.return_value = Mock(returncode=0, stdout="", stderr="")

            run_precommit(mock_module_path)

        # Verify quiet parameter was set
        call_args = mock_run.call_args
        assert call_args[1]["quiet"] is True
