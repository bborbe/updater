"""Tests for Go dependency updater."""

from unittest.mock import Mock, patch

import pytest

from updater import config
from updater.go_updater import (
    _has_makefile_target,
    _highest_stable,
    _is_prerelease,
    _is_pseudo_version,
    _parse_osv_go_packages,
    _version_parts,
    downgrade_prerelease_requirements,
    fix_osv_vulnerabilities,
    run_precommit,
    update_go_dependencies,
)


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
        # First call lists modules, second call is the pre-release audit
        assert mock_run.call_count == 2
        assert "go list -mod=mod -m -u -f" in mock_run.call_args_list[0].args[0]
        assert "go list -mod=mod -m -f" in mock_run.call_args_list[1].args[0]

    def test_single_update_available(self, mock_module_path, reset_config):
        """Test updating a single dependency."""
        mock_stdout_check = "github.com/foo/bar"
        mock_stdout_detail = "github.com/foo/bar v1.0.0 [v1.1.0]"

        with patch("updater.go_updater.run_command") as mock_run:
            # First call: list outdated modules
            # Second call: check specific module
            # Third call: go get
            # Fourth call: check for more updates (none)
            # Fifth call: pre-release audit
            # Sixth call: go mod tidy
            mock_run.side_effect = [
                Mock(returncode=0, stdout=mock_stdout_check, stderr=""),  # list outdated
                Mock(returncode=0, stdout=mock_stdout_detail, stderr=""),  # check module
                Mock(returncode=0, stdout="", stderr=""),  # go get
                Mock(returncode=0, stdout="", stderr=""),  # check again (no more updates)
                Mock(returncode=0, stdout="", stderr=""),  # pre-release audit
                Mock(returncode=0, stdout="", stderr=""),  # go mod tidy
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
                Mock(returncode=0, stdout="", stderr=""),  # pre-release audit
                Mock(returncode=0, stdout="", stderr=""),  # go mod tidy
            ]

            result = update_go_dependencies(mock_module_path)

        assert result is True
        assert mock_run.call_count == 8

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
                Mock(returncode=0, stdout="", stderr=""),  # pre-release audit
                Mock(returncode=0, stdout="", stderr=""),  # go mod tidy
            ]

            result = update_go_dependencies(mock_module_path)

        assert result is True
        assert mock_run.call_count == 9

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
                Mock(returncode=0, stdout="", stderr=""),  # pre-release audit
                Mock(returncode=0, stdout="", stderr=""),  # go mod tidy
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
                # Pre-release audit (nothing to correct)
                Mock(returncode=0, stdout="", stderr=""),
                # Check again (no more) - this call doesn't happen because no updates were made
            ]

            result = update_go_dependencies(mock_module_path)

        # No updates were made, so returns False and no cleanup commands
        assert result is False
        assert mock_run.call_count == 3  # list, module check, pre-release audit

    def test_verbose_mode_logging(self, mock_module_path, reset_config):
        """Test verbose mode produces console output."""
        config.VERBOSE_MODE = True

        with patch("updater.go_updater.run_command") as mock_run:
            mock_run.return_value = Mock(returncode=0, stdout="", stderr="")

            update_go_dependencies(mock_module_path)

        # Just verify it doesn't crash - actual logging checked by integration tests
        assert mock_run.call_count == 2  # list plus pre-release audit

    def test_go_mod_tidy_called(self, mock_module_path, reset_config):
        """Test that go mod tidy is called after updates."""
        with patch("updater.go_updater.run_command") as mock_run:
            mock_run.side_effect = [
                Mock(returncode=0, stdout="github.com/foo/bar", stderr=""),
                Mock(returncode=0, stdout="github.com/foo/bar v1.0.0 [v1.1.0]", stderr=""),
                Mock(returncode=0, stdout="", stderr=""),  # go get
                Mock(returncode=0, stdout="", stderr=""),  # check again
                Mock(returncode=0, stdout="", stderr=""),  # pre-release audit
                Mock(returncode=0, stdout="", stderr=""),  # go mod tidy
            ]

            result = update_go_dependencies(mock_module_path)

        assert result is True
        assert mock_run.call_count == 6

        # Verify tidy was called
        calls = [str(call) for call in mock_run.call_args_list]
        assert any("go mod tidy" in str(call) for call in calls)
        assert not any("go mod vendor" in str(call) for call in calls)

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


class TestHasMakefileTarget:
    """Tests for _has_makefile_target function."""

    def test_target_exists(self, tmp_path):
        makefile = tmp_path / "Makefile"
        makefile.write_text("build:\n\tgo build\n\nosv-scanner:\n\t@echo scan\n")
        assert _has_makefile_target(tmp_path, "osv-scanner") is True

    def test_target_missing(self, tmp_path):
        makefile = tmp_path / "Makefile"
        makefile.write_text("build:\n\tgo build\n")
        assert _has_makefile_target(tmp_path, "osv-scanner") is False

    def test_no_makefile(self, tmp_path):
        assert _has_makefile_target(tmp_path, "osv-scanner") is False

    def test_target_with_dependencies(self, tmp_path):
        makefile = tmp_path / "Makefile"
        makefile.write_text("osv-scanner: build\n\t@echo scan\n")
        assert _has_makefile_target(tmp_path, "osv-scanner") is True


class TestParseOsvGoPackages:
    """Tests for _parse_osv_go_packages function."""

    def test_single_vulnerability(self):
        output = """\
Total 1 package affected by 1 known vulnerability
+-------------------------------------+------+-----------+-----------------------+---------------------+---------------+--------+
| OSV URL                             | CVSS | ECOSYSTEM | PACKAGE               | VERSION             | FIXED VERSION | SOURCE |
+-------------------------------------+------+-----------+-----------------------+---------------------+---------------+--------+
| https://osv.dev/GHSA-p436-gjf2-799p | 7.0  | Go        | github.com/docker/cli | 28.3.3+incompatible | 29.2.0        | go.mod |
+-------------------------------------+------+-----------+-----------------------+---------------------+---------------+--------+
"""
        packages = _parse_osv_go_packages(output)
        assert packages == ["github.com/docker/cli"]

    def test_multiple_vulnerabilities(self):
        output = """\
+------+------+-----------+---------------------------+---------+---------------+--------+
| URL  | CVSS | ECOSYSTEM | PACKAGE                   | VERSION | FIXED VERSION | SOURCE |
+------+------+-----------+---------------------------+---------+---------------+--------+
| url1 | 7.0  | Go        | github.com/docker/cli     | 28.3.3  | 29.2.0        | go.mod |
| url2 | 5.0  | Go        | github.com/example/pkg    | 1.0.0   | 1.1.0         | go.mod |
+------+------+-----------+---------------------------+---------+---------------+--------+
"""
        packages = _parse_osv_go_packages(output)
        assert packages == ["github.com/docker/cli", "github.com/example/pkg"]

    def test_non_go_ecosystem_ignored(self):
        output = """\
+------+------+-----------+------------------+---------+---------------+--------+
| URL  | CVSS | ECOSYSTEM | PACKAGE          | VERSION | FIXED VERSION | SOURCE |
+------+------+-----------+------------------+---------+---------------+--------+
| url1 | 7.0  | npm       | some-npm-package | 1.0.0   | 2.0.0         | yarn   |
+------+------+-----------+------------------+---------+---------------+--------+
"""
        packages = _parse_osv_go_packages(output)
        assert packages == []

    def test_no_table_in_output(self):
        output = "No vulnerabilities found.\n"
        packages = _parse_osv_go_packages(output)
        assert packages == []

    def test_header_row_excluded(self):
        output = "| OSV URL | CVSS | ECOSYSTEM | PACKAGE | VERSION | FIXED VERSION | SOURCE |\n"
        packages = _parse_osv_go_packages(output)
        assert packages == []


class TestFixOsvVulnerabilities:
    """Tests for fix_osv_vulnerabilities function."""

    def test_no_makefile_target(self, tmp_path):
        makefile = tmp_path / "Makefile"
        makefile.write_text("build:\n\tgo build\n")
        result = fix_osv_vulnerabilities(tmp_path)
        assert result is False

    def test_no_vulnerabilities_found(self, tmp_path):
        makefile = tmp_path / "Makefile"
        makefile.write_text("osv-scanner:\n\t@echo scan\n")

        with patch("updater.go_updater.subprocess.run") as mock_sub:
            mock_sub.return_value = Mock(returncode=0, stdout="No vulnerabilities found", stderr="")
            result = fix_osv_vulnerabilities(tmp_path)

        assert result is False

    def test_fixes_go_vulnerabilities(self, tmp_path):
        makefile = tmp_path / "Makefile"
        makefile.write_text("osv-scanner:\n\t@echo scan\n")

        osv_output = """\
+------+------+-----------+-----------------------+---------+---------------+--------+
| URL  | CVSS | ECOSYSTEM | PACKAGE               | VERSION | FIXED VERSION | SOURCE |
+------+------+-----------+-----------------------+---------+---------------+--------+
| url1 | 7.0  | Go        | github.com/docker/cli | 28.3.3  | 29.2.0        | go.mod |
+------+------+-----------+-----------------------+---------+---------------+--------+
"""

        with (
            patch("updater.go_updater.subprocess.run") as mock_sub,
            patch("updater.go_updater.run_command") as mock_run,
        ):
            mock_sub.return_value = Mock(returncode=1, stdout=osv_output, stderr="")
            mock_run.return_value = Mock(returncode=0, stdout="", stderr="")

            result = fix_osv_vulnerabilities(tmp_path)

        assert result is True
        # Should call: go get -u, go mod tidy
        assert mock_run.call_count == 2
        calls = [str(c) for c in mock_run.call_args_list]
        assert any("go get -u github.com/docker/cli" in c for c in calls)
        assert any("go mod tidy" in c for c in calls)
        assert not any("go mod vendor" in c for c in calls)

    def test_no_go_packages_in_output(self, tmp_path):
        makefile = tmp_path / "Makefile"
        makefile.write_text("osv-scanner:\n\t@echo scan\n")

        with patch("updater.go_updater.subprocess.run") as mock_sub:
            mock_sub.return_value = Mock(returncode=1, stdout="some error", stderr="")
            result = fix_osv_vulnerabilities(tmp_path)

        assert result is False


class TestPrereleaseHelpers:
    """Tests for pre-release detection, stable selection, and the correction path."""

    @pytest.mark.parametrize(
        ("version", "expected"),
        [
            ("v0.38.0-beta.0", True),
            ("v1.0.0-rc.1", True),
            ("v2.0.0-alpha", True),
            ("v0.0.0-20260101120000-abcdef123456", True),
            ("v0.37.2", False),
            ("v1.14.33", False),
            ("v1.2.3+build.7", False),
            ("1.2.3", False),
        ],
    )
    def test_is_prerelease(self, version, expected):
        """A hyphen in the version core marks a pre-release."""
        assert _is_prerelease(version) is expected

    @pytest.mark.parametrize(
        ("version", "expected"),
        [
            ("v0.0.0-20260101120000-abcdef123456", True),
            ("v1.2.3-0.20260101120000-abcdef123456", True),
            ("v1.2.3-pre.0.20260101120000-abcdef123456", True),
            ("v0.38.0-beta.0", False),
            ("v0.37.2", False),
        ],
    )
    def test_is_pseudo_version(self, version, expected):
        """Only a 14-digit timestamp plus 12 hex characters marks a commit pseudo-version."""
        assert _is_pseudo_version(version) is expected

    @pytest.mark.parametrize(
        ("version", "expected"),
        [
            ("v0.38.0-beta.0", (0, 38, 0)),
            ("v1.2.3+build.7", (1, 2, 3)),
            ("v0.37.2", (0, 37, 2)),
            ("not-a-version", None),
        ],
    )
    def test_version_parts(self, version, expected):
        """The numeric triple parses even when a pre-release suffix is present."""
        assert _version_parts(version) == expected

    @pytest.mark.parametrize(
        ("versions", "major", "expected"),
        [
            (["v0.9.0", "v0.10.0", "v0.10.2"], None, "v0.10.2"),
            (["v0.37.1", "v0.37.2", "v0.38.0-beta.0"], None, "v0.37.2"),
            (["v1.0.0", "v1.1.0", "v1.2.0"], None, "v1.2.0"),
            (["v1.0.0-rc.1", "v1.0.0-beta.2"], None, None),
            ([], None, None),
            (["k8s.io/api", "v0.37.1", "not-a-version", "v0.37.2"], None, "v0.37.2"),
            (["v0.9.0", "v1.0.0"], 0, "v0.9.0"),
        ],
    )
    def test_highest_stable(self, versions, major, expected):
        """A pre-release never wins, ordering is numeric, and the major filter holds."""
        assert _highest_stable(versions, major=major) == expected

    def test_downgrade_corrects_prerelease_to_highest_stable(self, mock_module_path, reset_config):
        """The measured lib/k8s defect: a pre-release requirement is moved to the highest stable."""
        with patch("updater.go_updater.run_command") as mock_run:
            mock_run.side_effect = [
                Mock(
                    returncode=0,
                    stdout="k8s.io/api@v0.38.0-beta.0\n\nbborbe/k8s@v1.14.33\n\n",
                    stderr="",
                ),
                Mock(
                    returncode=0,
                    stdout="k8s.io/api v0.37.0 v0.37.1 v0.37.2 v0.38.0-alpha.0 v0.38.0-beta.0",
                    stderr="",
                ),
                Mock(returncode=0, stdout="", stderr=""),
            ]
            corrected = downgrade_prerelease_requirements(mock_module_path)
        commands = [call.args[0] for call in mock_run.call_args_list]
        get_commands = [command for command in commands if command.startswith("go get")]
        assert corrected is True
        assert "go get k8s.io/api@v0.37.2" in get_commands
        assert not any("v0.38.0-beta.0" in command for command in get_commands)
        assert not any("bborbe/k8s" in command for command in commands)

    def test_pseudo_version_left_alone(self, mock_module_path, reset_config):
        """A commit pseudo-version is a deliberate pin and is never moved."""
        with patch("updater.go_updater.run_command") as mock_run:
            mock_run.side_effect = [
                Mock(
                    returncode=0,
                    stdout="k8s.io/utils@v0.0.0-20260101120000-abcdef123456\n",
                    stderr="",
                ),
            ]
            corrected = downgrade_prerelease_requirements(mock_module_path)
        commands = [call.args[0] for call in mock_run.call_args_list]
        assert corrected is False
        assert not any(command.startswith("go get") for command in commands)

    def test_no_stable_of_current_major_leaves_prerelease(self, mock_module_path, reset_config):
        """When no stable release of the current major exists, the module is left alone."""
        with patch("updater.go_updater.run_command") as mock_run:
            mock_run.side_effect = [
                Mock(returncode=0, stdout="example.com/lib@v1.0.0-rc.1\n", stderr=""),
                Mock(returncode=0, stdout="example.com/lib v0.9.0 v0.10.0", stderr=""),
            ]
            corrected = downgrade_prerelease_requirements(mock_module_path)
        commands = [call.args[0] for call in mock_run.call_args_list]
        assert corrected is False
        assert not any(command.startswith("go get") for command in commands)

    def test_update_go_dependencies_corrects_prerelease_without_upgrade(
        self, mock_module_path, reset_config
    ):
        """A sweep with no upgrade available still corrects a pre-release requirement."""
        with patch("updater.go_updater.run_command") as mock_run:
            mock_run.side_effect = [
                Mock(returncode=0, stdout="", stderr=""),  # list outdated: none
                Mock(returncode=0, stdout="k8s.io/api@v0.38.0-beta.0\n", stderr=""),  # audit
                Mock(
                    returncode=0,
                    stdout="k8s.io/api v0.37.1 v0.37.2 v0.38.0-beta.0",
                    stderr="",
                ),  # versions
                Mock(returncode=0, stdout="", stderr=""),  # go get
                Mock(returncode=0, stdout="", stderr=""),  # clean_indirect_deps: list indirect
                Mock(returncode=0, stdout="", stderr=""),  # go mod tidy
            ]
            result = update_go_dependencies(mock_module_path)
        commands = [call.args[0] for call in mock_run.call_args_list]
        assert result is True
        assert "go get k8s.io/api@v0.37.2" in commands
        assert "go mod tidy" in commands

    def test_upgrade_guard_skips_prerelease_candidate(self, mock_module_path, reset_config):
        """A pre-release reported as the available upgrade is never applied."""
        with patch("updater.go_updater.run_command") as mock_run:
            mock_run.side_effect = [
                Mock(returncode=0, stdout="k8s.io/api", stderr=""),  # list outdated
                Mock(
                    returncode=0, stdout="k8s.io/api v0.37.2 [v0.38.0-beta.0]", stderr=""
                ),  # check
                Mock(
                    returncode=0,
                    stdout="k8s.io/api v0.37.0 v0.37.1 v0.37.2 v0.38.0-alpha.0 v0.38.0-beta.0",
                    stderr="",
                ),  # versions
                Mock(returncode=0, stdout="", stderr=""),  # go get stable
                Mock(returncode=0, stdout="", stderr=""),  # list again: none
                Mock(returncode=0, stdout="", stderr=""),  # audit
                Mock(returncode=0, stdout="", stderr=""),  # go mod tidy
            ]
            result = update_go_dependencies(mock_module_path)
        commands = [call.args[0] for call in mock_run.call_args_list]
        assert result is True
        assert "go get k8s.io/api@v0.37.2" in commands
        assert not any("@latest" in command for command in commands)
        assert not any("v0.38.0-beta.0" in command for command in commands)

    def test_correction_cleans_indirect_pins(self, mock_module_path, reset_config):
        """A correction drops the indirect pins the pre-release dragged in."""
        with (
            patch("updater.go_updater.clean_indirect_deps") as mock_clean,
            patch("updater.go_updater.run_command") as mock_run,
        ):
            mock_run.side_effect = [
                Mock(returncode=0, stdout="", stderr=""),  # list outdated: none
                Mock(returncode=0, stdout="example.com/lib@v1.0.0-rc.1\n", stderr=""),  # audit
                Mock(returncode=0, stdout="example.com/lib v1.0.0", stderr=""),  # versions
                Mock(returncode=0, stdout="", stderr=""),  # go get stable
                Mock(returncode=0, stdout="", stderr=""),  # go mod tidy
            ]
            result = update_go_dependencies(mock_module_path)
        commands = [call.args[0] for call in mock_run.call_args_list]
        assert result is True
        assert "go get example.com/lib@v1.0.0" in commands
        mock_clean.assert_called_once()

    def test_no_correction_skips_indirect_cleanup(self, mock_module_path, reset_config):
        """An upgrade with nothing to correct leaves the indirect graph alone."""
        with (
            patch("updater.go_updater.clean_indirect_deps") as mock_clean,
            patch("updater.go_updater.run_command") as mock_run,
        ):
            mock_run.side_effect = [
                Mock(returncode=0, stdout="example.com/lib", stderr=""),  # list outdated
                Mock(returncode=0, stdout="example.com/lib v1.0.0 [v1.1.0]", stderr=""),  # check
                Mock(returncode=0, stdout="", stderr=""),  # go get stable
                Mock(returncode=0, stdout="", stderr=""),  # list again: none
                Mock(returncode=0, stdout="example.com/lib@v1.1.0\n", stderr=""),  # audit
                Mock(returncode=0, stdout="", stderr=""),  # go mod tidy
            ]
            result = update_go_dependencies(mock_module_path)
        commands = [call.args[0] for call in mock_run.call_args_list]
        assert result is True
        assert "go get example.com/lib@v1.1.0" in commands
        mock_clean.assert_not_called()
