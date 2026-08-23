"""Configuration constants for the updater."""

from pathlib import Path
from typing import TextIO

# Logging configuration
LOG_RETENTION_COUNT = 5
LOG_DIR_NAME = ".update-logs"

# Global state (set by CLI) - Not thread-safe, CLI uses single-threaded execution only
VERBOSE_MODE = False
RUN_TIMESTAMP: str | None = None
LOG_FILE_HANDLE: TextIO | None = None
MODEL: str | None = None  # Claude model to use (sonnet, opus, haiku)
REQUIRE_CONFIRM = False  # Require user confirmation before commits
NO_TAG = False  # Add to Unreleased instead of creating version/tag
YES_MODE = False  # Auto-accept all prompts (non-interactive mode, for CI/containers)
CHECK_COMMAND: str = ""  # Override precommit command (empty = use default "make precommit")
NO_GIT = False  # Skip all git operations (for containers without .git access)

# Go updater configuration
GO_MAX_ITERATIONS = 10

# Claude configuration
CLAUDE_SESSION_DELAY = 0.5  # seconds between sessions

# Weekly digest configuration
# Fleet of repos the weekly digest queries (operator-maintained — mirror the
# github-update-go-watcher REPO_ALLOWLIST plus repos with goUpdate.autoUpdate: true).
DIGEST_FLEET_REPOS: list[str] = [
    "bborbe/agent",
    "bborbe/coding",
    "bborbe/dark-factory",
    "bborbe/github-build-watcher",
    "bborbe/github-pr-watcher",
    "bborbe/github-release-watcher",
    "bborbe/github-update-go-watcher",
    "bborbe/go-version-watcher",
    "bborbe/maintainer",
    "bborbe/sentry-watcher",
    "bborbe/task-watcher",
    "bborbe/updater",
    "bborbe/vault-cli",
]
# Directory of park-list JSON files (github-update-go-agent plan outputs with
# Outcome="needs_input" / PlanVuln.Action="park"). REQUIRED for spec AC2 (surfaces
# parked advisories) — the operator MUST confirm this points at the agent's plan outputs
# before AC verification (see requirement 9).
DIGEST_PARK_LIST_DIR: Path | None = Path.home() / "Documents/OpenClaw/plans"
# Task directories scanned for human_review-flagged tasks (vault 24 Tasks/ + OpenClaw/tasks/).
DIGEST_HUMAN_REVIEW_DIRS: list[Path] = [
    Path.home() / "Documents/Obsidian/Personal/24 Tasks",
    Path.home() / "Documents/Obsidian/OpenClaw/tasks",
]

# Weekly digest delivery configuration
DIGEST_EMAIL_TO: str = ""  # recipient for the weekly digest email (gog gmail send --to; gog auto-selects the send-as account)
DIGEST_SLACK_WEBHOOK: str | None = None  # when set, digest delivers to Slack instead of email
DIGEST_DELIVERY_LOG_DIR: Path | None = (
    None  # delivery markers; default <workdir>/.update-logs/digest
)
DIGEST_WEEKLY_CRON: str = "0 9 * * 1"  # Monday 09:00
