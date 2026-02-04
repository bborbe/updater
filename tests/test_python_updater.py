"""Tests for Python dependency updater."""

from unittest.mock import MagicMock, patch

from updater.python_updater import run_precommit, update_python_dependencies


class TestUpdatePythonDependencies:
    """Tests for update_python_dependencies function."""

    def test_runs_uv_sync_upgrade(self, tmp_path):
        """Test that uv sync --upgrade is called."""
        # Create a minimal Python project
        (tmp_path / "pyproject.toml").write_text("[project]\nname = 'test'\n")
        (tmp_path / "uv.lock").write_text("# lockfile\n")

        log_func = MagicMock()

        with patch("updater.python_updater.run_command") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            update_python_dependencies(tmp_path, log_func=log_func)

            # Verify uv sync --upgrade was called
            calls = [str(c) for c in mock_run.call_args_list]
            assert any("uv sync --upgrade" in str(c) for c in calls)

    def test_returns_true_when_lockfile_changes(self, tmp_path):
        """Test returns True when uv.lock is modified."""
        (tmp_path / "pyproject.toml").write_text("[project]\nname = 'test'\n")
        lockfile = tmp_path / "uv.lock"
        lockfile.write_text("# original\n")

        log_func = MagicMock()

        with patch("updater.python_updater.run_command") as mock_run:

            def modify_lockfile(*args, **kwargs):
                if "uv sync" in args[0]:
                    lockfile.write_text("# modified\n")
                return MagicMock(returncode=0)

            mock_run.side_effect = modify_lockfile
            result = update_python_dependencies(tmp_path, log_func=log_func)

            assert result is True

    def test_returns_false_when_no_changes(self, tmp_path):
        """Test returns False when no updates needed."""
        (tmp_path / "pyproject.toml").write_text("[project]\nname = 'test'\n")
        lockfile = tmp_path / "uv.lock"
        lockfile.write_text("# unchanged\n")

        log_func = MagicMock()

        with patch("updater.python_updater.run_command") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            result = update_python_dependencies(tmp_path, log_func=log_func)

            assert result is False

    def test_no_pyproject_returns_false(self, tmp_path):
        """Test returns False when no pyproject.toml exists."""
        log_func = MagicMock()
        result = update_python_dependencies(tmp_path, log_func=log_func)
        assert result is False


class TestRunPrecommit:
    """Tests for run_precommit function."""

    def test_runs_make_precommit(self, tmp_path):
        """Test that make precommit is called."""
        log_func = MagicMock()

        with patch("updater.python_updater.run_command") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            run_precommit(tmp_path, log_func=log_func)

            # Verify make precommit was called
            mock_run.assert_called()
            calls = [str(c) for c in mock_run.call_args_list]
            assert any("make precommit" in str(c) for c in calls)

    def test_logs_phase_message(self, tmp_path):
        """Test that phase message is logged."""
        log_func = MagicMock()

        with patch("updater.python_updater.run_command") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            run_precommit(tmp_path, log_func=log_func)

            # Verify phase message was logged
            log_calls = [str(c) for c in log_func.call_args_list]
            assert any("Phase 2" in str(c) for c in log_calls)
