"""Tests for Claude integration and analysis."""

import json
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import pytest

from updater import config
from updater.claude_analyzer import (
    analyze_changes_with_claude,
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


def create_mock_client(response_text):
    """Helper to create mock Claude SDK client."""
    from claude_code_sdk import AssistantMessage, TextBlock

    mock_text_block = Mock(spec=TextBlock)
    mock_text_block.text = response_text

    mock_assistant_msg = Mock(spec=AssistantMessage)
    mock_assistant_msg.content = [mock_text_block]

    async def mock_receive_response():
        yield mock_assistant_msg

    mock_client = AsyncMock()
    mock_client.query = AsyncMock()
    mock_client.receive_response = mock_receive_response
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock()

    return mock_client


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

        mock_client = create_mock_client(json.dumps(mock_response))

        with (
            patch("updater.claude_analyzer.ClaudeSDKClient", return_value=mock_client),
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
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

        mock_client = create_mock_client(json.dumps(mock_response))

        with (
            patch("updater.claude_analyzer.ClaudeSDKClient", return_value=mock_client),
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
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

        mock_client = create_mock_client(json.dumps(mock_response))

        with (
            patch("updater.claude_analyzer.ClaudeSDKClient", return_value=mock_client),
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
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

        mock_client = create_mock_client(json.dumps(mock_response))

        with (
            patch("updater.claude_analyzer.ClaudeSDKClient", return_value=mock_client),
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
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
        mock_client = create_mock_client(response_text)

        with (
            patch("updater.claude_analyzer.ClaudeSDKClient", return_value=mock_client),
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
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
        mock_client = create_mock_client(response_text)

        with (
            patch("updater.claude_analyzer.ClaudeSDKClient", return_value=mock_client),
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
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
        mock_client = create_mock_client(response_text)

        with (
            patch("updater.claude_analyzer.ClaudeSDKClient", return_value=mock_client),
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            result = await analyze_changes_with_claude(mock_module_path)

        assert result["version_bump"] == "patch"

    @pytest.mark.asyncio
    async def test_invalid_json_response(self, mock_module_path, reset_config):
        """Test handling of invalid JSON response."""
        mock_client = create_mock_client("This is not valid JSON")

        with (
            patch("updater.claude_analyzer.ClaudeSDKClient", return_value=mock_client),
            patch("asyncio.sleep", new_callable=AsyncMock),
            pytest.raises(ClaudeError, match="Failed to parse Claude response"),
        ):
            await analyze_changes_with_claude(mock_module_path)

    @pytest.mark.asyncio
    async def test_missing_fields_use_defaults(self, mock_module_path, reset_config):
        """Test default values when response is missing fields."""
        mock_response = {}  # Empty response
        mock_client = create_mock_client(json.dumps(mock_response))

        with (
            patch("updater.claude_analyzer.ClaudeSDKClient", return_value=mock_client),
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            result = await analyze_changes_with_claude(mock_module_path)

        # Should use defaults
        assert result["version_bump"] == "patch"
        assert result["changelog"] == ["go mod update"]
        assert result["commit_message"] == "update dependencies"

    @pytest.mark.asyncio
    async def test_multiple_text_blocks(self, mock_module_path, reset_config):
        """Test handling multiple text blocks in response."""
        from claude_code_sdk import AssistantMessage, TextBlock

        # Create multiple text blocks
        mock_text_block1 = Mock(spec=TextBlock)
        mock_text_block1.text = '{"version_bump": "patch",'

        mock_text_block2 = Mock(spec=TextBlock)
        mock_text_block2.text = ' "changelog": ["update deps"],'

        mock_text_block3 = Mock(spec=TextBlock)
        mock_text_block3.text = ' "commit_message": "update deps"}'

        mock_assistant_msg = Mock(spec=AssistantMessage)
        mock_assistant_msg.content = [mock_text_block1, mock_text_block2, mock_text_block3]

        async def mock_receive_response():
            yield mock_assistant_msg

        mock_client = AsyncMock()
        mock_client.query = AsyncMock()
        mock_client.receive_response = mock_receive_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock()

        with (
            patch("updater.claude_analyzer.ClaudeSDKClient", return_value=mock_client),
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            result = await analyze_changes_with_claude(mock_module_path)

        assert result["version_bump"] == "patch"

    @pytest.mark.asyncio
    async def test_changes_directory_context(self, mock_module_path, reset_config):
        """Test that function changes to module directory for analysis."""
        original_cwd = Path.cwd()

        mock_response = {
            "version_bump": "patch",
            "changelog": ["update deps"],
            "commit_message": "update deps",
        }

        mock_client = create_mock_client(json.dumps(mock_response))

        with (
            patch("updater.claude_analyzer.ClaudeSDKClient", return_value=mock_client),
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            await analyze_changes_with_claude(mock_module_path)

        # Should be back to original directory after analysis
        assert Path.cwd() == original_cwd

    @pytest.mark.asyncio
    async def test_uses_configured_model(self, mock_module_path, reset_config):
        """Test that configured model is used."""
        config.MODEL = "haiku"

        mock_response = {
            "version_bump": "patch",
            "changelog": ["update deps"],
            "commit_message": "update deps",
        }

        mock_client = create_mock_client(json.dumps(mock_response))

        with (
            patch("updater.claude_analyzer.ClaudeSDKClient", return_value=mock_client) as mock_sdk,
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            await analyze_changes_with_claude(mock_module_path)

            # Verify model was passed to client
            call_args = mock_sdk.call_args
            assert call_args[1]["options"].model == "haiku"

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

        mock_client = create_mock_client(json.dumps(mock_response))

        # Use tmp_path as home directory for testing
        fake_home = tmp_path / "home"
        fake_home.mkdir()

        with (
            patch("updater.claude_analyzer.ClaudeSDKClient", return_value=mock_client),
            patch("updater.claude_analyzer.Path.home", return_value=fake_home),
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            await analyze_changes_with_claude(mock_module_path)

            # .claude-clean should NOT be created automatically
            clean_dir = fake_home / ".claude-clean"
            assert not clean_dir.exists()

    @pytest.mark.asyncio
    async def test_clean_config_dir_used_if_exists(self, mock_module_path, reset_config, tmp_path):
        """Test that .claude-clean is used when it already exists."""
        mock_response = {
            "version_bump": "patch",
            "changelog": ["update deps"],
            "commit_message": "update deps",
        }

        mock_client = create_mock_client(json.dumps(mock_response))

        # Use tmp_path as home directory for testing
        fake_home = tmp_path / "home"
        fake_home.mkdir()

        # Pre-create .claude-clean directory
        clean_dir = fake_home / ".claude-clean"
        clean_dir.mkdir()

        with (
            patch("updater.claude_analyzer.ClaudeSDKClient", return_value=mock_client) as mock_sdk,
            patch("updater.claude_analyzer.Path.home", return_value=fake_home),
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            await analyze_changes_with_claude(mock_module_path)

            # settings.json should be created inside existing .claude-clean
            assert (clean_dir / "settings.json").exists()

            # CLAUDE_CONFIG_DIR should be set in env
            call_args = mock_sdk.call_args
            env = call_args[1]["options"].env
            assert env.get("CLAUDE_CONFIG_DIR") == str(clean_dir)

    @pytest.mark.asyncio
    async def test_session_delay_applied(self, mock_module_path, reset_config):
        """Test that session delay is applied after analysis."""
        config.CLAUDE_SESSION_DELAY = 0.5

        mock_response = {
            "version_bump": "patch",
            "changelog": ["update deps"],
            "commit_message": "update deps",
        }

        mock_client = create_mock_client(json.dumps(mock_response))
        mock_sleep = AsyncMock()

        with (
            patch("updater.claude_analyzer.ClaudeSDKClient", return_value=mock_client),
            patch("asyncio.sleep", mock_sleep),
        ):
            await analyze_changes_with_claude(mock_module_path)

            # Verify sleep was called with correct delay
            mock_sleep.assert_called_once_with(0.5)


class TestVerifyClaudeAuth:
    """Tests for verify_claude_auth function."""

    @pytest.mark.asyncio
    async def test_successful_auth(self, reset_config):
        """Test successful authentication."""
        mock_client = create_mock_client("ok")

        with patch("updater.claude_analyzer.ClaudeSDKClient", return_value=mock_client):
            success, error = await verify_claude_auth()

        assert success is True
        assert error == ""

    @pytest.mark.asyncio
    async def test_invalid_api_key_error(self, reset_config):
        """Test auth failure with invalid API key."""
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(side_effect=Exception("Invalid API key"))
        mock_client.__aexit__ = AsyncMock()

        with patch("updater.claude_analyzer.ClaudeSDKClient", return_value=mock_client):
            success, error = await verify_claude_auth()

        assert success is False
        assert "Claude authentication failed" in error
        assert "claude login" in error

    @pytest.mark.asyncio
    async def test_login_required_error(self, reset_config):
        """Test auth failure when login required."""
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(side_effect=Exception("Please run /login"))
        mock_client.__aexit__ = AsyncMock()

        with patch("updater.claude_analyzer.ClaudeSDKClient", return_value=mock_client):
            success, error = await verify_claude_auth()

        assert success is False
        assert "Claude authentication failed" in error

    @pytest.mark.asyncio
    async def test_other_error(self, reset_config):
        """Test other errors don't show login hint."""
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(side_effect=Exception("Network timeout"))
        mock_client.__aexit__ = AsyncMock()

        with patch("updater.claude_analyzer.ClaudeSDKClient", return_value=mock_client):
            success, error = await verify_claude_auth()

        assert success is False
        assert "Claude check failed" in error
        assert "Network timeout" in error


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

        mock_client = create_mock_client(response)
        mock_log = Mock()

        with patch("updater.claude_analyzer.ClaudeSDKClient", return_value=mock_client):
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

        mock_client = create_mock_client(response)
        mock_log = Mock()

        with patch("updater.claude_analyzer.ClaudeSDKClient", return_value=mock_client):
            result = await generate_changelog_from_commits(
                commits, "test-module", log_func=mock_log
            )

        assert result == ["Test entry"]

    @pytest.mark.asyncio
    async def test_empty_entries(self, reset_config):
        """Test handling empty entries response."""
        commits = [{"hash": "abc", "subject": "Minor fix", "body": ""}]

        response = json.dumps({"entries": []})

        mock_client = create_mock_client(response)
        mock_log = Mock()

        with patch("updater.claude_analyzer.ClaudeSDKClient", return_value=mock_client):
            result = await generate_changelog_from_commits(
                commits, "test-module", log_func=mock_log
            )

        assert result == []
