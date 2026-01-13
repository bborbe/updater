"""Version updater for golang, alpine, and other runtime dependencies."""

import json
import re
from collections.abc import Callable
from pathlib import Path

import httpx
import yaml

from .log_manager import log_message


def get_latest_golang_version() -> str | None:
    """Fetch the latest stable golang version from go.dev.

    Returns:
        Version string like "1.23.5" or None if fetch fails
    """
    try:
        response = httpx.get("https://go.dev/dl/?mode=json", timeout=10)
        response.raise_for_status()

        versions = json.loads(response.text)
        if versions and len(versions) > 0:
            # First entry is the latest stable version
            version = versions[0].get("version", "")
            # Remove "go" prefix: "go1.23.5" -> "1.23.5"
            return version.removeprefix("go")

        return None
    except httpx.HTTPError:
        # Network error, timeout, or HTTP error - silently return None
        return None
    except (json.JSONDecodeError, KeyError, IndexError):
        # Invalid response format - silently return None
        return None


def get_latest_alpine_version() -> str | None:
    """Fetch the latest stable alpine version.

    Returns:
        Version string like "3.20.3" or None if fetch fails
    """
    try:
        response = httpx.get(
            "https://dl-cdn.alpinelinux.org/alpine/latest-stable/releases/x86_64/latest-releases.yaml",
            timeout=10,
        )
        response.raise_for_status()

        releases = yaml.safe_load(response.text)

        # Find the "alpine-minirootfs" entry (most common for Docker)
        for release in releases:
            if release.get("flavor") == "alpine-minirootfs":
                version = release.get("version", "")
                # Remove minor patch: "3.20.3" -> "3.20"
                parts = version.split(".")
                if len(parts) >= 2:
                    return f"{parts[0]}.{parts[1]}"

        return None
    except httpx.HTTPError:
        # Network error, timeout, or HTTP error - silently return None
        return None
    except (yaml.YAMLError, KeyError, AttributeError):
        # Invalid YAML or unexpected structure - silently return None
        return None


def update_dockerfile_golang(
    module_path: Path, new_version: str, log_func: Callable[..., None] = log_message
) -> bool:
    """Update golang version in Dockerfile.

    Args:
        module_path: Path to module
        new_version: New golang version (e.g., "1.23.5")
        log_func: Logging function

    Returns:
        True if file was updated, False otherwise
    """
    dockerfile = module_path / "Dockerfile"
    if not dockerfile.exists():
        return False

    content = dockerfile.read_text()
    original_content = content

    # Pattern: FROM golang:1.23.4 or FROM golang:1.23.4-alpine3.20 or FROM golang:1.23.4 AS build
    # Replace with new version but keep any suffix and AS clause
    pattern = r"FROM golang:(\d+\.\d+\.\d+)([-\w.]*)(\s+AS\s+\w+)?"

    def replace_version(match: re.Match[str]) -> str:
        suffix = match.group(2) if match.group(2) else ""
        as_clause = match.group(3) if match.group(3) else ""
        return f"FROM golang:{new_version}{suffix}{as_clause}"

    content = re.sub(pattern, replace_version, content)

    if content != original_content:
        dockerfile.write_text(content)
        log_func(f"  → Updated Dockerfile: golang:{new_version}", to_console=True)
        return True

    return False


def update_dockerfile_alpine(
    module_path: Path, new_version: str, log_func: Callable[..., None] = log_message
) -> bool:
    """Update alpine version in Dockerfile.

    Args:
        module_path: Path to module
        new_version: New alpine version (e.g., "3.20")
        log_func: Logging function

    Returns:
        True if file was updated, False otherwise
    """
    dockerfile = module_path / "Dockerfile"
    if not dockerfile.exists():
        return False

    content = dockerfile.read_text()
    original_content = content

    # Pattern: FROM alpine:3.19 or FROM alpine:3.19.1 or FROM alpine:3.19 AS alpine
    pattern = r"FROM alpine:(\d+\.\d+(?:\.\d+)?)(\s+AS\s+\w+)?"

    def replace_version(match: re.Match[str]) -> str:
        as_clause = match.group(2) if match.group(2) else ""
        return f"FROM alpine:{new_version}{as_clause}"

    content = re.sub(pattern, replace_version, content)

    if content != original_content:
        dockerfile.write_text(content)
        log_func(f"  → Updated Dockerfile: alpine:{new_version}", to_console=True)
        return True

    return False


def update_gomod_version(
    module_path: Path, new_version: str, log_func: Callable[..., None] = log_message
) -> bool:
    """Update go version in go.mod.

    Args:
        module_path: Path to module
        new_version: New go version (e.g., "1.23.5")
        log_func: Logging function

    Returns:
        True if file was updated, False otherwise
    """
    gomod = module_path / "go.mod"
    if not gomod.exists():
        return False

    content = gomod.read_text()

    # Pattern: go 1.23 or go 1.23.4
    pattern = r"^go (\d+\.\d+(?:\.\d+)?)$"

    lines = content.split("\n")
    updated = False

    for i, line in enumerate(lines):
        match = re.match(pattern, line)
        if match:
            current = match.group(1)

            # Compare versions - if different, update to new_version
            if current != new_version:
                lines[i] = f"go {new_version}"
                updated = True
                break

    if updated:
        content = "\n".join(lines)
        gomod.write_text(content)
        log_func(f"  → Updated go.mod: go {new_version}", to_console=True)
        return True

    return False


def update_github_workflows_golang(
    module_path: Path, new_version: str, log_func: Callable[..., None] = log_message
) -> bool:
    """Update golang version in GitHub Actions workflows.

    Args:
        module_path: Path to module
        new_version: New go version (e.g., "1.23.5")
        log_func: Logging function

    Returns:
        True if any files were updated, False otherwise
    """
    workflows_dir = module_path / ".github" / "workflows"
    if not workflows_dir.exists():
        return False

    any_updates = False

    for workflow_file in workflows_dir.glob("*.yml"):
        content = workflow_file.read_text()
        original_content = content

        # Pattern: go-version: '1.23.4' or go-version: "1.23.4" or go-version: 1.23.4
        pattern = r"go-version:\s*['\"]?(\d+\.\d+\.\d+)['\"]?"

        def replace_version(match: re.Match[str]) -> str:
            # Preserve the quote style (or lack thereof)
            if "'" in match.group(0):
                return f"go-version: '{new_version}'"
            elif '"' in match.group(0):
                return f'go-version: "{new_version}"'
            else:
                return f"go-version: {new_version}"

        content = re.sub(pattern, replace_version, content)

        if content != original_content:
            workflow_file.write_text(content)
            log_func(
                f"  → Updated {workflow_file.name}: go-version: {new_version}",
                to_console=True,
            )
            any_updates = True

    return any_updates


def update_versions(module_path: Path, log_func: Callable[..., None] = log_message) -> bool:
    """Check and update golang and alpine versions if needed.

    Args:
        module_path: Path to module
        log_func: Logging function

    Returns:
        True if any updates were made, False otherwise
    """
    log_func("\n=== Phase 1a: Check Runtime Versions ===", to_console=True)

    any_updates = False

    # Check golang version
    log_func("\n→ Checking golang version...", to_console=True)
    latest_go = get_latest_golang_version()

    if latest_go:
        log_func(f"  Latest golang: {latest_go}", to_console=True)

        # Update go.mod
        if update_gomod_version(module_path, latest_go, log_func):
            any_updates = True

        # Update Dockerfile
        if update_dockerfile_golang(module_path, latest_go, log_func):
            any_updates = True

        # Update GitHub workflows
        if update_github_workflows_golang(module_path, latest_go, log_func):
            any_updates = True
    else:
        log_func("  ⚠ Could not fetch latest golang version", to_console=True)

    # Check alpine version
    log_func("\n→ Checking alpine version...", to_console=True)
    latest_alpine = get_latest_alpine_version()

    if latest_alpine:
        log_func(f"  Latest alpine: {latest_alpine}", to_console=True)

        # Update Dockerfile
        if update_dockerfile_alpine(module_path, latest_alpine, log_func):
            any_updates = True
    else:
        log_func("  ⚠ Could not fetch latest alpine version", to_console=True)

    if any_updates:
        log_func("\n✓ Runtime versions updated", to_console=True)
    else:
        log_func("\n✓ Runtime versions are up to date", to_console=True)

    return any_updates
