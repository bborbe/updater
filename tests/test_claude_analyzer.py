"""Tests for Claude integration and analysis."""

import json
import os
from unittest.mock import AsyncMock, Mock, patch

import pytest

from updater import config
from updater.claude_analyzer import (
    _extract_json_from_response,
    _get_clean_config_dir,
    _run_claude,
    _without_claudecode,
    analyze_changes_with_claude,
    analyze_unreleased_for_release,
    generate_changelog_from_commits,
    verify_claude_auth,
)
from updater.exceptions import ClaudeError


@pytest.fixture
def reset_config():
    """Reset global config before each test."""
    config.VERBOSE_MODE = False
    config.MODEL = "sonnet"
    config.CLAUDE_SESSION_DELAY = 0.1
    yield


@pytest.fixture
def mock_module_path(tmp_path):
    """Create a mock module directory."""
    module_path = tmp_path / "test-module"
    module_path.mkdir()
    return module_path


class TestExtractJsonFromResponse:
    """Tests for _extract_json_from_response helper."""

    def test_json_code_block(self):
        """Extracts JSON from a ```json ... ``` block."""
        response = '```json\n{"key": "value"}\n```'
        result = _extract_json_from_response(response)
        assert result == {"key": "value"}

    def test_plain_code_block(self):
        """Extracts JSON from a plain ``` ... ``` block."""
        response = '```\n{"key": "value"}\n```'
        result = _extract_json_from_response(response)
        assert result == {"key": "value"}

    def test_no_code_block_with_braces(self):
        """Extracts JSON by brace matching when there is no code block."""
        response = 'Here is the result: {"key": "value"} done.'
        result = _extract_json_from_response(response)
        assert result == {"key": "value"}

    def test_no_json_raises_claude_error(self):
        """Raises ClaudeError when response cannot be parsed as JSON."""
        with pytest.raises(ClaudeError, match="Failed to parse Claude response as JSON"):
            _extract_json_from_response("This is not valid JSON at all")


class TestAnalyzeChangesWithClaude:
    """Tests for analyze_changes_with_claude function."""

    @pytest.mark.asyncio
    async def test_successful_analysis_patch(self, mock_module_path, reset_config):
        """Test successful Claude analysis for patch version."""
        mock_response = {
            "version_bump": "patch",
            "changelog": ["update golang to 1.23.4", "update dependencies"],
            "commit_message": "update dependencies",
        }

        with (
            patch("updater.claude_analyzer._run_claude", new_callable=AsyncMock) as mock_run,
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            mock_run.return_value = json.dumps(mock_response)
            result = await analyze_changes_with_claude(mock_module_path)

        assert result["version_bump"] == "patch"
        assert result["changelog"] == ["update golang to 1.23.4", "update dependencies"]
        assert result["commit_message"] == "update dependencies"

    @pytest.mark.asyncio
    async def test_successful_analysis_minor(self, mock_module_path, reset_config):
        """Test successful Claude analysis for minor version."""
        mock_response = {
            "version_bump": "minor",
            "changelog": ["add new feature X", "improve API"],
            "commit_message": "add new feature X",
        }

        with (
            patch("updater.claude_analyzer._run_claude", new_callable=AsyncMock) as mock_run,
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            mock_run.return_value = json.dumps(mock_response)
            result = await analyze_changes_with_claude(mock_module_path)

        assert result["version_bump"] == "minor"
        assert len(result["changelog"]) == 2

    @pytest.mark.asyncio
    async def test_successful_analysis_major(self, mock_module_path, reset_config):
        """Test successful Claude analysis for major version."""
        mock_response = {
            "version_bump": "major",
            "changelog": ["breaking: remove deprecated API", "refactor core logic"],
            "commit_message": "breaking: remove deprecated API",
        }

        with (
            patch("updater.claude_analyzer._run_claude", new_callable=AsyncMock) as mock_run,
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            mock_run.return_value = json.dumps(mock_response)
            result = await analyze_changes_with_claude(mock_module_path)

        assert result["version_bump"] == "major"

    @pytest.mark.asyncio
    async def test_successful_analysis_none(self, mock_module_path, reset_config):
        """Test successful Claude analysis for no version bump."""
        mock_response = {
            "version_bump": "none",
            "changelog": ["update .gitignore"],
            "commit_message": "update .gitignore",
        }

        with (
            patch("updater.claude_analyzer._run_claude", new_callable=AsyncMock) as mock_run,
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            mock_run.return_value = json.dumps(mock_response)
            result = await analyze_changes_with_claude(mock_module_path)

        assert result["version_bump"] == "none"

    @pytest.mark.asyncio
    async def test_json_in_code_block(self, mock_module_path, reset_config):
        """Test parsing JSON wrapped in markdown code block."""
        mock_response = {
            "version_bump": "patch",
            "changelog": ["update deps"],
            "commit_message": "update deps",
        }

        response_text = f"```json\n{json.dumps(mock_response)}\n```"

        with (
            patch("updater.claude_analyzer._run_claude", new_callable=AsyncMock) as mock_run,
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            mock_run.return_value = response_text
            result = await analyze_changes_with_claude(mock_module_path)

        assert result["version_bump"] == "patch"

    @pytest.mark.asyncio
    async def test_json_in_generic_code_block(self, mock_module_path, reset_config):
        """Test parsing JSON wrapped in generic code block."""
        mock_response = {
            "version_bump": "patch",
            "changelog": ["update deps"],
            "commit_message": "update deps",
        }

        response_text = f"```\n{json.dumps(mock_response)}\n```"

        with (
            patch("updater.claude_analyzer._run_claude", new_callable=AsyncMock) as mock_run,
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            mock_run.return_value = response_text
            result = await analyze_changes_with_claude(mock_module_path)

        assert result["version_bump"] == "patch"

    @pytest.mark.asyncio
    async def test_json_with_surrounding_text(self, mock_module_path, reset_config):
        """Test parsing JSON with surrounding explanation text."""
        mock_response = {
            "version_bump": "patch",
            "changelog": ["update deps"],
            "commit_message": "update deps",
        }

        response_text = f"Here is my analysis:\n\n{json.dumps(mock_response)}\n\nHope this helps!"

        with (
            patch("updater.claude_analyzer._run_claude", new_callable=AsyncMock) as mock_run,
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            mock_run.return_value = response_text
            result = await analyze_changes_with_claude(mock_module_path)

        assert result["version_bump"] == "patch"

    @pytest.mark.asyncio
    async def test_invalid_json_response(self, mock_module_path, reset_config):
        """Test handling of invalid JSON response."""
        with (
            patch("updater.claude_analyzer._run_claude", new_callable=AsyncMock) as mock_run,
            patch("asyncio.sleep", new_callable=AsyncMock),
            pytest.raises(ClaudeError, match="Failed to parse Claude response"),
        ):
            mock_run.return_value = "This is not valid JSON"
            await analyze_changes_with_claude(mock_module_path)

    @pytest.mark.asyncio
    async def test_missing_fields_use_defaults(self, mock_module_path, reset_config):
        """Test default values when response is missing fields."""
        mock_response = {}  # Empty response

        with (
            patch("updater.claude_analyzer._run_claude", new_callable=AsyncMock) as mock_run,
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            mock_run.return_value = json.dumps(mock_response)
            result = await analyze_changes_with_claude(mock_module_path)

        # Should use defaults
        assert result["version_bump"] == "patch"
        assert result["changelog"] == ["go mod update"]
        assert result["commit_message"] == "update dependencies"

    @pytest.mark.asyncio
    async def test_uses_configured_model(self, mock_module_path, reset_config):
        """Test that configured model is passed to _run_claude."""
        config.MODEL = "haiku"

        mock_response = {
            "version_bump": "patch",
            "changelog": ["update deps"],
            "commit_message": "update deps",
        }

        with (
            patch("updater.claude_analyzer._run_claude", new_callable=AsyncMock) as mock_run,
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            mock_run.return_value = json.dumps(mock_response)
            await analyze_changes_with_claude(mock_module_path)

            # _run_claude is called with cwd=module_path; model comes from config
            mock_run.assert_called_once()
            call_kwargs = mock_run.call_args
            assert call_kwargs.kwargs.get("cwd") == mock_module_path

    @pytest.mark.asyncio
    async def test_clean_config_dir_not_created_if_missing(
        self, mock_module_path, reset_config, tmp_path
    ):
        """Test that .claude-clean is NOT created when it doesn't exist."""
        mock_response = {
            "version_bump": "patch",
            "changelog": ["update deps"],
            "commit_message": "update deps",
        }

        # Use tmp_path as home directory for testing
        fake_home = tmp_path / "home"
        fake_home.mkdir()

        with (
            patch("updater.claude_analyzer._run_claude", new_callable=AsyncMock) as mock_run,
            patch("updater.claude_analyzer.Path.home", return_value=fake_home),
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            mock_run.return_value = json.dumps(mock_response)
            await analyze_changes_with_claude(mock_module_path)

            # .claude-clean should NOT be created automatically
            clean_dir = fake_home / ".claude-clean"
            assert not clean_dir.exists()

    def test_clean_config_dir_returns_none_when_missing(self, tmp_path):
        """Test that _get_clean_config_dir returns None when .claude-clean doesn't exist."""
        fake_home = tmp_path / "home"
        fake_home.mkdir()

        with patch("updater.claude_analyzer.Path.home", return_value=fake_home):
            result = _get_clean_config_dir()

        assert result is None

    def test_clean_config_dir_removes_plugins_dir(self, tmp_path):
        """Test that _get_clean_config_dir removes the plugins directory if present."""
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        clean_dir = fake_home / ".claude-clean"
        clean_dir.mkdir()
        plugins_dir = clean_dir / "plugins"
        plugins_dir.mkdir()

        with patch("updater.claude_analyzer.Path.home", return_value=fake_home):
            result = _get_clean_config_dir()

        assert result == clean_dir
        assert not plugins_dir.exists()

    def test_clean_config_dir_used_if_exists(self, tmp_path):
        """Test that _get_clean_config_dir sets up settings.json when .claude-clean exists."""
        # Use tmp_path as home directory for testing
        fake_home = tmp_path / "home"
        fake_home.mkdir()

        # Pre-create .claude-clean directory
        clean_dir = fake_home / ".claude-clean"
        clean_dir.mkdir()

        with patch("updater.claude_analyzer.Path.home", return_value=fake_home):
            result = _get_clean_config_dir()

        # settings.json should be created inside existing .claude-clean
        assert result == clean_dir
        assert (clean_dir / "settings.json").exists()

    @pytest.mark.asyncio
    async def test_session_delay_applied(self, mock_module_path, reset_config):
        """Test that session delay is applied after analysis."""
        config.CLAUDE_SESSION_DELAY = 0.5

        mock_response = {
            "version_bump": "patch",
            "changelog": ["update deps"],
            "commit_message": "update deps",
        }

        mock_sleep = AsyncMock()

        with (
            patch("updater.claude_analyzer._run_claude", new_callable=AsyncMock) as mock_run,
            patch("asyncio.sleep", mock_sleep),
        ):
            mock_run.return_value = json.dumps(mock_response)
            await analyze_changes_with_claude(mock_module_path)

            # Verify sleep was called with correct delay
            mock_sleep.assert_called_once_with(0.5)


class TestVerifyClaudeAuth:
    """Tests for verify_claude_auth function."""

    @pytest.mark.asyncio
    async def test_successful_auth(self, reset_config):
        """Test successful authentication."""
        with patch("updater.claude_analyzer._run_claude", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = "ok"
            success, error = await verify_claude_auth()

        assert success is True
        assert error == ""

    @pytest.mark.asyncio
    async def test_invalid_api_key_error(self, reset_config):
        """Test auth failure with invalid API key."""
        with patch(
            "updater.claude_analyzer._run_claude",
            new_callable=AsyncMock,
            side_effect=Exception("Invalid API key"),
        ):
            success, error = await verify_claude_auth()

        assert success is False
        assert "authentication failed" in error.lower()
        assert "/login" in error

    @pytest.mark.asyncio
    async def test_login_required_error(self, reset_config):
        """Test auth failure when login required."""
        with patch(
            "updater.claude_analyzer._run_claude",
            new_callable=AsyncMock,
            side_effect=Exception("Please run /login"),
        ):
            success, error = await verify_claude_auth()

        assert success is False
        assert "Claude authentication failed" in error

    @pytest.mark.asyncio
    async def test_other_error(self, reset_config):
        """Test other errors don't show login hint."""
        with (
            patch(
                "updater.claude_analyzer._run_claude",
                new_callable=AsyncMock,
                side_effect=Exception("Network timeout"),
            ),
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            success, error = await verify_claude_auth()

        assert success is False
        assert "Claude check failed" in error
        assert "Network timeout" in error

    @pytest.mark.asyncio
    async def test_timeout_keyword_triggers_retries_and_exhausts(self, reset_config):
        """Test that a 'timeout' error triggers retries and fails after max_retries."""
        call_count = 0

        async def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            raise ClaudeError("connection timeout")

        with (
            patch("updater.claude_analyzer._run_claude", side_effect=side_effect),
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            success, error = await verify_claude_auth()

        assert success is False
        assert call_count == 3
        assert "failed" in error.lower()

    @pytest.mark.asyncio
    async def test_non_retryable_error_fails_immediately(self, reset_config):
        """Test that an unknown non-retryable error fails on the first attempt."""
        call_count = 0

        async def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            raise Exception("completely unknown XYZ123 error")

        with (
            patch("updater.claude_analyzer._run_claude", side_effect=side_effect),
            patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep,
        ):
            success, error = await verify_claude_auth()

        assert success is False
        assert call_count == 1
        mock_sleep.assert_not_called()

    @pytest.mark.asyncio
    async def test_auth_times_out_after_30_seconds(self, reset_config):
        """Test that asyncio.TimeoutError from wait_for is treated as retryable and exhausts retries."""

        with (
            patch("updater.claude_analyzer._run_claude", side_effect=TimeoutError()),
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            success, error = await verify_claude_auth()

        assert success is False
        assert "timed out" in error.lower()
        assert "/login" in error


class TestAnalyzeUnreleasedForRelease:
    """Tests for analyze_unreleased_for_release function."""

    @pytest.mark.asyncio
    async def test_success_path_returns_version_bump(self, reset_config):
        """Test successful analysis returns version bump dict."""
        response = json.dumps({"version_bump": "minor"})
        mock_log = Mock()

        with (
            patch("updater.claude_analyzer._run_claude", new_callable=AsyncMock) as mock_run,
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            mock_run.return_value = response
            result = await analyze_unreleased_for_release(
                ["Add new feature", "Fix bug"], "test-module", log_func=mock_log
            )

        assert result["version_bump"] == "minor"

    @pytest.mark.asyncio
    async def test_rate_limit_retries_and_succeeds(self, reset_config):
        """Test that rate_limit error retries and succeeds on second attempt."""
        call_count = 0

        async def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ClaudeError("rate_limit exceeded")
            return json.dumps({"version_bump": "patch"})

        mock_log = Mock()

        with (
            patch("updater.claude_analyzer._run_claude", side_effect=side_effect),
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            result = await analyze_unreleased_for_release(
                ["Fix bug"], "test-module", log_func=mock_log
            )

        assert result["version_bump"] == "patch"
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_max_retries_exhausted_raises_claude_error(self, reset_config):
        """Test that exhausting all retries raises ClaudeError."""
        with (
            patch(
                "updater.claude_analyzer._run_claude",
                new_callable=AsyncMock,
                side_effect=ClaudeError("connection error"),
            ),
            patch("asyncio.sleep", new_callable=AsyncMock),
            pytest.raises(ClaudeError),
        ):
            await analyze_unreleased_for_release(["Fix bug"], "test-module")


class TestGenerateChangelogFromCommits:
    """Tests for generate_changelog_from_commits function."""

    @pytest.mark.asyncio
    async def test_successful_generation(self, reset_config):
        """Test successful changelog generation from commits."""
        commits = [
            {"hash": "abc1234", "subject": "Add new feature", "body": ""},
            {"hash": "def5678", "subject": "Fix bug in handler", "body": ""},
        ]

        response = json.dumps(
            {
                "entries": [
                    "Add new feature for users",
                    "Fix bug in HTTP handler",
                ]
            }
        )

        mock_log = Mock()

        with patch("updater.claude_analyzer._run_claude", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = response
            result = await generate_changelog_from_commits(
                commits, "test-module", log_func=mock_log
            )

        assert len(result) == 2
        assert "Add new feature for users" in result
        assert "Fix bug in HTTP handler" in result

    @pytest.mark.asyncio
    async def test_json_in_code_block(self, reset_config):
        """Test parsing JSON wrapped in code block."""
        commits = [{"hash": "abc", "subject": "Test", "body": ""}]

        response = '```json\n{"entries": ["Test entry"]}\n```'

        mock_log = Mock()

        with patch("updater.claude_analyzer._run_claude", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = response
            result = await generate_changelog_from_commits(
                commits, "test-module", log_func=mock_log
            )

        assert result == ["Test entry"]

    @pytest.mark.asyncio
    async def test_empty_entries(self, reset_config):
        """Test handling empty entries response."""
        commits = [{"hash": "abc", "subject": "Minor fix", "body": ""}]

        response = json.dumps({"entries": []})

        mock_log = Mock()

        with patch("updater.claude_analyzer._run_claude", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = response
            result = await generate_changelog_from_commits(
                commits, "test-module", log_func=mock_log
            )

        assert result == []

    @pytest.mark.asyncio
    async def test_retry_on_transient_error_succeeds(self, reset_config):
        """Test that a transient (timeout) error retries and succeeds on second attempt."""
        commits = [{"hash": "abc", "subject": "Add feature", "body": ""}]
        call_count = 0

        async def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ClaudeError("connection timeout")
            return json.dumps({"entries": ["Added feature X"]})

        mock_log = Mock()

        with (
            patch("updater.claude_analyzer._run_claude", side_effect=side_effect),
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            result = await generate_changelog_from_commits(
                commits, "test-module", log_func=mock_log
            )

        assert result == ["Added feature X"]
        assert call_count == 2


class TestRunClaude:
    """Tests for _run_claude function."""

    @pytest.mark.asyncio
    async def test_kills_subprocess_on_timeout(self, reset_config):
        """Test that proc.kill() is called when asyncio.wait_for raises TimeoutError."""
        mock_proc = AsyncMock()
        mock_proc.kill = Mock()
        mock_proc.wait = AsyncMock()

        async def mock_wait_for(coro, *, timeout):
            coro.close()
            raise TimeoutError()

        with (
            patch("asyncio.create_subprocess_exec", new_callable=AsyncMock, return_value=mock_proc),
            patch("asyncio.wait_for", side_effect=mock_wait_for),
            pytest.raises(ClaudeError, match="Claude timed out after 120s"),
        ):
            await _run_claude("test prompt")

        mock_proc.kill.assert_called_once()
        mock_proc.wait.assert_awaited_once()


class TestWithoutClaudecode:
    """Tests for _without_claudecode context manager."""

    def test_removes_claudecode_inside_block(self):
        """CLAUDECODE is absent from os.environ inside the context manager."""
        os.environ["CLAUDECODE"] = "1"
        try:
            with _without_claudecode():
                assert "CLAUDECODE" not in os.environ
            assert os.environ.get("CLAUDECODE") == "1"
        finally:
            os.environ.pop("CLAUDECODE", None)

    def test_restores_claudecode_after_exception(self):
        """CLAUDECODE is restored even when an exception is raised inside the block."""
        os.environ["CLAUDECODE"] = "1"
        try:
            try:
                with _without_claudecode():
                    raise RuntimeError("test")
            except RuntimeError:
                pass
            assert os.environ.get("CLAUDECODE") == "1"
        finally:
            os.environ.pop("CLAUDECODE", None)

    def test_works_when_claudecode_not_set(self):
        """Works correctly when CLAUDECODE is not set."""
        os.environ.pop("CLAUDECODE", None)
        with _without_claudecode():
            assert "CLAUDECODE" not in os.environ
        assert "CLAUDECODE" not in os.environ

    def test_does_not_introduce_claudecode(self):
        """CLAUDECODE is not added to os.environ if it wasn't there before."""
        os.environ.pop("CLAUDECODE", None)
        with _without_claudecode():
            pass
        assert "CLAUDECODE" not in os.environ
