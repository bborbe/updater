"""Configuration constants for the updater."""

from typing import Optional
from typing import TextIO

# Logging configuration
LOG_RETENTION_COUNT = 5
LOG_DIR_NAME = ".update-logs"

# Global state (set by CLI) - Not thread-safe, CLI uses single-threaded execution only
VERBOSE_MODE = False
RUN_TIMESTAMP: Optional[str] = None
LOG_FILE_HANDLE: Optional[TextIO] = None
MODEL: Optional[str] = None  # Claude model to use (sonnet, opus, haiku)
REQUIRE_CONFIRM = False  # Require user confirmation before commits

# Go updater configuration
GO_MAX_ITERATIONS = 10

# Claude configuration
CLAUDE_SESSION_DELAY = 0.5  # seconds between sessions
