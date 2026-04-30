"""Tests for go.mod excludes and replaces."""

from updater.gomod_excludes import (
    apply_gomod_excludes_and_replaces,
    read_gomod_excludes_and_replaces,
)


def test_read_empty_gomod(tmp_path):
    """Test reading go.mod with no excludes or replaces."""
    gomod = tmp_path / "go.mod"
    gomod.write_text("module example.com/test\n\ngo 1.23\n")

    excludes, replaces = read_gomod_excludes_and_replaces(tmp_path)

    assert excludes == set()
    assert replaces == {}


def test_read_gomod_with_single_line_excludes(tmp_path):
    """Test reading go.mod with single-line excludes."""
    gomod = tmp_path / "go.mod"
    content = """module example.com/test

go 1.23

exclude k8s.io/api v0.34.0
exclude k8s.io/client-go v0.34.1
"""
    gomod.write_text(content)

    excludes, replaces = read_gomod_excludes_and_replaces(tmp_path)

    assert excludes == {
        "k8s.io/api@v0.34.0",
        "k8s.io/client-go@v0.34.1",
    }
    assert replaces == {}


def test_read_gomod_with_exclude_block(tmp_path):
    """Test reading go.mod with exclude block."""
    gomod = tmp_path / "go.mod"
    content = """module example.com/test

go 1.23

exclude (
    k8s.io/api v0.34.0
    k8s.io/client-go v0.34.1
    golang.org/x/tools v0.38.0
)
"""
    gomod.write_text(content)

    excludes, replaces = read_gomod_excludes_and_replaces(tmp_path)

    assert excludes == {
        "k8s.io/api@v0.34.0",
        "k8s.io/client-go@v0.34.1",
        "golang.org/x/tools@v0.38.0",
    }
    assert replaces == {}


def test_read_gomod_with_single_line_replace(tmp_path):
    """Test reading go.mod with single-line replace."""
    gomod = tmp_path / "go.mod"
    content = """module example.com/test

go 1.23

replace k8s.io/kube-openapi => k8s.io/kube-openapi v0.0.0-20250701173324-9bd5c66d9911
"""
    gomod.write_text(content)

    excludes, replaces = read_gomod_excludes_and_replaces(tmp_path)

    assert excludes == set()
    assert replaces == {
        "k8s.io/kube-openapi": "k8s.io/kube-openapi v0.0.0-20250701173324-9bd5c66d9911",
    }


def test_read_gomod_with_replace_block(tmp_path):
    """Test reading go.mod with replace block."""
    gomod = tmp_path / "go.mod"
    content = """module example.com/test

go 1.23

replace (
    k8s.io/kube-openapi => k8s.io/kube-openapi v0.0.0-20250701173324-9bd5c66d9911
    example.com/old => example.com/new v1.2.3
)
"""
    gomod.write_text(content)

    excludes, replaces = read_gomod_excludes_and_replaces(tmp_path)

    assert excludes == set()
    assert replaces == {
        "k8s.io/kube-openapi": "k8s.io/kube-openapi v0.0.0-20250701173324-9bd5c66d9911",
        "example.com/old": "example.com/new v1.2.3",
    }


def test_read_gomod_with_mixed_format(tmp_path):
    """Test reading go.mod with both blocks and single-line entries."""
    gomod = tmp_path / "go.mod"
    content = """module example.com/test

go 1.23

exclude k8s.io/api v0.34.0

exclude (
    k8s.io/client-go v0.34.1
    golang.org/x/tools v0.38.0
)

replace k8s.io/kube-openapi => k8s.io/kube-openapi v0.0.0-20250701173324-9bd5c66d9911

replace (
    example.com/old => example.com/new v1.2.3
)
"""
    gomod.write_text(content)

    excludes, replaces = read_gomod_excludes_and_replaces(tmp_path)

    assert excludes == {
        "k8s.io/api@v0.34.0",
        "k8s.io/client-go@v0.34.1",
        "golang.org/x/tools@v0.38.0",
    }
    assert replaces == {
        "k8s.io/kube-openapi": "k8s.io/kube-openapi v0.0.0-20250701173324-9bd5c66d9911",
        "example.com/old": "example.com/new v1.2.3",
    }


def test_apply_excludes_to_empty_gomod(tmp_path, mocker):
    """Test applying excludes to empty go.mod is a no-op when STANDARD_REPLACES is empty."""
    gomod = tmp_path / "go.mod"
    gomod.write_text("module example.com/test\n\ngo 1.23\n")

    # Mock run_command to avoid actual go mod edit calls
    mock_run = mocker.patch("updater.gomod_excludes.run_command")

    result = apply_gomod_excludes_and_replaces(tmp_path)

    assert result is False  # No standard replaces to add
    assert mock_run.call_count == 0  # No commands run


def test_apply_excludes_idempotent(tmp_path, mocker):
    """Test that applying with all tools.go-era replaces present makes no changes
    when tools.go exists (un-migrated project).
    """
    gomod = tmp_path / "go.mod"
    content = """module example.com/test

go 1.23

replace (
    github.com/charmbracelet/x/cellbuf => github.com/charmbracelet/x/cellbuf v0.0.15
    github.com/denis-tingaikin/go-header => github.com/denis-tingaikin/go-header v0.5.0
    github.com/diskfs/go-diskfs => github.com/diskfs/go-diskfs v1.7.0
    github.com/nunnatsa/ginkgolinter/types => github.com/nunnatsa/ginkgolinter v0.19.1
)
"""
    gomod.write_text(content)
    (tmp_path / "tools.go").write_text("//go:build tools\npackage tools\n")

    # Mock run_command to avoid actual go mod edit calls
    mock_run = mocker.patch("updater.gomod_excludes.run_command")

    result = apply_gomod_excludes_and_replaces(tmp_path)

    assert result is False  # No changes needed
    assert mock_run.call_count == 0  # No commands run


def test_apply_removes_old_non_k8s_excludes(tmp_path, mocker):
    """Test that old non-k8s excludes are also removed as obsolete."""
    gomod = tmp_path / "go.mod"
    content = """module example.com/test

go 1.23

exclude (
    cloud.google.com/go v0.26.0
    github.com/go-logr/glogr v1.0.0-rc1
    github.com/go-logr/glogr v1.0.0
    github.com/go-logr/logr v1.0.0-rc1
    github.com/go-logr/logr v1.0.0
    go.yaml.in/yaml/v3 v3.0.3
    go.yaml.in/yaml/v3 v3.0.4
    golang.org/x/tools v0.38.0
    golang.org/x/tools v0.39.0
)
"""
    gomod.write_text(content)

    mock_run = mocker.patch("updater.gomod_excludes.run_command")

    result = apply_gomod_excludes_and_replaces(tmp_path)

    assert result is True  # Changes made — obsolete excludes removed
    assert mock_run.call_count == 10  # 9 dropexclude + 1 go mod download


def test_apply_excludes_removes_obsolete_k8s_entries(tmp_path, mocker):
    """Test that obsolete k8s excludes and kube-openapi replace are removed."""
    gomod = tmp_path / "go.mod"
    content = """module example.com/test

go 1.23

exclude (
    cloud.google.com/go v0.26.0
    k8s.io/api v0.34.0
    k8s.io/client-go v0.35.2
    sigs.k8s.io/structured-merge-diff/v6 v6.3.0
    golang.org/x/tools v0.38.0
)

replace k8s.io/kube-openapi => k8s.io/kube-openapi v0.0.0-20250701173324-9bd5c66d9911
"""
    gomod.write_text(content)

    mock_run = mocker.patch("updater.gomod_excludes.run_command")

    result = apply_gomod_excludes_and_replaces(tmp_path)

    assert result is True  # Obsolete entries were removed
    # Should have called go mod edit to drop the obsolete entries
    assert mock_run.call_count > 0
    calls = [str(c) for c in mock_run.call_args_list]
    assert any("dropexclude" in c and "k8s.io/api" in c for c in calls)
    assert any("dropexclude" in c and "k8s.io/client-go" in c for c in calls)
    assert any("dropexclude" in c and "structured-merge-diff" in c for c in calls)
    assert any("dropreplace" in c and "kube-openapi" in c for c in calls)


def test_apply_excludes_missing_gomod(tmp_path):
    """Test applying excludes when go.mod doesn't exist."""
    result = apply_gomod_excludes_and_replaces(tmp_path)

    assert result is False  # No changes made


def test_apply_excludes_calls_go_mod_download_when_changes_made(tmp_path, mocker):
    """Test that go mod download is called when changes are made."""
    gomod = tmp_path / "go.mod"
    # Use an obsolete replace to trigger changes (since STANDARD_REPLACES is empty)
    gomod.write_text(
        "module example.com/test\n\ngo 1.23\n\n"
        "replace github.com/anthropics/anthropic-sdk-go => "
        "github.com/anthropics/anthropic-sdk-go v1.26.0\n"
    )

    mock_run = mocker.patch("updater.gomod_excludes.run_command")

    result = apply_gomod_excludes_and_replaces(tmp_path)

    assert result is True
    calls = [str(c) for c in mock_run.call_args_list]
    assert any("go mod download" in c for c in calls)


def test_apply_excludes_does_not_call_go_mod_download_when_no_changes(tmp_path, mocker):
    """Test that go mod download is NOT called when no changes are made
    on an un-migrated project (tools.go present, replaces stay).
    """
    gomod = tmp_path / "go.mod"
    content = """module example.com/test

go 1.23

replace (
    github.com/charmbracelet/x/cellbuf => github.com/charmbracelet/x/cellbuf v0.0.15
    github.com/denis-tingaikin/go-header => github.com/denis-tingaikin/go-header v0.5.0
    github.com/diskfs/go-diskfs => github.com/diskfs/go-diskfs v1.7.0
    github.com/nunnatsa/ginkgolinter/types => github.com/nunnatsa/ginkgolinter v0.19.1
)
"""
    gomod.write_text(content)
    (tmp_path / "tools.go").write_text("//go:build tools\npackage tools\n")

    mock_run = mocker.patch("updater.gomod_excludes.run_command")

    result = apply_gomod_excludes_and_replaces(tmp_path)

    assert result is False
    calls = [str(c) for c in mock_run.call_args_list]
    assert not any("go mod download" in c for c in calls)


def test_apply_excludes_removes_obsolete_anthropic_replace(tmp_path, mocker):
    """Test that stale anthropic-sdk-go replace pin is actively dropped."""
    gomod = tmp_path / "go.mod"
    content = """module example.com/test

go 1.23

replace (
    github.com/anthropics/anthropic-sdk-go => github.com/anthropics/anthropic-sdk-go v1.26.0
)
"""
    gomod.write_text(content)

    mock_run = mocker.patch("updater.gomod_excludes.run_command")

    result = apply_gomod_excludes_and_replaces(tmp_path)

    assert result is True
    calls = [str(c) for c in mock_run.call_args_list]
    assert any("dropreplace" in c and "anthropic-sdk-go" in c for c in calls)


def test_tools_go_replaces_kept_when_tools_go_exists(tmp_path, mocker):
    """Test that tools.go-related replaces are kept when tools.go is present."""
    gomod = tmp_path / "go.mod"
    content = """module example.com/test

go 1.23

replace (
    github.com/charmbracelet/x/cellbuf => github.com/charmbracelet/x/cellbuf v0.0.15
    github.com/denis-tingaikin/go-header => github.com/denis-tingaikin/go-header v0.5.0
    github.com/diskfs/go-diskfs => github.com/diskfs/go-diskfs v1.7.0
    github.com/nunnatsa/ginkgolinter/types => github.com/nunnatsa/ginkgolinter v0.19.1
)
"""
    gomod.write_text(content)
    (tmp_path / "tools.go").write_text("//go:build tools\npackage tools\n")

    mock_run = mocker.patch("updater.gomod_excludes.run_command")

    result = apply_gomod_excludes_and_replaces(tmp_path)

    assert result is False  # No changes — tools.go present, replaces kept
    assert mock_run.call_count == 0


def test_tools_go_replaces_removed_when_tools_go_absent(tmp_path, mocker):
    """Test that tools.go-related replaces are dropped when tools.go is absent."""
    gomod = tmp_path / "go.mod"
    content = """module example.com/test

go 1.23

replace (
    github.com/charmbracelet/x/cellbuf => github.com/charmbracelet/x/cellbuf v0.0.15
    github.com/denis-tingaikin/go-header => github.com/denis-tingaikin/go-header v0.5.0
    github.com/diskfs/go-diskfs => github.com/diskfs/go-diskfs v1.7.0
    github.com/nunnatsa/ginkgolinter/types => github.com/nunnatsa/ginkgolinter v0.19.1
)
"""
    gomod.write_text(content)
    # No tools.go — project has migrated

    mock_run = mocker.patch("updater.gomod_excludes.run_command")

    result = apply_gomod_excludes_and_replaces(tmp_path)

    assert result is True  # 4 replaces removed
    calls = [str(c) for c in mock_run.call_args_list]
    assert any("dropreplace" in c and "cellbuf" in c for c in calls)
    assert any("dropreplace" in c and "go-header" in c for c in calls)
    assert any("dropreplace" in c and "go-diskfs" in c for c in calls)
    assert any("dropreplace" in c and "ginkgolinter" in c for c in calls)
