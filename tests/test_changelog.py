"""Tests for changelog operations."""

import pytest

from updater.changelog import (
    add_to_unreleased,
    bump_version,
    drain_unreleased_section,
    extract_current_version,
    get_unreleased_entries,
    promote_unreleased_to_version,
    update_changelog_with_suggestions,
)
from updater.exceptions import ChangelogError


def noop_log(*args, **kwargs):
    """No-op log function for testing."""


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


# ---------------------------------------------------------------------------
# add_to_unreleased
# ---------------------------------------------------------------------------


def test_add_to_unreleased_no_changelog(tmp_path):
    """Test add_to_unreleased logs warning and returns when CHANGELOG.md missing."""
    logged = []

    def log_func(*args, **kwargs):
        logged.append(args[0] if args else "")

    add_to_unreleased(tmp_path, {"changelog": ["Fix bug"]}, log_func)

    assert any("skipping" in msg or "No CHANGELOG" in msg for msg in logged)
    assert not (tmp_path / "CHANGELOG.md").exists()


def test_add_to_unreleased_existing_unreleased_section(tmp_path):
    """Test add_to_unreleased appends bullets to existing ## Unreleased section."""
    changelog_path = tmp_path / "CHANGELOG.md"
    changelog_path.write_text(
        """# Changelog

## Unreleased

- Existing entry

## v1.0.0

- Initial release
"""
    )

    add_to_unreleased(tmp_path, {"changelog": ["Add new feature", "Fix critical bug"]}, noop_log)

    content = changelog_path.read_text()
    assert "## Unreleased" in content
    assert "- Existing entry" in content
    assert "- Add new feature" in content
    assert "- Fix critical bug" in content
    # New bullets should appear before the version header
    unreleased_pos = content.index("## Unreleased")
    version_pos = content.index("## v1.0.0")
    new_feature_pos = content.index("- Add new feature")
    assert unreleased_pos < new_feature_pos < version_pos


def test_add_to_unreleased_no_unreleased_creates_before_version(tmp_path):
    """Test add_to_unreleased creates ## Unreleased before first version header."""
    changelog_path = tmp_path / "CHANGELOG.md"
    changelog_path.write_text(
        """# Changelog

## v1.0.0

- Initial release
"""
    )

    add_to_unreleased(tmp_path, {"changelog": ["Add feature"]}, noop_log)

    content = changelog_path.read_text()
    assert "## Unreleased" in content
    assert "- Add feature" in content
    # Unreleased section must appear before the version section
    assert content.index("## Unreleased") < content.index("## v1.0.0")


def test_add_to_unreleased_no_version_headers(tmp_path):
    """Test add_to_unreleased creates ## Unreleased at end of preamble when no versions exist."""
    changelog_path = tmp_path / "CHANGELOG.md"
    changelog_path.write_text("# Changelog\n\nSome preamble text.\n")

    add_to_unreleased(tmp_path, {"changelog": ["Initial change"]}, noop_log)

    content = changelog_path.read_text()
    assert "## Unreleased" in content
    assert "- Initial change" in content


def test_add_to_unreleased_file_content_format(tmp_path):
    """Test add_to_unreleased writes correctly formatted bullets."""
    changelog_path = tmp_path / "CHANGELOG.md"
    changelog_path.write_text("# Changelog\n\n## v1.0.0\n\n- Old entry\n")

    add_to_unreleased(tmp_path, {"changelog": ["Fix bug", "- Add feature"]}, noop_log)

    content = changelog_path.read_text()
    # Bullets must be normalised (leading "- " stripped and re-added)
    assert "- Fix bug" in content
    assert "- Add feature" in content
    # Should not have double dashes
    assert "-- " not in content


# ---------------------------------------------------------------------------
# update_changelog_with_suggestions
# ---------------------------------------------------------------------------


def test_update_changelog_with_suggestions_no_changelog(tmp_path):
    """Test update_changelog_with_suggestions returns None when CHANGELOG.md missing."""
    result = update_changelog_with_suggestions(
        tmp_path, {"version_bump": "patch", "changelog": ["Fix bug"]}, noop_log
    )
    assert result is None


def test_update_changelog_with_suggestions_patch_bump(tmp_path):
    """Test update_changelog_with_suggestions inserts patch version section and returns version."""
    changelog_path = tmp_path / "CHANGELOG.md"
    changelog_path.write_text(
        """# Changelog

## v1.2.3

- Previous change
"""
    )

    result = update_changelog_with_suggestions(
        tmp_path,
        {"version_bump": "patch", "changelog": ["Fix regression"]},
        noop_log,
    )

    assert result == "v1.2.4"
    content = changelog_path.read_text()
    assert "## v1.2.4" in content
    assert "- Fix regression" in content
    # New version should appear before old version
    assert content.index("## v1.2.4") < content.index("## v1.2.3")


def test_update_changelog_with_suggestions_minor_bump(tmp_path):
    """Test update_changelog_with_suggestions handles minor version bump correctly."""
    changelog_path = tmp_path / "CHANGELOG.md"
    changelog_path.write_text(
        """# Changelog

## v2.0.0

- Major release
"""
    )

    result = update_changelog_with_suggestions(
        tmp_path,
        {"version_bump": "minor", "changelog": ["Add new API"]},
        noop_log,
    )

    assert result == "v2.1.0"
    content = changelog_path.read_text()
    assert "## v2.1.0" in content
    assert "- Add new API" in content


def test_update_changelog_with_suggestions_file_content_format(tmp_path):
    """Test update_changelog_with_suggestions writes correct CHANGELOG format."""
    changelog_path = tmp_path / "CHANGELOG.md"
    changelog_path.write_text("# Changelog\n\n## v1.0.0\n\n- Init\n")

    update_changelog_with_suggestions(
        tmp_path,
        {"version_bump": "patch", "changelog": ["- Fix typo", "Add docs"]},
        noop_log,
    )

    content = changelog_path.read_text()
    # Bullets normalised: leading "- " stripped and re-added
    assert "- Fix typo" in content
    assert "- Add docs" in content
    assert "-- " not in content


# ---------------------------------------------------------------------------
# drain_unreleased_section
# ---------------------------------------------------------------------------


def test_drain_unreleased_removes_header_and_bullets(tmp_path):
    """Test drain_unreleased_section removes ## Unreleased header and its bullets."""
    changelog_path = tmp_path / "CHANGELOG.md"
    changelog_path.write_text(
        "# Changelog\n\n## Unreleased\n\n- bullet 1\n- bullet 2\n\n## v1.2.3\n\n- old\n"
    )

    drain_unreleased_section(changelog_path)

    content = changelog_path.read_text()
    assert "## Unreleased" not in content
    assert "- bullet 1" not in content
    assert "- bullet 2" not in content
    assert "## v1.2.3" in content
    assert "- old" in content


def test_drain_unreleased_no_section_noop(tmp_path):
    """Test drain_unreleased_section is a no-op when only version sections exist."""
    original = "# Changelog\n\n## v1.0.0\n\n- Init\n"
    changelog_path = tmp_path / "CHANGELOG.md"
    changelog_path.write_text(original)

    drain_unreleased_section(changelog_path)

    assert changelog_path.read_text() == original


def test_drain_unreleased_missing_file_noop(tmp_path):
    """Test drain_unreleased_section does not raise when file does not exist."""
    changelog_path = tmp_path / "CHANGELOG.md"
    drain_unreleased_section(changelog_path)  # Should not raise


def test_drain_unreleased_custom_header(tmp_path):
    """Test drain_unreleased_section removes a non-standard header (e.g. ## Banana)."""
    changelog_path = tmp_path / "CHANGELOG.md"
    changelog_path.write_text(
        "# Changelog\n\n## Banana\n\n- wip feature\n\n## v2.0.0\n\n- stable\n"
    )

    drain_unreleased_section(changelog_path)

    content = changelog_path.read_text()
    assert "## Banana" not in content
    assert "- wip feature" not in content
    assert "## v2.0.0" in content
