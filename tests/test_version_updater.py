"""Tests for version updater."""

import json
from unittest.mock import MagicMock, patch

import httpx
import yaml

from updater.version_updater import (
    get_latest_alpine_version,
    get_latest_golang_version,
    update_dockerfile_alpine,
    update_dockerfile_golang,
    update_github_workflows_golang,
    update_gomod_version,
    update_versions,
)


def test_get_latest_golang_version():
    """Test fetching latest golang version."""
    version = get_latest_golang_version()
    assert version is not None
    assert len(version.split(".")) >= 2  # At least major.minor
    assert version[0].isdigit()


def test_get_latest_alpine_version():
    """Test fetching latest alpine version."""
    version = get_latest_alpine_version()
    assert version is not None
    assert len(version.split(".")) == 2  # major.minor only
    assert version[0].isdigit()


# --- Mocked tests for get_latest_golang_version ---


def test_get_latest_golang_version_success():
    """Mock valid JSON response returns stripped version string."""
    mock_response = MagicMock()
    mock_response.text = json.dumps([{"version": "go1.23.5"}])
    mock_response.raise_for_status.return_value = None

    with patch("updater.version_updater.httpx.get", return_value=mock_response):
        result = get_latest_golang_version()

    assert result == "1.23.5"


def test_get_latest_golang_version_http_error():
    """HTTP error returns None."""
    with patch(
        "updater.version_updater.httpx.get",
        side_effect=httpx.HTTPError("connection failed"),
    ):
        result = get_latest_golang_version()

    assert result is None


def test_get_latest_golang_version_timeout():
    """Timeout returns None."""
    with patch(
        "updater.version_updater.httpx.get",
        side_effect=httpx.TimeoutException("timeout"),
    ):
        result = get_latest_golang_version()

    assert result is None


def test_get_latest_golang_version_json_parse_error():
    """Invalid JSON returns None."""
    mock_response = MagicMock()
    mock_response.text = "not valid json"
    mock_response.raise_for_status.return_value = None

    with patch("updater.version_updater.httpx.get", return_value=mock_response):
        result = get_latest_golang_version()

    assert result is None


def test_get_latest_golang_version_empty_list():
    """Empty list response returns None."""
    mock_response = MagicMock()
    mock_response.text = json.dumps([])
    mock_response.raise_for_status.return_value = None

    with patch("updater.version_updater.httpx.get", return_value=mock_response):
        result = get_latest_golang_version()

    assert result is None


# --- Mocked tests for get_latest_alpine_version ---


def test_get_latest_alpine_version_success():
    """Mock valid YAML response returns major.minor version string."""
    releases = [{"flavor": "alpine-minirootfs", "version": "3.20.3"}]
    mock_response = MagicMock()
    mock_response.text = yaml.dump(releases)
    mock_response.raise_for_status.return_value = None

    with patch("updater.version_updater.httpx.get", return_value=mock_response):
        result = get_latest_alpine_version()

    assert result == "3.20"


def test_get_latest_alpine_version_http_error():
    """HTTP error returns None."""
    with patch(
        "updater.version_updater.httpx.get",
        side_effect=httpx.HTTPError("connection failed"),
    ):
        result = get_latest_alpine_version()

    assert result is None


def test_get_latest_alpine_version_timeout():
    """Timeout returns None."""
    with patch(
        "updater.version_updater.httpx.get",
        side_effect=httpx.TimeoutException("timeout"),
    ):
        result = get_latest_alpine_version()

    assert result is None


def test_get_latest_alpine_version_yaml_parse_error():
    """Invalid YAML returns None."""
    mock_response = MagicMock()
    mock_response.text = ":\ninvalid: yaml: ]["
    mock_response.raise_for_status.return_value = None

    with patch("updater.version_updater.httpx.get", return_value=mock_response):
        result = get_latest_alpine_version()

    assert result is None


def test_get_latest_alpine_version_no_minirootfs_flavor():
    """YAML without alpine-minirootfs flavor returns None."""
    releases = [{"flavor": "other-flavor", "version": "3.20.3"}]
    mock_response = MagicMock()
    mock_response.text = yaml.dump(releases)
    mock_response.raise_for_status.return_value = None

    with patch("updater.version_updater.httpx.get", return_value=mock_response):
        result = get_latest_alpine_version()

    assert result is None


# --- Mocked tests for update_versions ---


def test_update_versions_both_succeed_with_updates(tmp_path):
    """Both golang and alpine fetched; sub-updaters run; returns True when files updated."""
    dockerfile = tmp_path / "Dockerfile"
    dockerfile.write_text("FROM golang:1.22.0\nFROM alpine:3.19\n")

    with (
        patch("updater.version_updater.get_latest_golang_version", return_value="1.23.5"),
        patch("updater.version_updater.get_latest_alpine_version", return_value="3.20"),
    ):
        result = update_versions(tmp_path)

    assert result is True
    content = dockerfile.read_text()
    assert "golang:1.23.5" in content
    assert "alpine:3.20" in content


def test_update_versions_no_updates_needed(tmp_path):
    """All versions already current; returns False."""
    dockerfile = tmp_path / "Dockerfile"
    dockerfile.write_text("FROM golang:1.23.5\nFROM alpine:3.20\n")

    with (
        patch("updater.version_updater.get_latest_golang_version", return_value="1.23.5"),
        patch("updater.version_updater.get_latest_alpine_version", return_value="3.20"),
    ):
        result = update_versions(tmp_path)

    assert result is False


def test_update_versions_golang_fetch_fails(tmp_path):
    """Golang fetch returns None; logs warning; alpine still processed."""
    dockerfile = tmp_path / "Dockerfile"
    dockerfile.write_text("FROM alpine:3.19\n")

    log_calls = []

    def capture_log(msg, **kwargs):
        log_calls.append(msg)

    with (
        patch("updater.version_updater.get_latest_golang_version", return_value=None),
        patch("updater.version_updater.get_latest_alpine_version", return_value="3.20"),
    ):
        result = update_versions(tmp_path, log_func=capture_log)

    assert result is True
    assert any("golang" in msg.lower() for msg in log_calls)


def test_update_versions_alpine_fetch_fails(tmp_path):
    """Alpine fetch returns None; logs warning; golang still processed."""
    dockerfile = tmp_path / "Dockerfile"
    dockerfile.write_text("FROM golang:1.22.0\n")

    log_calls = []

    def capture_log(msg, **kwargs):
        log_calls.append(msg)

    with (
        patch("updater.version_updater.get_latest_golang_version", return_value="1.23.5"),
        patch("updater.version_updater.get_latest_alpine_version", return_value=None),
    ):
        result = update_versions(tmp_path, log_func=capture_log)

    assert result is True
    assert any("alpine" in msg.lower() for msg in log_calls)


def test_update_versions_both_fetch_fail(tmp_path):
    """Both fetches return None; returns False."""
    with (
        patch("updater.version_updater.get_latest_golang_version", return_value=None),
        patch("updater.version_updater.get_latest_alpine_version", return_value=None),
    ):
        result = update_versions(tmp_path)

    assert result is False


def test_update_dockerfile_golang(tmp_path):
    """Test updating golang version in Dockerfile."""
    dockerfile = tmp_path / "Dockerfile"

    # Test case 1: Simple FROM statement
    dockerfile.write_text("FROM golang:1.23.4\n")
    assert update_dockerfile_golang(tmp_path, "1.25.5")
    assert "FROM golang:1.25.5\n" == dockerfile.read_text()

    # Test case 2: FROM with AS clause
    dockerfile.write_text("FROM golang:1.23.4 AS build\n")
    assert update_dockerfile_golang(tmp_path, "1.25.5")
    assert "FROM golang:1.25.5 AS build\n" == dockerfile.read_text()

    # Test case 3: FROM with alpine suffix
    dockerfile.write_text("FROM golang:1.23.4-alpine3.20\n")
    assert update_dockerfile_golang(tmp_path, "1.25.5")
    assert "FROM golang:1.25.5-alpine3.20\n" == dockerfile.read_text()

    # Test case 4: FROM with alpine suffix and AS clause
    dockerfile.write_text("FROM golang:1.23.4-alpine3.20 AS build\n")
    assert update_dockerfile_golang(tmp_path, "1.25.5")
    assert "FROM golang:1.25.5-alpine3.20 AS build\n" == dockerfile.read_text()

    # Test case 5: Already up to date
    dockerfile.write_text("FROM golang:1.25.5 AS build\n")
    assert not update_dockerfile_golang(tmp_path, "1.25.5")


def test_update_dockerfile_alpine(tmp_path):
    """Test updating alpine version in Dockerfile."""
    dockerfile = tmp_path / "Dockerfile"

    # Test case 1: Simple FROM statement
    dockerfile.write_text("FROM alpine:3.19\n")
    assert update_dockerfile_alpine(tmp_path, "3.22")
    assert "FROM alpine:3.22\n" == dockerfile.read_text()

    # Test case 2: FROM with AS clause
    dockerfile.write_text("FROM alpine:3.19 AS alpine\n")
    assert update_dockerfile_alpine(tmp_path, "3.22")
    assert "FROM alpine:3.22 AS alpine\n" == dockerfile.read_text()

    # Test case 3: FROM with patch version
    dockerfile.write_text("FROM alpine:3.19.1\n")
    assert update_dockerfile_alpine(tmp_path, "3.22")
    assert "FROM alpine:3.22\n" == dockerfile.read_text()

    # Test case 4: Already up to date
    dockerfile.write_text("FROM alpine:3.22 AS alpine\n")
    assert not update_dockerfile_alpine(tmp_path, "3.22")


def test_update_dockerfile_golang_registry_prefix(tmp_path):
    """Test updating golang version in Dockerfile with registry prefix."""
    dockerfile = tmp_path / "Dockerfile"

    # Test case 1: Variable registry prefix with AS clause
    dockerfile.write_text("FROM ${DOCKER_REGISTRY}/golang:1.23.4 AS build\n")
    assert update_dockerfile_golang(tmp_path, "1.25.5")
    assert "FROM ${DOCKER_REGISTRY}/golang:1.25.5 AS build\n" == dockerfile.read_text()

    # Test case 2: docker.io/library prefix
    dockerfile.write_text("FROM docker.io/library/golang:1.23.4\n")
    assert update_dockerfile_golang(tmp_path, "1.25.5")
    assert "FROM docker.io/library/golang:1.25.5\n" == dockerfile.read_text()

    # Test case 3: Bare FROM still works
    dockerfile.write_text("FROM golang:1.23.4 AS build\n")
    assert update_dockerfile_golang(tmp_path, "1.25.5")
    assert "FROM golang:1.25.5 AS build\n" == dockerfile.read_text()


def test_update_dockerfile_alpine_registry_prefix(tmp_path):
    """Test updating alpine version in Dockerfile with registry prefix."""
    dockerfile = tmp_path / "Dockerfile"

    # Test case 1: Variable registry prefix with AS clause
    dockerfile.write_text("FROM ${DOCKER_REGISTRY}/alpine:3.19 AS alpine\n")
    assert update_dockerfile_alpine(tmp_path, "3.22")
    assert "FROM ${DOCKER_REGISTRY}/alpine:3.22 AS alpine\n" == dockerfile.read_text()

    # Test case 2: docker.io/library prefix
    dockerfile.write_text("FROM docker.io/library/alpine:3.19\n")
    assert update_dockerfile_alpine(tmp_path, "3.22")
    assert "FROM docker.io/library/alpine:3.22\n" == dockerfile.read_text()

    # Test case 3: Bare FROM still works
    dockerfile.write_text("FROM alpine:3.19 AS alpine\n")
    assert update_dockerfile_alpine(tmp_path, "3.22")
    assert "FROM alpine:3.22 AS alpine\n" == dockerfile.read_text()


def test_update_versions_registry_prefix(tmp_path):
    """Test update_versions with Dockerfile using ${DOCKER_REGISTRY}/ prefix."""
    dockerfile = tmp_path / "Dockerfile"
    dockerfile.write_text(
        "ARG DOCKER_REGISTRY=docker.quant.benjamin-borbe.de:443\n"
        "FROM ${DOCKER_REGISTRY}/golang:1.23.4 AS build\n"
        "FROM ${DOCKER_REGISTRY}/alpine:3.19 AS alpine\n"
    )

    with (
        patch("updater.version_updater.get_latest_golang_version", return_value="1.25.5"),
        patch("updater.version_updater.get_latest_alpine_version", return_value="3.22"),
    ):
        result = update_versions(tmp_path)

    assert result is True
    content = dockerfile.read_text()
    assert "FROM ${DOCKER_REGISTRY}/golang:1.25.5 AS build" in content
    assert "FROM ${DOCKER_REGISTRY}/alpine:3.22 AS alpine" in content


def test_update_gomod_version(tmp_path):
    """Test updating go version in go.mod."""
    gomod = tmp_path / "go.mod"

    # Test case 1: Update from minor to patch version
    gomod.write_text("module example.com/test\n\ngo 1.23\n")
    assert update_gomod_version(tmp_path, "1.25.5")
    assert "module example.com/test\n\ngo 1.25.5\n" == gomod.read_text()

    # Test case 2: Update from old patch to new patch version
    gomod.write_text("module example.com/test\n\ngo 1.23.4\n")
    assert update_gomod_version(tmp_path, "1.25.5")
    assert "module example.com/test\n\ngo 1.25.5\n" == gomod.read_text()

    # Test case 3: Already up to date (exact match)
    gomod.write_text("module example.com/test\n\ngo 1.25.5\n")
    assert not update_gomod_version(tmp_path, "1.25.5")

    # Test case 4: Update patch version (1.25.5 -> 1.25.6)
    gomod.write_text("module example.com/test\n\ngo 1.25.5\n")
    assert update_gomod_version(tmp_path, "1.25.6")
    assert "module example.com/test\n\ngo 1.25.6\n" == gomod.read_text()


def test_update_github_workflows_golang(tmp_path):
    """Test updating golang version in GitHub workflows."""
    workflows_dir = tmp_path / ".github" / "workflows"
    workflows_dir.mkdir(parents=True)

    ci_yml = workflows_dir / "ci.yml"

    # Test case 1: Single quotes
    ci_yml.write_text(
        "      - uses: actions/setup-go@v5\n        with:\n          go-version: '1.23.4'\n"
    )
    assert update_github_workflows_golang(tmp_path, "1.25.5")
    content = ci_yml.read_text()
    assert "go-version: '1.25.5'" in content

    # Test case 2: Double quotes
    ci_yml.write_text(
        '      - uses: actions/setup-go@v5\n        with:\n          go-version: "1.23.4"\n'
    )
    assert update_github_workflows_golang(tmp_path, "1.25.5")
    content = ci_yml.read_text()
    assert 'go-version: "1.25.5"' in content

    # Test case 3: No quotes
    ci_yml.write_text(
        "      - uses: actions/setup-go@v5\n        with:\n          go-version: 1.23.4\n"
    )
    assert update_github_workflows_golang(tmp_path, "1.25.5")
    content = ci_yml.read_text()
    assert "go-version: 1.25.5" in content

    # Test case 4: Already up to date
    ci_yml.write_text(
        "      - uses: actions/setup-go@v5\n        with:\n          go-version: '1.25.5'\n"
    )
    assert not update_github_workflows_golang(tmp_path, "1.25.5")

    # Test case 5: Skip when go-version-file is present (preferred approach)
    ci_yml.write_text(
        "      - uses: actions/setup-go@v5\n        with:\n          go-version-file: go.mod\n"
    )
    assert not update_github_workflows_golang(tmp_path, "1.25.5")
    content = ci_yml.read_text()
    assert "go-version-file: go.mod" in content
    assert "go-version: " not in content


def test_update_dockerfile_complete_example(tmp_path):
    """Test updating a complete Dockerfile like the skeleton example."""
    dockerfile = tmp_path / "Dockerfile"

    # Complete Dockerfile example from skeleton
    content = """FROM golang:1.23.4 AS build
COPY . /workspace
WORKDIR /workspace
RUN CGO_ENABLED=0 GOOS=linux go build -mod=vendor -ldflags "-s" -a -installsuffix cgo -o /main
CMD ["/bin/bash"]

FROM alpine:3.19 AS alpine
RUN apk --no-cache add ca-certificates

FROM scratch
COPY --from=build /main /main
COPY --from=alpine /etc/ssl/certs/ca-certificates.crt /etc/ssl/certs/
COPY --from=build /usr/local/go/lib/time/zoneinfo.zip /
ENV ZONEINFO=/zoneinfo.zip
ENTRYPOINT ["/main"]
"""

    dockerfile.write_text(content)

    # Update golang
    assert update_dockerfile_golang(tmp_path, "1.25.5")

    # Update alpine
    assert update_dockerfile_alpine(tmp_path, "3.22")

    result = dockerfile.read_text()

    # Verify both updates
    assert "FROM golang:1.25.5 AS build" in result
    assert "FROM alpine:3.22 AS alpine" in result
    assert "FROM scratch" in result  # Unchanged
