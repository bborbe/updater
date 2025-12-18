"""Configuration constants for the updater."""

from pathlib import Path

# Logging configuration
LOG_RETENTION_COUNT = 5
LOG_DIR_NAME = ".update-logs"

# Global state (set by CLI)
VERBOSE_MODE = False
RUN_TIMESTAMP = None
LOG_FILE_HANDLE = None
MODEL = None  # Claude model to use (sonnet, opus, haiku)
REQUIRE_CONFIRM = False  # Require user confirmation before commits

# Go updater configuration
GO_MAX_ITERATIONS = 10

# Claude configuration
CLAUDE_SESSION_DELAY = 0.5  # seconds between sessions
