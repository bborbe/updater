"""Tests for sound utilities."""

from unittest.mock import patch

from updater.sound import play_completion_sound, play_interaction_sound, play_sound


def test_play_sound_on_macos():
    """Test sound playback on macOS."""
    with patch("sys.platform", "darwin"):
        with patch("updater.sound.subprocess.Popen") as mock_popen:
            with patch("updater.sound.Path.exists", return_value=True):
                play_sound("/System/Library/Sounds/Ping.aiff")

                # Verify Popen was called with correct arguments
                assert mock_popen.called
                call_args = mock_popen.call_args[0][0]
                assert call_args[0] == "afplay"
                assert "/System/Library/Sounds/Ping.aiff" in call_args


def test_play_sound_on_non_macos():
    """Test that sound playback is skipped on non-macOS."""
    with patch("sys.platform", "linux"):
        with patch("updater.sound.subprocess.Popen") as mock_popen:
            play_sound("/System/Library/Sounds/Ping.aiff")

            # Verify Popen was NOT called
            assert not mock_popen.called


def test_play_sound_missing_file():
    """Test that missing sound files are handled gracefully."""
    with patch("sys.platform", "darwin"):
        with patch("updater.sound.subprocess.Popen") as mock_popen:
            with patch("updater.sound.Path.exists", return_value=False):
                play_sound("/nonexistent/sound.aiff")

                # Verify Popen was NOT called
                assert not mock_popen.called


def test_play_sound_afplay_not_found():
    """Test that missing afplay command is handled gracefully."""
    with patch("sys.platform", "darwin"):
        with patch("updater.sound.Path.exists", return_value=True):
            with patch("updater.sound.subprocess.Popen", side_effect=FileNotFoundError):
                # Should not raise exception
                play_sound("/System/Library/Sounds/Ping.aiff")


def test_play_interaction_sound():
    """Test interaction sound helper."""
    with patch("updater.sound.play_sound") as mock_play:
        play_interaction_sound()
        mock_play.assert_called_once_with("/System/Library/Sounds/Ping.aiff")


def test_play_completion_sound():
    """Test completion sound helper."""
    with patch("updater.sound.play_sound") as mock_play:
        play_completion_sound()
        mock_play.assert_called_once_with("/System/Library/Sounds/Glass.aiff")
