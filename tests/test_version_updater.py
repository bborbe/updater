"""Tests for version updater."""

from updater.version_updater import (
    get_latest_alpine_version,
    get_latest_golang_version,
    update_dockerfile_alpine,
    update_dockerfile_golang,
    update_github_workflows_golang,
    update_gomod_version,
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
