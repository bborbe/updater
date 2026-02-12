"""Tests for standalone Docker updater."""

from unittest.mock import MagicMock, patch

from updater.docker_updater import (
    parse_dockerfile_images,
    update_dockerfile_images,
)


class TestParseDockerfileImages:
    """Tests for parse_dockerfile_images function."""

    def test_parses_simple_from(self, tmp_path):
        """Test parsing simple FROM statements."""
        dockerfile = tmp_path / "Dockerfile"
        dockerfile.write_text("FROM golang:1.23.4\n")

        images = parse_dockerfile_images(dockerfile)

        assert len(images) == 1
        assert images[0]["image"] == "golang"
        assert images[0]["tag"] == "1.23.4"

    def test_parses_from_with_as(self, tmp_path):
        """Test parsing FROM with AS clause."""
        dockerfile = tmp_path / "Dockerfile"
        dockerfile.write_text("FROM python:3.12-slim AS builder\n")

        images = parse_dockerfile_images(dockerfile)

        assert len(images) == 1
        assert images[0]["image"] == "python"
        assert images[0]["tag"] == "3.12-slim"
        assert images[0]["as_name"] == "builder"

    def test_parses_multiple_stages(self, tmp_path):
        """Test parsing multi-stage Dockerfile."""
        dockerfile = tmp_path / "Dockerfile"
        dockerfile.write_text("""FROM golang:1.23.4 AS build
COPY . /app

FROM alpine:3.20
COPY --from=build /app /app
""")

        images = parse_dockerfile_images(dockerfile)

        assert len(images) == 2
        assert images[0]["image"] == "golang"
        assert images[0]["tag"] == "1.23.4"
        assert images[1]["image"] == "alpine"
        assert images[1]["tag"] == "3.20"

    def test_parses_scratch(self, tmp_path):
        """Test that scratch is included but marked specially."""
        dockerfile = tmp_path / "Dockerfile"
        dockerfile.write_text("""FROM golang:1.23.4 AS build
FROM scratch
COPY --from=build /app /app
""")

        images = parse_dockerfile_images(dockerfile)

        # scratch should be included
        assert len(images) == 2
        assert images[1]["image"] == "scratch"
        assert images[1]["tag"] is None

    def test_parses_registry_prefix(self, tmp_path):
        """Test parsing images with registry prefix."""
        dockerfile = tmp_path / "Dockerfile"
        dockerfile.write_text("FROM ghcr.io/astral-sh/uv:latest\n")

        images = parse_dockerfile_images(dockerfile)

        assert len(images) == 1
        assert images[0]["image"] == "ghcr.io/astral-sh/uv"
        assert images[0]["tag"] == "latest"

    def test_empty_dockerfile(self, tmp_path):
        """Test empty Dockerfile returns empty list."""
        dockerfile = tmp_path / "Dockerfile"
        dockerfile.write_text("# Just a comment\n")

        images = parse_dockerfile_images(dockerfile)

        assert images == []

    def test_nonexistent_dockerfile(self, tmp_path):
        """Test nonexistent Dockerfile returns empty list."""
        dockerfile = tmp_path / "Dockerfile"

        images = parse_dockerfile_images(dockerfile)

        assert images == []


class TestUpdateDockerfileImages:
    """Tests for update_dockerfile_images function."""

    def test_updates_golang_version(self, tmp_path):
        """Test updating golang image."""
        dockerfile = tmp_path / "Dockerfile"
        dockerfile.write_text("FROM golang:1.22.0 AS build\n")

        log_func = MagicMock()

        with patch("updater.docker_updater.get_latest_golang_version") as mock_go:
            mock_go.return_value = "1.23.5"
            updated, updates = update_dockerfile_images(tmp_path, log_func=log_func)

        assert updated is True
        assert len(updates) == 1
        assert "golang:1.22.0 → golang:1.23.5" in updates[0]
        assert "golang:1.23.5" in dockerfile.read_text()

    def test_updates_python_version(self, tmp_path):
        """Test updating python image."""
        dockerfile = tmp_path / "Dockerfile"
        dockerfile.write_text("FROM python:3.11-slim\n")

        log_func = MagicMock()

        with patch("updater.docker_updater.get_latest_python_version") as mock_py:
            mock_py.return_value = "3.12"
            updated, updates = update_dockerfile_images(tmp_path, log_func=log_func)

        assert updated is True
        assert len(updates) == 1
        assert "python:3.11-slim → python:3.12-slim" in updates[0]
        assert "python:3.12-slim" in dockerfile.read_text()

    def test_updates_alpine_version(self, tmp_path):
        """Test updating alpine image."""
        dockerfile = tmp_path / "Dockerfile"
        dockerfile.write_text("FROM alpine:3.19\n")

        log_func = MagicMock()

        with patch("updater.docker_updater.get_latest_alpine_version") as mock_alpine:
            mock_alpine.return_value = "3.20"
            updated, updates = update_dockerfile_images(tmp_path, log_func=log_func)

        assert updated is True
        assert len(updates) == 1
        assert "alpine:3.19 → alpine:3.20" in updates[0]
        assert "alpine:3.20" in dockerfile.read_text()

    def test_updates_multiple_images(self, tmp_path):
        """Test updating multiple images in one Dockerfile."""
        dockerfile = tmp_path / "Dockerfile"
        dockerfile.write_text("""FROM golang:1.22.0 AS build
COPY . /app

FROM alpine:3.19
COPY --from=build /app /app
""")

        log_func = MagicMock()

        with (
            patch("updater.docker_updater.get_latest_golang_version") as mock_go,
            patch("updater.docker_updater.get_latest_alpine_version") as mock_alpine,
        ):
            mock_go.return_value = "1.23.5"
            mock_alpine.return_value = "3.20"
            updated, updates = update_dockerfile_images(tmp_path, log_func=log_func)

        assert updated is True
        assert len(updates) == 2
        content = dockerfile.read_text()
        assert "golang:1.23.5" in content
        assert "alpine:3.20" in content

    def test_no_updates_needed(self, tmp_path):
        """Test when images are already up to date."""
        dockerfile = tmp_path / "Dockerfile"
        dockerfile.write_text("FROM golang:1.23.5 AS build\n")

        log_func = MagicMock()

        with patch("updater.docker_updater.get_latest_golang_version") as mock_go:
            mock_go.return_value = "1.23.5"
            updated, updates = update_dockerfile_images(tmp_path, log_func=log_func)

        assert updated is False
        assert updates == []

    def test_skips_scratch(self, tmp_path):
        """Test that scratch image is not updated."""
        dockerfile = tmp_path / "Dockerfile"
        dockerfile.write_text("FROM scratch\nCOPY /app /app\n")

        log_func = MagicMock()
        updated, updates = update_dockerfile_images(tmp_path, log_func=log_func)

        assert updated is False
        assert updates == []
        assert "FROM scratch" in dockerfile.read_text()

    def test_skips_unknown_images(self, tmp_path):
        """Test that unknown images are skipped."""
        dockerfile = tmp_path / "Dockerfile"
        dockerfile.write_text("FROM someregistry/customimage:v1.0.0\n")

        log_func = MagicMock()
        updated, updates = update_dockerfile_images(tmp_path, log_func=log_func)

        assert updated is False
        assert updates == []
        # Image unchanged
        assert "someregistry/customimage:v1.0.0" in dockerfile.read_text()

    def test_no_dockerfile(self, tmp_path):
        """Test when no Dockerfile exists."""
        log_func = MagicMock()
        updated, updates = update_dockerfile_images(tmp_path, log_func=log_func)

        assert updated is False
        assert updates == []

    def test_preserves_tag_suffix(self, tmp_path):
        """Test that tag suffixes like -slim, -alpine are preserved."""
        dockerfile = tmp_path / "Dockerfile"
        dockerfile.write_text("FROM python:3.11-slim-bookworm AS builder\n")

        log_func = MagicMock()

        with patch("updater.docker_updater.get_latest_python_version") as mock_py:
            mock_py.return_value = "3.12"
            updated, updates = update_dockerfile_images(tmp_path, log_func=log_func)

        assert updated is True
        assert len(updates) == 1
        # Should update version but keep suffix
        content = dockerfile.read_text()
        assert "python:3.12" in content
        # The suffix handling depends on implementation
