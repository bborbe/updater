"""Infra-tier handler for bborbe/claude-yolo's Dockerfile ARG GO_VERSION."""

import re
from pathlib import Path

from .infra_tier import process_infra_target, validate_go_version
from .log_manager import log_message

CLAUDE_YOLO_REPO = "bborbe/claude-yolo"
CLAUDE_YOLO_FILE = "Dockerfile"
CLAUDE_YOLO_PATTERN = re.compile(r"^ARG GO_VERSION=(\d+\.\d+\.\d+)$")


class ClaudeYoloHandler:
    """Bump ARG GO_VERSION in the bborbe/claude-yolo Dockerfile and open a PR."""

    def run(self, checkout: Path, *, dry_run: bool, go_version: str) -> int:
        if not validate_go_version(go_version):
            log_message(f"✗ Invalid Go version: {go_version!r} (expected X.Y.Z)", to_console=True)
            return 1
        return process_infra_target(
            checkout,
            repo=CLAUDE_YOLO_REPO,
            target_file=CLAUDE_YOLO_FILE,
            pattern=CLAUDE_YOLO_PATTERN,
            new_value=go_version,
            branch_name=f"updater/claude-yolo-{go_version}",
            title=f"chore: bump Go version to {go_version} in Dockerfile",
            body=f"Bump ARG GO_VERSION to {go_version}.",
            changelog_bullet=f"chore: bump Go version to {go_version} in Dockerfile",
            dry_run=dry_run,
        )
