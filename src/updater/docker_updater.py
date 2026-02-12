"""Standalone Docker image updater."""

import re
from collections.abc import Callable
from pathlib import Path

from .log_manager import log_message
from .python_version_updater import get_latest_python_version
from .version_updater import get_latest_alpine_version, get_latest_golang_version


def parse_dockerfile_images(dockerfile_path: Path) -> list[dict]:
    """Parse FROM statements from a Dockerfile.

    Args:
        dockerfile_path: Path to Dockerfile

    Returns:
        List of dicts with keys: image, tag, as_name, line_num, full_match
    """
    if not dockerfile_path.exists():
        return []

    content = dockerfile_path.read_text()
    images = []

    # Pattern: FROM image:tag [AS name]
    # image can include registry (ghcr.io/user/repo)
    pattern = r"^FROM\s+([\w./-]+)(?::([^\s]+))?(?:\s+AS\s+(\w+))?\s*$"

    for line_num, line in enumerate(content.split("\n"), 1):
        match = re.match(pattern, line, re.IGNORECASE)
        if match:
            image = match.group(1)
            tag = match.group(2)
            as_name = match.group(3)

            images.append(
                {
                    "image": image,
                    "tag": tag,
                    "as_name": as_name,
                    "line_num": line_num,
                    "full_match": line,
                }
            )

    return images


def _get_version_for_image(image: str) -> tuple[str | None, str]:
    """Get the latest version for a known image.

    Args:
        image: Image name (e.g., "golang", "python", "alpine")

    Returns:
        Tuple of (version, version_type) where version_type describes how to apply it.
        Returns (None, "") if image is not supported.
    """
    if image == "golang":
        return get_latest_golang_version(), "full"  # Replace full version X.Y.Z
    elif image == "python":
        return get_latest_python_version(), "major_minor"  # Replace X.Y
    elif image == "alpine":
        return get_latest_alpine_version(), "major_minor"  # Replace X.Y
    elif image == "node":
        # Node version fetching not implemented yet
        return None, ""
    elif image == "scratch":
        return None, ""  # scratch has no version
    else:
        return None, ""


def _update_image_tag(current_tag: str | None, new_version: str, version_type: str) -> str:
    """Update image tag with new version while preserving suffix.

    Args:
        current_tag: Current tag (e.g., "3.11-slim", "1.23.4-alpine3.20")
        new_version: New version to apply
        version_type: How to apply version ("full" or "major_minor")

    Returns:
        Updated tag
    """
    if not current_tag:
        return new_version

    if version_type == "full":
        # Replace X.Y.Z, keep suffix like -alpine3.20
        pattern = r"^\d+\.\d+\.\d+"
        return re.sub(pattern, new_version, current_tag)
    elif version_type == "major_minor":
        # Replace X.Y, keep suffix like -slim
        pattern = r"^\d+\.\d+"
        return re.sub(pattern, new_version, current_tag)

    return current_tag


def update_dockerfile_images(
    module_path: Path, log_func: Callable[..., None] = log_message
) -> tuple[bool, list[str]]:
    """Update all known base images in Dockerfile to latest versions.

    Supports: golang, python, alpine

    Args:
        module_path: Path to module containing Dockerfile
        log_func: Logging function

    Returns:
        Tuple of (updated: bool, updates: list[str]) where updates contains
        human-readable update descriptions like "golang:1.25.7 → golang:1.26.0"
    """
    dockerfile = module_path / "Dockerfile"
    if not dockerfile.exists():
        return False, []

    log_func("\n=== Docker Image Updates ===", to_console=True)

    images = parse_dockerfile_images(dockerfile)
    if not images:
        log_func("  No FROM statements found", to_console=True)
        return False, []

    content = dockerfile.read_text()
    original_content = content
    updates_made = []

    for img in images:
        image_name = img["image"]
        current_tag = img["tag"]

        # Get latest version for this image
        new_version, version_type = _get_version_for_image(image_name)

        if not new_version:
            continue  # Unknown image or no update available

        # Calculate new tag
        new_tag = _update_image_tag(current_tag, new_version, version_type)

        if new_tag == current_tag:
            continue  # Already up to date

        # Build old and new FROM lines
        old_from = img["full_match"]
        as_clause = f" AS {img['as_name']}" if img["as_name"] else ""
        new_from = f"FROM {image_name}:{new_tag}{as_clause}"

        # Replace in content
        content = content.replace(old_from, new_from)
        updates_made.append(f"{image_name}:{current_tag} → {image_name}:{new_tag}")

    if content != original_content:
        dockerfile.write_text(content)
        for update in updates_made:
            log_func(f"  → {update}", to_console=True)
        log_func("\n✓ Dockerfile images updated", to_console=True)
        return True, updates_made

    log_func("✓ Dockerfile images are up to date", to_console=True)
    return False, []
