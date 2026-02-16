"""CHANGELOG parsing, version bumping, and updates."""

import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .exceptions import ChangelogError


def get_unreleased_entries(changelog_path: Path) -> list[str] | None:
    """Parse CHANGELOG.md and return bullet points under ## Unreleased.

    Args:
        changelog_path: Path to CHANGELOG.md

    Returns:
        List of bullet point strings, or None if no Unreleased section or empty
    """
    if not changelog_path.exists():
        return None

    with open(changelog_path) as f:
        lines = f.readlines()

    # Find ## Unreleased section
    unreleased_idx = None
    for i, line in enumerate(lines):
        if line.strip() == "## Unreleased":
            unreleased_idx = i
            break

    if unreleased_idx is None:
        return None

    # Collect bullet points until next ## section or end of file
    entries: list[str] = []
    for line in lines[unreleased_idx + 1 :]:
        stripped = line.strip()
        if stripped.startswith("## "):
            break
        if stripped.startswith("- "):
            entries.append(stripped)

    return entries if entries else None


def promote_unreleased_to_version(changelog_path: Path, new_version: str) -> None:
    """Replace ## Unreleased header with a versioned header.

    Replaces the `## Unreleased` line with `## {new_version}`, keeping
    all the bullet points in place.

    Args:
        changelog_path: Path to CHANGELOG.md
        new_version: Version string (e.g., "v1.7.0")

    Raises:
        ChangelogError: If CHANGELOG.md not found or no Unreleased section
    """
    if not changelog_path.exists():
        raise ChangelogError(f"CHANGELOG.md not found at {changelog_path}")

    with open(changelog_path) as f:
        content = f.read()

    if "## Unreleased" not in content:
        raise ChangelogError("No ## Unreleased section found in CHANGELOG.md")

    content = content.replace("## Unreleased", f"## {new_version}", 1)

    with open(changelog_path, "w") as f:
        f.write(content)


def extract_current_version(changelog_path: Path) -> tuple[int, int, int]:
    """Extract current version from CHANGELOG.md.

    Args:
        changelog_path: Path to CHANGELOG.md

    Returns:
        Tuple of (major, minor, patch) version numbers

    Raises:
        ChangelogError: If version cannot be found or parsed
    """
    if not changelog_path.exists():
        raise ChangelogError(f"CHANGELOG.md not found at {changelog_path}")

    with open(changelog_path) as f:
        content = f.read()

    version_match = re.search(r"##\s+v(\d+)\.(\d+)\.(\d+)", content)
    if not version_match:
        raise ChangelogError("Could not find version in CHANGELOG.md")

    major = int(version_match.group(1))
    minor = int(version_match.group(2))
    patch = int(version_match.group(3))

    return major, minor, patch


def bump_version(major: int, minor: int, patch: int, bump_type: str) -> str:
    """Calculate new version based on bump type.

    Args:
        major: Current major version
        minor: Current minor version
        patch: Current patch version
        bump_type: One of "major", "minor", or "patch"

    Returns:
        New version string (e.g., "v1.2.3")

    Raises:
        ValueError: If bump_type is invalid
    """
    bump_type = bump_type.lower()

    if bump_type == "major":
        major += 1
        minor = 0
        patch = 0
    elif bump_type == "minor":
        minor += 1
        patch = 0
    elif bump_type == "patch":
        patch += 1
    else:
        raise ValueError(f"Invalid bump_type: {bump_type}. Must be major, minor, or patch")

    return f"v{major}.{minor}.{patch}"


def add_to_unreleased(
    module_path: Path, analysis: dict[str, Any], log_func: Callable[..., None]
) -> None:
    """Add changes to ## Unreleased section (for --no-tag mode).

    Args:
        module_path: Path to module
        analysis: Dict with keys: changelog
        log_func: Logging function to use

    Raises:
        ChangelogError: If CHANGELOG operations fail
    """
    from . import config

    log_func("\n=== Phase 4: Update CHANGELOG (Unreleased) ===", to_console=True)

    changelog_path = Path(module_path) / "CHANGELOG.md"

    if not changelog_path.exists():
        log_func(f"⚠ No CHANGELOG.md found at {changelog_path}, skipping", to_console=True)
        return

    # Read current CHANGELOG
    log_func("→ Reading current CHANGELOG", to_console=config.VERBOSE_MODE)
    with open(changelog_path) as f:
        content = f.read()

    # Format changelog bullets
    changelog_bullets = "\n".join(f"- {bullet.lstrip('- ')}" for bullet in analysis["changelog"])

    log_func("\n  Adding to Unreleased:", to_console=config.VERBOSE_MODE)
    for bullet in analysis["changelog"]:
        log_func(f"    - {bullet.lstrip('- ')}", to_console=config.VERBOSE_MODE)

    lines = content.split("\n")

    # Find or create ## Unreleased section
    unreleased_idx = None
    first_version_idx = None

    for i, line in enumerate(lines):
        if line.strip() == "## Unreleased":
            unreleased_idx = i
            break
        if line.startswith("## v") and first_version_idx is None:
            first_version_idx = i

    if unreleased_idx is not None:
        # Unreleased section exists - append to it
        # Find the end of existing entries (next ## section or empty line)
        insert_idx = unreleased_idx + 1
        # Skip blank lines after ## Unreleased
        while insert_idx < len(lines) and lines[insert_idx].strip() == "":
            insert_idx += 1
        # Find where existing bullets end
        while insert_idx < len(lines) and lines[insert_idx].strip().startswith("-"):
            insert_idx += 1
        # Insert new bullets before the blank line
        lines.insert(insert_idx, changelog_bullets)
    else:
        # Create ## Unreleased section before first version
        if first_version_idx is not None:
            new_entry = f"## Unreleased\n\n{changelog_bullets}\n"
            lines.insert(first_version_idx, new_entry)
        else:
            # No versions exist - append after preamble
            # Find end of preamble (last non-empty line before we'd insert)
            insert_idx = len(lines)
            for i in range(len(lines) - 1, -1, -1):
                if lines[i].strip():
                    insert_idx = i + 1
                    break
            new_entry = f"\n## Unreleased\n\n{changelog_bullets}\n"
            lines.insert(insert_idx, new_entry)

    # Write back
    with open(changelog_path, "w") as f:
        f.write("\n".join(lines))

    log_func("\n✓ Changes added to ## Unreleased", to_console=True)


def update_changelog_with_suggestions(
    module_path: Path, analysis: dict[str, Any], log_func: Callable[..., None]
) -> str | None:
    """Update CHANGELOG.md with suggested changes.

    Args:
        module_path: Path to module
        analysis: Dict with keys: version_bump, changelog, commit_message
        log_func: Logging function to use

    Returns:
        New version string, or None if no CHANGELOG found

    Raises:
        ChangelogError: If CHANGELOG operations fail
    """
    from . import config

    log_func("\n=== Phase 4: Update CHANGELOG ===", to_console=True)

    changelog_path = Path(module_path) / "CHANGELOG.md"

    if not changelog_path.exists():
        log_func(f"⚠ No CHANGELOG.md found at {changelog_path}, skipping", to_console=True)
        return None

    # Read current CHANGELOG
    log_func("→ Reading current CHANGELOG", to_console=config.VERBOSE_MODE)
    with open(changelog_path) as f:
        content = f.read()

    # Extract current version
    major, minor, patch = extract_current_version(changelog_path)
    old_version = f"v{major}.{minor}.{patch}"

    # Calculate new version
    new_version = bump_version(major, minor, patch, analysis["version_bump"])

    log_func(f"  Current version: {old_version}", to_console=config.VERBOSE_MODE)
    log_func(f"  Version bump: {analysis['version_bump']}", to_console=config.VERBOSE_MODE)
    log_func(f"  New version: {new_version}", to_console=config.VERBOSE_MODE)

    # Format changelog bullets
    changelog_bullets = "\n".join(f"- {bullet.lstrip('- ')}" for bullet in analysis["changelog"])

    log_func("\n  Changelog entry:", to_console=config.VERBOSE_MODE)
    for bullet in analysis["changelog"]:
        log_func(f"    - {bullet.lstrip('- ')}", to_console=config.VERBOSE_MODE)

    # Insert new version section
    lines = content.split("\n")

    insert_idx = 0
    for i, line in enumerate(lines):
        if line.startswith("## v"):
            insert_idx = i
            break

    new_entry = f"## {new_version}\n\n{changelog_bullets}\n"
    lines.insert(insert_idx, new_entry)

    # Write back
    with open(changelog_path, "w") as f:
        f.write("\n".join(lines))

    log_func(f"\n✓ CHANGELOG updated to {new_version}", to_console=True)

    return new_version
