"""Sound notification utilities."""

import subprocess
import sys
from pathlib import Path


def play_sound(sound_file: str) -> None:
    """Play a system sound using afplay (macOS only).

    Args:
        sound_file: Path to the sound file to play

    Note:
        - Fails silently if afplay is not available (non-macOS)
        - Plays sound in background (non-blocking)
    """
    if sys.platform != "darwin":
        return  # Only works on macOS

    sound_path = Path(sound_file)
    if not sound_path.exists():
        return  # Sound file doesn't exist

    try:
        # Play sound in background (non-blocking)
        subprocess.Popen(
            ["afplay", str(sound_path)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,  # Detach from parent to prevent asyncio waitpid hang
        )
    except (FileNotFoundError, subprocess.SubprocessError):
        # afplay not available or failed - fail silently
        pass


def play_interaction_sound() -> None:
    """Play sound when user interaction is needed."""
    play_sound("/System/Library/Sounds/Ping.aiff")


def play_completion_sound() -> None:
    """Play sound when task completes."""
    play_sound("/System/Library/Sounds/Glass.aiff")


def play_error_sound() -> None:
    """Play sound when an error occurs."""
    play_sound("/System/Library/Sounds/Sosumi.aiff")
