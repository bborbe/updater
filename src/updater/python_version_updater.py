"""Python version updater for .python-version, pyproject.toml, and Dockerfile."""

import re
from collections.abc import Callable
from pathlib import Path

import httpx

from .log_manager import log_message


def get_latest_python_version() -> str | None:
    """Fetch the latest stable Python version.

    Returns the latest Python 3.x version as major.minor (e.g., "3.12").
    Checks python.org for the latest release.

    Returns:
        Version string like "3.12" or None if fetch fails
    """
    try:
        # Python.org downloads page lists versions
        response = httpx.get(
            "https://www.python.org/api/v2/downloads/release/?is_published=true&pre_release=false",
            timeout=10,
        )
        response.raise_for_status()

        releases = response.json()

        # Find highest 3.x version
        highest_version = None
        for release in releases:
            name = release.get("name", "")
            # Match "Python 3.12.1" format
            match = re.match(r"Python (\d+)\.(\d+)\.(\d+)", name)
            if match:
                major, minor, patch = int(match.group(1)), int(match.group(2)), int(match.group(3))
                if major == 3:
                    version_tuple = (major, minor, patch)
                    if highest_version is None or version_tuple > highest_version:
                        highest_version = version_tuple

        if highest_version:
            return f"{highest_version[0]}.{highest_version[1]}"

        return None
    except httpx.HTTPError:
        return None
    except KeyError, ValueError:
        return None


def update_python_version_file(
    module_path: Path, new_version: str, log_func: Callable[..., None] = log_message
) -> bool:
    """Update Python version in .python-version file.

    Only updates if the file already exists. Does not create the file.

    Args:
        module_path: Path to module
        new_version: New Python version (e.g., "3.12")
        log_func: Logging function

    Returns:
        True if file was updated, False otherwise
    """
    version_file = module_path / ".python-version"
    if not version_file.exists():
        return False

    current = version_file.read_text().strip()

    # Normalize to major.minor for comparison
    current_normalized = ".".join(current.split(".")[:2])

    if current_normalized == new_version:
        return False

    version_file.write_text(f"{new_version}\n")
    log_func(f"  → Updated .python-version: {new_version}", to_console=True)
    return True


def update_pyproject_python(
    module_path: Path, new_version: str, log_func: Callable[..., None] = log_message
) -> bool:
    """Update Python version in pyproject.toml.

    Updates:
    - requires-python = ">=X.Y"
    - [tool.ruff] target-version = "pyXY"
    - [tool.mypy] python_version = "X.Y"

    Args:
        module_path: Path to module
        new_version: New Python version (e.g., "3.12")
        log_func: Logging function

    Returns:
        True if file was updated, False otherwise
    """
    pyproject = module_path / "pyproject.toml"
    if not pyproject.exists():
        return False

    content = pyproject.read_text()
    original_content = content

    # Update requires-python = ">=3.11" or ">=3.11.0"
    pattern = r'requires-python\s*=\s*">=\d+\.\d+(?:\.\d+)?"'
    replacement = f'requires-python = ">={new_version}"'
    content = re.sub(pattern, replacement, content)

    # Update target-version = "py311" -> "py312"
    py_short = new_version.replace(".", "")
    pattern = r'target-version\s*=\s*"py\d+"'
    replacement = f'target-version = "py{py_short}"'
    content = re.sub(pattern, replacement, content)

    # Update python_version = "3.11" -> "3.12"
    pattern = r'python_version\s*=\s*"\d+\.\d+"'
    replacement = f'python_version = "{new_version}"'
    content = re.sub(pattern, replacement, content)

    if content != original_content:
        pyproject.write_text(content)
        log_func(f"  → Updated pyproject.toml: Python {new_version}", to_console=True)
        return True

    return False


def update_dockerfile_python(
    module_path: Path, new_version: str, log_func: Callable[..., None] = log_message
) -> bool:
    """Update Python version in Dockerfile.

    Updates FROM python:X.Y-variant statements.

    Args:
        module_path: Path to module
        new_version: New Python version (e.g., "3.12")
        log_func: Logging function

    Returns:
        True if file was updated, False otherwise
    """
    dockerfile = module_path / "Dockerfile"
    if not dockerfile.exists():
        return False

    content = dockerfile.read_text()
    original_content = content

    # Pattern: FROM python:3.11-slim or FROM python:3.11-alpine or FROM python:3.11-slim AS builder
    # Match python:X.Y with any suffix and optional AS clause
    pattern = r"FROM python:(\d+\.\d+)([-\w]*)(\s+AS\s+\w+)?"

    def replace_version(match: re.Match[str]) -> str:
        suffix = match.group(2) if match.group(2) else ""
        as_clause = match.group(3) if match.group(3) else ""
        return f"FROM python:{new_version}{suffix}{as_clause}"

    content = re.sub(pattern, replace_version, content)

    if content != original_content:
        dockerfile.write_text(content)
        log_func(f"  → Updated Dockerfile: python:{new_version}", to_console=True)
        return True

    return False


def update_python_versions(module_path: Path, log_func: Callable[..., None] = log_message) -> bool:
    """Check and update Python versions if needed.

    Updates .python-version, pyproject.toml, and Dockerfile.

    Args:
        module_path: Path to module
        log_func: Logging function

    Returns:
        True if any updates were made, False otherwise
    """
    log_func("\n=== Phase 1a: Check Python Versions ===", to_console=True)

    log_func("\n→ Checking Python version...", to_console=True)
    latest = get_latest_python_version()

    if not latest:
        log_func("  ⚠ Could not fetch latest Python version", to_console=True)
        return False

    log_func(f"  Latest Python: {latest}", to_console=True)

    any_updates = False

    # Update .python-version
    if update_python_version_file(module_path, latest, log_func):
        any_updates = True

    # Update pyproject.toml
    if update_pyproject_python(module_path, latest, log_func):
        any_updates = True

    # Update Dockerfile
    if update_dockerfile_python(module_path, latest, log_func):
        any_updates = True

    if any_updates:
        log_func("\n✓ Python versions updated", to_console=True)
    else:
        log_func("\n✓ Python versions are up to date", to_console=True)

    return any_updates
