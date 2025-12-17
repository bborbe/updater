"""Tests for go.mod excludes and replaces."""

from pathlib import Path

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
    """Test applying excludes to go.mod with no existing excludes."""
    gomod = tmp_path / "go.mod"
    gomod.write_text("module example.com/test\n\ngo 1.23\n")

    # Mock run_command to avoid actual go mod edit calls
    mock_run = mocker.patch('updater.gomod_excludes.run_command')

    result = apply_gomod_excludes_and_replaces(tmp_path)

    assert result is True  # Changes were made
    # Should have called go mod edit for each exclude and replace
    assert mock_run.call_count > 0


def test_apply_excludes_idempotent(tmp_path, mocker):
    """Test that applying excludes twice doesn't duplicate them."""
    gomod = tmp_path / "go.mod"
    # Pre-populate with all standard excludes and replaces
    content = """module example.com/test

go 1.23

exclude (
    cloud.google.com/go v0.26.0
    k8s.io/api v0.34.0
    k8s.io/api v0.34.1
    k8s.io/api v0.34.2
    k8s.io/api v0.34.3
    k8s.io/client-go v0.34.0
    k8s.io/client-go v0.34.1
    k8s.io/client-go v0.34.2
    k8s.io/client-go v0.34.3
    k8s.io/code-generator v0.34.0
    k8s.io/code-generator v0.34.1
    k8s.io/code-generator v0.34.2
    k8s.io/code-generator v0.34.3
    k8s.io/apiextensions-apiserver v0.34.0
    k8s.io/apiextensions-apiserver v0.34.1
    k8s.io/apiextensions-apiserver v0.34.2
    k8s.io/apiextensions-apiserver v0.34.3
    k8s.io/apimachinery v0.34.0
    k8s.io/apimachinery v0.34.1
    k8s.io/apimachinery v0.34.2
    k8s.io/apimachinery v0.34.3
    github.com/go-logr/glogr v1.0.0-rc1
    github.com/go-logr/glogr v1.0.0
    github.com/go-logr/logr v1.0.0-rc1
    github.com/go-logr/logr v1.0.0
    go.yaml.in/yaml/v3 v3.0.3
    go.yaml.in/yaml/v3 v3.0.4
    golang.org/x/tools v0.38.0
    golang.org/x/tools v0.39.0
    sigs.k8s.io/structured-merge-diff/v6 v6.0.0
    sigs.k8s.io/structured-merge-diff/v6 v6.1.0
    sigs.k8s.io/structured-merge-diff/v6 v6.2.0
    sigs.k8s.io/structured-merge-diff/v6 v6.3.0
)

replace k8s.io/kube-openapi => k8s.io/kube-openapi v0.0.0-20250701173324-9bd5c66d9911
"""
    gomod.write_text(content)

    # Mock run_command to avoid actual go mod edit calls
    mock_run = mocker.patch('updater.gomod_excludes.run_command')

    result = apply_gomod_excludes_and_replaces(tmp_path)

    assert result is False  # No changes needed
    assert mock_run.call_count == 0  # No commands run


def test_apply_excludes_missing_gomod(tmp_path):
    """Test applying excludes when go.mod doesn't exist."""
    result = apply_gomod_excludes_and_replaces(tmp_path)

    assert result is False  # No changes made
