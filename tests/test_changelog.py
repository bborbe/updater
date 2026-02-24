"""Tests for changelog operations."""

import pytest

from updater.changelog import (
    bump_version,
    extract_current_version,
    get_unreleased_entries,
    promote_unreleased_to_version,
)
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


# ---------------------------------------------------------------------------
# get_unreleased_entries
# ---------------------------------------------------------------------------


def test_get_unreleased_entries_with_entries(tmp_path):
    """Test get_unreleased_entries returns bullet points under Unreleased."""
    changelog_path = tmp_path / "CHANGELOG.md"
    changelog_path.write_text(
        """# Changelog

## Unreleased

- Add new feature
- Fix critical bug

## v1.0.0

- Initial release
"""
    )

    entries = get_unreleased_entries(changelog_path)
    assert entries == ["- Add new feature", "- Fix critical bug"]


def test_get_unreleased_entries_empty_unreleased(tmp_path):
    """Test get_unreleased_entries returns None when Unreleased section is empty."""
    changelog_path = tmp_path / "CHANGELOG.md"
    changelog_path.write_text(
        """# Changelog

## Unreleased

## v1.0.0

- Initial release
"""
    )

    entries = get_unreleased_entries(changelog_path)
    assert entries is None


def test_get_unreleased_entries_no_unreleased_section(tmp_path):
    """Test get_unreleased_entries returns None when no Unreleased section exists."""
    changelog_path = tmp_path / "CHANGELOG.md"
    changelog_path.write_text(
        """# Changelog

## v1.0.0

- Initial release
"""
    )

    entries = get_unreleased_entries(changelog_path)
    assert entries is None


def test_get_unreleased_entries_no_changelog(tmp_path):
    """Test get_unreleased_entries returns None when CHANGELOG.md does not exist."""
    changelog_path = tmp_path / "CHANGELOG.md"

    entries = get_unreleased_entries(changelog_path)
    assert entries is None


def test_get_unreleased_entries_custom_title(tmp_path):
    """Test get_unreleased_entries finds entries under any non-version title."""
    changelog_path = tmp_path / "CHANGELOG.md"
    changelog_path.write_text(
        """# Changelog

## Banana

- Add new feature
- Fix critical bug

## v1.0.0

- Initial release
"""
    )

    entries = get_unreleased_entries(changelog_path)
    assert entries == ["- Add new feature", "- Fix critical bug"]


def test_get_unreleased_entries_prefers_first_non_version(tmp_path):
    """Test get_unreleased_entries finds first non-version section."""
    changelog_path = tmp_path / "CHANGELOG.md"
    changelog_path.write_text(
        """# Changelog

## WIP Changes

- Work in progress

## v1.0.0

- Initial release
"""
    )

    entries = get_unreleased_entries(changelog_path)
    assert entries == ["- Work in progress"]


# ---------------------------------------------------------------------------
# promote_unreleased_to_version
# ---------------------------------------------------------------------------


def test_promote_unreleased_to_version_success(tmp_path):
    """Test promote_unreleased_to_version replaces header correctly."""
    changelog_path = tmp_path / "CHANGELOG.md"
    changelog_path.write_text(
        """# Changelog

## Unreleased

- Add new feature
- Fix critical bug

## v1.0.0

- Initial release
"""
    )

    promote_unreleased_to_version(changelog_path, "v1.1.0")

    content = changelog_path.read_text()
    assert "## v1.1.0" in content
    assert "## Unreleased" not in content
    assert "- Add new feature" in content
    assert "- Fix critical bug" in content


def test_promote_unreleased_to_version_no_file(tmp_path):
    """Test promote_unreleased_to_version raises when file missing."""
    changelog_path = tmp_path / "CHANGELOG.md"

    with pytest.raises(ChangelogError, match="CHANGELOG.md not found"):
        promote_unreleased_to_version(changelog_path, "v1.1.0")


def test_promote_unreleased_to_version_no_unreleased_section(tmp_path):
    """Test promote_unreleased_to_version raises when no unreleased section."""
    changelog_path = tmp_path / "CHANGELOG.md"
    changelog_path.write_text(
        """# Changelog

## v1.0.0

- Initial release
"""
    )

    with pytest.raises(ChangelogError, match="No unreleased section"):
        promote_unreleased_to_version(changelog_path, "v1.1.0")


def test_promote_unreleased_to_version_custom_title(tmp_path):
    """Test promote_unreleased_to_version replaces custom title with version."""
    changelog_path = tmp_path / "CHANGELOG.md"
    changelog_path.write_text(
        """# Changelog

## Banana

- Add new feature
- Fix critical bug

## v1.0.0

- Initial release
"""
    )

    promote_unreleased_to_version(changelog_path, "v1.1.0")

    content = changelog_path.read_text()
    assert "## v1.1.0" in content
    assert "## Banana" not in content
    assert "- Add new feature" in content
    assert "- Fix critical bug" in content


def test_promote_unreleased_to_version_wip_title(tmp_path):
    """Test promote_unreleased_to_version replaces WIP title with version."""
    changelog_path = tmp_path / "CHANGELOG.md"
    changelog_path.write_text(
        """# Changelog

## WIP Changes

- Work in progress

## v1.0.0

- Initial release
"""
    )

    promote_unreleased_to_version(changelog_path, "v1.1.0")

    content = changelog_path.read_text()
    assert "## v1.1.0" in content
    assert "## WIP Changes" not in content
    assert "- Work in progress" in content
