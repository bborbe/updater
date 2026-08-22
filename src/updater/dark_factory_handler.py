"""Infra-tier handler for bborbe/dark-factory's DefaultContainerImage constant."""

import re
from pathlib import Path

from .infra_tier import (
    InfraTargetError,
    process_infra_target,
    validate_claude_yolo_tag,
)
from .log_manager import log_message, run_command

DARK_FACTORY_REPO = "bborbe/dark-factory"
DARK_FACTORY_FILE = "pkg/const.go"
DARK_FACTORY_PATTERN = re.compile(
    r'DefaultContainerImage = "docker\.io/bborbe/claude-yolo:(v\d+\.\d+\.\d+)"'
)


def resolve_latest_claude_yolo_tag(checkout: Path) -> str:
    """Return the latest claude-yolo release tag (e.g. 'v0.16.0') via gh.

    Args:
        checkout: Path to the target checkout (used as the gh working directory)

    Returns:
        The latest release tag, validated as vX.Y.Z

    Raises:
        RuntimeError: gh failed (auth, network, rate limit).
        InfraTargetError: gh returned a tag that is not vX.Y.Z-shaped.
    """
    result = run_command(
        "gh release view -R bborbe/claude-yolo --json tagName --jq .tagName",
        cwd=checkout,
        capture_output=True,
        quiet=True,
        log_func=log_message,
    )
    tag = result.stdout.strip()
    if not validate_claude_yolo_tag(tag):
        raise InfraTargetError(f"unexpected claude-yolo release tag from gh: {tag!r}")
    return tag


class DarkFactoryHandler:
    """Bump DefaultContainerImage in bborbe/dark-factory pkg/const.go and open a PR."""

    def run(self, checkout: Path, *, dry_run: bool, claude_yolo_tag: str | None) -> int:
        """Resolve the target tag (explicit or from gh) and delegate to the shared helper.

        Args:
            checkout: Path to the bborbe/dark-factory checkout
            dry_run: If True, patch the working tree and show the diff only
            claude_yolo_tag: Explicit target tag, or None to resolve claude-yolo's
                latest GitHub release

        Returns:
            Exit code: 0 on success or no-op, 1 on any error
        """
        if claude_yolo_tag is None:
            try:
                claude_yolo_tag = resolve_latest_claude_yolo_tag(checkout)
                log_message(
                    f"→ Resolved latest claude-yolo release tag: {claude_yolo_tag}",
                    to_console=True,
                )
            except (RuntimeError, InfraTargetError) as e:
                log_message(f"✗ Cannot resolve claude-yolo's latest release: {e}", to_console=True)
                return 1
        if not validate_claude_yolo_tag(claude_yolo_tag):
            log_message(
                f"✗ Invalid claude-yolo tag: {claude_yolo_tag!r} (expected vX.Y.Z)",
                to_console=True,
            )
            return 1
        return process_infra_target(
            checkout,
            repo=DARK_FACTORY_REPO,
            target_file=DARK_FACTORY_FILE,
            pattern=DARK_FACTORY_PATTERN,
            new_value=claude_yolo_tag,
            branch_name=f"updater/dark-factory-{claude_yolo_tag}",
            title=f"chore: bump DefaultContainerImage to claude-yolo:{claude_yolo_tag}",
            body=f"Bump DefaultContainerImage to docker.io/bborbe/claude-yolo:{claude_yolo_tag}.",
            changelog_bullet=f"chore: bump DefaultContainerImage to claude-yolo:{claude_yolo_tag}",
            dry_run=dry_run,
        )
