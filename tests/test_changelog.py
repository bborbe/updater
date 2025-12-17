"""Tests for changelog operations."""

import pytest
from pathlib import Path
from updater.changelog import extract_current_version, bump_version
from updater.exceptions import ChangelogError


def test_bump_version_patch():
    """Test patch version bump."""
    result = bump_version(1, 2, 3, "patch")
    assert result == "v1.2.4"


def test_bump_version_minor():
    """Test minor version bump resets patch."""
    result = bump_version(1, 2, 3, "minor")
    assert result == "v1.3.0"


def test_bump_version_major():
    """Test major version bump resets minor and patch."""
    result = bump_version(1, 2, 3, "major")
    assert result == "v2.0.0"


def test_bump_version_invalid():
    """Test invalid bump type raises ValueError."""
    with pytest.raises(ValueError, match="Invalid bump_type"):
        bump_version(1, 2, 3, "invalid")


def test_extract_current_version_missing_file(tmp_path):
    """Test extract_current_version with missing file."""
    changelog_path = tmp_path / "CHANGELOG.md"

    with pytest.raises(ChangelogError, match="CHANGELOG.md not found"):
        extract_current_version(changelog_path)


def test_extract_current_version_success(tmp_path):
    """Test extract_current_version with valid CHANGELOG."""
    changelog_path = tmp_path / "CHANGELOG.md"
    changelog_path.write_text("""# Changelog

## v1.2.3

- Some change

## v1.2.2

- Previous change
""")

    major, minor, patch = extract_current_version(changelog_path)
    assert major == 1
    assert minor == 2
    assert patch == 3


def test_extract_current_version_no_version(tmp_path):
    """Test extract_current_version with no version in CHANGELOG."""
    changelog_path = tmp_path / "CHANGELOG.md"
    changelog_path.write_text("# Changelog\n\nNo versions here!")

    with pytest.raises(ChangelogError, match="Could not find version"):
        extract_current_version(changelog_path)
