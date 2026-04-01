"""Tests for clean_indirect_deps function."""

from unittest.mock import Mock, patch

import pytest

from updater.go_updater import clean_indirect_deps


@pytest.fixture
def module_path(tmp_path):
    """Create a mock module directory with go.mod."""
    (tmp_path / "go.mod").write_text(
        "module example.com/test\n\ngo 1.23\n\nrequire (\n"
        "\texample.com/direct v1.0.0\n"
        "\texample.com/indirect v2.0.0 // indirect\n"
        ")\n"
    )
    return tmp_path


class TestCleanIndirectDeps:
    """Tests for clean_indirect_deps function."""

    def test_no_gomod_returns_false(self, tmp_path):
        """Test that missing go.mod returns False with warning."""
        log_calls = []

        def capture_log(msg, to_console=False):
            log_calls.append(msg)

        result = clean_indirect_deps(tmp_path, log_func=capture_log)

        assert result is False
        assert any("No go.mod found" in msg for msg in log_calls)

    def test_no_indirect_deps_returns_false(self, module_path):
        """Test that go.mod with no indirect deps returns False."""
        with patch("updater.go_updater.run_command") as mock_run:
            mock_run.return_value = Mock(returncode=0, stdout="", stderr="")

            result = clean_indirect_deps(module_path)

        assert result is False
        # Only called once for go list
        assert mock_run.call_count == 1

    def test_indirect_deps_are_removed(self, module_path):
        """Test that indirect deps are dropped and go mod tidy is called."""
        indirect_output = "example.com/indirect@v2.0.0\nexample.com/other@v1.5.0\n"

        with patch("updater.go_updater.run_command") as mock_run:
            mock_run.side_effect = [
                Mock(returncode=0, stdout=indirect_output, stderr=""),  # go list
                Mock(returncode=0, stdout="", stderr=""),  # droprequire indirect
                Mock(returncode=0, stdout="", stderr=""),  # droprequire other
                Mock(returncode=0, stdout="", stderr=""),  # go mod tidy
            ]

            result = clean_indirect_deps(module_path)

        assert result is True
        assert mock_run.call_count == 4
        calls = [str(c) for c in mock_run.call_args_list]
        assert any("droprequire example.com/indirect" in c for c in calls)
        assert any("droprequire example.com/other" in c for c in calls)
        assert any("go mod tidy" in c for c in calls)

    def test_mixed_direct_and_indirect_only_removes_indirect(self, module_path):
        """Test that only indirect deps are targeted, not direct ones."""
        # go list -f only outputs indirect deps, so direct ones are never in the list
        indirect_output = "example.com/indirect@v2.0.0\n"

        with patch("updater.go_updater.run_command") as mock_run:
            mock_run.side_effect = [
                Mock(returncode=0, stdout=indirect_output, stderr=""),  # go list
                Mock(returncode=0, stdout="", stderr=""),  # droprequire
                Mock(returncode=0, stdout="", stderr=""),  # go mod tidy
            ]

            result = clean_indirect_deps(module_path)

        assert result is True
        calls = [str(c) for c in mock_run.call_args_list]
        # Direct dep should NOT be dropped
        assert not any("droprequire example.com/direct" in c for c in calls)
        assert any("droprequire example.com/indirect" in c for c in calls)

    def test_idempotent_when_no_indirect_deps_remain(self, module_path):
        """Test that running twice with no indirect deps is a no-op."""
        with patch("updater.go_updater.run_command") as mock_run:
            mock_run.return_value = Mock(returncode=0, stdout="", stderr="")

            result1 = clean_indirect_deps(module_path)
            result2 = clean_indirect_deps(module_path)

        assert result1 is False
        assert result2 is False

    def test_logs_count_of_removed_deps(self, module_path):
        """Test that the function logs how many indirect deps were removed."""
        indirect_output = "example.com/a@v1.0.0\nexample.com/b@v2.0.0\n"
        log_calls = []

        def capture_log(msg, to_console=False):
            log_calls.append(msg)

        with patch("updater.go_updater.run_command") as mock_run:
            mock_run.side_effect = [
                Mock(returncode=0, stdout=indirect_output, stderr=""),
                Mock(returncode=0, stdout="", stderr=""),
                Mock(returncode=0, stdout="", stderr=""),
                Mock(returncode=0, stdout="", stderr=""),
            ]

            clean_indirect_deps(module_path, log_func=capture_log)

        assert any("2" in msg for msg in log_calls)

    def test_go_list_called_with_correct_args(self, module_path):
        """Test that go list is called with the indirect filter format."""
        with patch("updater.go_updater.run_command") as mock_run:
            mock_run.return_value = Mock(returncode=0, stdout="", stderr="")

            clean_indirect_deps(module_path)

        first_call = mock_run.call_args_list[0]
        assert "go list" in first_call[0][0]
        assert ".Indirect" in first_call[0][0]
