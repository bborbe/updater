"""Tests for Python version updater."""

import pytest

from updater.python_version_updater import (
    get_latest_python_version,
    update_dockerfile_python,
    update_pyproject_python,
    update_python_version_file,
    update_python_versions,
)


@pytest.mark.skip(reason="Flaky: depends on python.org API availability and rate limits")
def test_get_latest_python_version():
    """Test fetching latest Python version."""
    version = get_latest_python_version()
    assert version is not None
    # Should return major.minor (e.g., "3.12" or "3.13")
    parts = version.split(".")
    assert len(parts) == 2
    assert parts[0].isdigit()
    assert parts[1].isdigit()
    # Should be Python 3.x
    assert int(parts[0]) >= 3


def test_update_python_version_file(tmp_path):
    """Test updating .python-version file."""
    version_file = tmp_path / ".python-version"

    # Test case 1: Update from old version
    version_file.write_text("3.11\n")
    assert update_python_version_file(tmp_path, "3.12")
    assert version_file.read_text() == "3.12\n"

    # Test case 2: Already up to date
    version_file.write_text("3.12\n")
    assert not update_python_version_file(tmp_path, "3.12")

    # Test case 3: File with patch version
    version_file.write_text("3.11.5\n")
    assert update_python_version_file(tmp_path, "3.12")
    assert version_file.read_text() == "3.12\n"

    # Test case 4: No .python-version file (should not create one)
    version_file.unlink()
    assert not update_python_version_file(tmp_path, "3.12")
    assert not version_file.exists()


def test_update_pyproject_python(tmp_path):
    """Test updating Python version in pyproject.toml."""
    pyproject = tmp_path / "pyproject.toml"

    # Test case 1: Update requires-python and tool versions
    pyproject.write_text("""[project]
name = "test"
requires-python = ">=3.11"

[tool.ruff]
target-version = "py311"

[tool.mypy]
python_version = "3.11"
""")
    assert update_pyproject_python(tmp_path, "3.12")
    content = pyproject.read_text()
    assert 'requires-python = ">=3.12"' in content
    assert 'target-version = "py312"' in content
    assert 'python_version = "3.12"' in content

    # Test case 2: Already up to date
    assert not update_pyproject_python(tmp_path, "3.12")

    # Test case 3: Only some fields present
    pyproject.write_text("""[project]
name = "test"
requires-python = ">=3.11"

[tool.ruff]
line-length = 100
""")
    assert update_pyproject_python(tmp_path, "3.12")
    content = pyproject.read_text()
    assert 'requires-python = ">=3.12"' in content
    # ruff target-version not present, shouldn't add it
    assert "target-version" not in content

    # Test case 4: No pyproject.toml
    pyproject.unlink()
    assert not update_pyproject_python(tmp_path, "3.12")


def test_update_pyproject_preserves_other_content(tmp_path):
    """Test that pyproject.toml updates preserve other content."""
    pyproject = tmp_path / "pyproject.toml"

    pyproject.write_text("""[project]
name = "test"
version = "1.0.0"
description = "A test project"
requires-python = ">=3.11"
dependencies = [
    "fastapi>=0.115.0",
    "pydantic>=2.10.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.3.0",
    "ruff>=0.8.0",
]

[tool.ruff]
line-length = 100
target-version = "py311"

[tool.ruff.lint]
select = ["E", "W", "F"]

[tool.mypy]
python_version = "3.11"
strict = true
""")
    assert update_pyproject_python(tmp_path, "3.12")
    content = pyproject.read_text()

    # Version-related fields updated
    assert 'requires-python = ">=3.12"' in content
    assert 'target-version = "py312"' in content
    assert 'python_version = "3.12"' in content

    # Other content preserved
    assert 'name = "test"' in content
    assert 'version = "1.0.0"' in content
    assert 'description = "A test project"' in content
    assert '"fastapi>=0.115.0"' in content
    assert '"pytest>=8.3.0"' in content
    assert "line-length = 100" in content
    assert "strict = true" in content
    assert 'select = ["E", "W", "F"]' in content


def test_update_dockerfile_python(tmp_path):
    """Test updating Python version in Dockerfile."""
    dockerfile = tmp_path / "Dockerfile"

    # Test case 1: Simple FROM statement
    dockerfile.write_text("FROM python:3.11-slim\n")
    assert update_dockerfile_python(tmp_path, "3.12")
    assert dockerfile.read_text() == "FROM python:3.12-slim\n"

    # Test case 2: FROM with AS clause
    dockerfile.write_text("FROM python:3.11-slim AS builder\n")
    assert update_dockerfile_python(tmp_path, "3.12")
    assert dockerfile.read_text() == "FROM python:3.12-slim AS builder\n"

    # Test case 3: Multiple Python stages
    dockerfile.write_text("""FROM python:3.11-slim AS builder
COPY . /app

FROM python:3.11-slim
COPY --from=builder /app /app
""")
    assert update_dockerfile_python(tmp_path, "3.12")
    content = dockerfile.read_text()
    assert "FROM python:3.12-slim AS builder" in content
    assert "FROM python:3.12-slim\n" in content

    # Test case 4: Already up to date
    dockerfile.write_text("FROM python:3.12-slim\n")
    assert not update_dockerfile_python(tmp_path, "3.12")

    # Test case 5: No Dockerfile
    dockerfile.unlink()
    assert not update_dockerfile_python(tmp_path, "3.12")

    # Test case 6: Different variants
    dockerfile.write_text("FROM python:3.11-alpine\n")
    assert update_dockerfile_python(tmp_path, "3.12")
    assert dockerfile.read_text() == "FROM python:3.12-alpine\n"


def test_update_dockerfile_python_complete_example(tmp_path):
    """Test updating a complete Python Dockerfile like python-skeleton."""
    dockerfile = tmp_path / "Dockerfile"

    content = """# Build stage
FROM python:3.11-slim AS builder

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

WORKDIR /app

# Copy dependency files first for layer caching
COPY pyproject.toml uv.lock ./

# Install production dependencies only
RUN uv sync --frozen --no-dev --no-editable

# Copy source code
COPY src/ ./src/

# Install the package
RUN uv pip install --no-deps -e .

# Runtime stage
FROM python:3.11-slim

# Create non-root user
RUN useradd --create-home --shell /bin/bash app

WORKDIR /app

# Copy virtual environment and source from builder
COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app/src /app/src

# Set environment variables
ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONUNBUFFERED=1

USER app
CMD ["skeleton", "serve"]
"""

    dockerfile.write_text(content)
    assert update_dockerfile_python(tmp_path, "3.12")
    result = dockerfile.read_text()

    # Both stages updated
    assert "FROM python:3.12-slim AS builder" in result
    assert "FROM python:3.12-slim\n" in result

    # Other content preserved
    assert "COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv" in result
    assert "RUN uv sync --frozen --no-dev --no-editable" in result
    assert 'CMD ["skeleton", "serve"]' in result


def test_update_python_versions(tmp_path, monkeypatch):
    """Test the orchestrating function that updates all Python version files."""
    # Mock get_latest_python_version to avoid network calls
    latest = "3.14"
    monkeypatch.setattr("updater.python_version_updater.get_latest_python_version", lambda: latest)

    # Create .python-version with old version
    version_file = tmp_path / ".python-version"
    version_file.write_text("3.11\n")

    # Create pyproject.toml with old version
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text("""[project]
name = "test"
requires-python = ">=3.11"

[tool.ruff]
target-version = "py311"

[tool.mypy]
python_version = "3.11"
""")

    # Create Dockerfile with old version
    dockerfile = tmp_path / "Dockerfile"
    dockerfile.write_text("FROM python:3.11-slim\n")

    # Update all
    assert update_python_versions(tmp_path) is True

    # Verify all updated to latest
    assert version_file.read_text().strip() == latest

    content = pyproject.read_text()
    assert f'requires-python = ">={latest}"' in content

    dockerfile_content = dockerfile.read_text()
    assert f"FROM python:{latest}-slim" in dockerfile_content


def test_update_python_versions_no_changes_needed(tmp_path, monkeypatch):
    """Test when versions are already up to date."""
    # Mock get_latest_python_version to avoid network calls
    latest = "3.14"
    monkeypatch.setattr("updater.python_version_updater.get_latest_python_version", lambda: latest)

    # Create files with latest version
    version_file = tmp_path / ".python-version"
    version_file.write_text(f"{latest}\n")

    pyproject = tmp_path / "pyproject.toml"
    py_short = latest.replace(".", "")  # e.g., "312"
    pyproject.write_text(f'''[project]
name = "test"
requires-python = ">={latest}"

[tool.ruff]
target-version = "py{py_short}"

[tool.mypy]
python_version = "{latest}"
''')

    dockerfile = tmp_path / "Dockerfile"
    dockerfile.write_text(f"FROM python:{latest}-slim\n")

    # Should return False when nothing to update
    assert update_python_versions(tmp_path) is False
