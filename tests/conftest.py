"""Shared test fixtures and configuration."""

from pathlib import Path

import pytest


@pytest.fixture
def tmp_git_repo(tmp_path: Path) -> Path:
    """Create a temporary git repository for testing.

    Args:
        tmp_path: Pytest temporary directory fixture

    Returns:
        Path to temporary git repository
    """
    import subprocess

    repo_path = tmp_path / "test_repo"
    repo_path.mkdir()

    # Initialize git repo
    subprocess.run(
        ["git", "init"],
        cwd=repo_path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=repo_path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=repo_path,
        check=True,
        capture_output=True,
    )

    return repo_path


@pytest.fixture
def sample_changelog(tmp_path: Path) -> Path:
    """Create a sample CHANGELOG.md file for testing.

    Args:
        tmp_path: Pytest temporary directory fixture

    Returns:
        Path to CHANGELOG.md file
    """
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text(
        """# Changelog

## v0.2.1
- Fix bug in version parsing
- Improve error messages

## v0.2.0
- Add new feature
- Update dependencies

## v0.1.0
- Initial release
"""
    )
    return changelog


@pytest.fixture
def sample_gomod(tmp_path: Path) -> Path:
    """Create a sample go.mod file for testing.

    Args:
        tmp_path: Pytest temporary directory fixture

    Returns:
        Path to go.mod file
    """
    gomod = tmp_path / "go.mod"
    gomod.write_text(
        """module github.com/example/project

go 1.21

require (
    github.com/stretchr/testify v1.8.4
    golang.org/x/sync v0.5.0
)
"""
    )
    return gomod
