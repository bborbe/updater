"""Tests for go.mod excludes and replaces."""

import pytest

from updater.gomod_excludes import (
    EXCLUDE_CONFLICT_PHRASES,
    STRUCTURED_MERGE_DIFF_V7_EXCLUDE,
    apply_gomod_excludes_and_replaces,
    drop_exclude,
    is_exclude_conflict,
    read_gomod_excludes_and_replaces,
)
from updater.pipeline import GoDepUpdateStep, StepStatus

# Verbatim conflict text Go prints from `go get <module>@latest` when the exclude
# has removed a package the graph imports.
GO_GET_CONFLICT_TEXT = (
    "sigs.k8s.io/structured-merge-diff/v7/merge: cannot find module providing "
    "package sigs.k8s.io/structured-merge-diff/v7/merge"
)

# Verbatim conflict text Go prints from the trailing `go mod tidy` for the same
# root cause — a different phrasing of the same conflict.
GO_MOD_TIDY_CONFLICT_TEXT = (
    "sigs.k8s.io/structured-merge-diff/v7/merge: module "
    "sigs.k8s.io/structured-merge-diff@latest found (v1.0.2), but does not "
    "contain package sigs.k8s.io/structured-merge-diff/v7/merge"
)


def _write_gomod_with_v7_exclude(tmp_path):
    """Write a go.mod carrying the structured-merge-diff v7 exclude."""
    gomod = tmp_path / "go.mod"
    gomod.write_text(
        "module example.com/test\n\ngo 1.23\n\n"
        "exclude sigs.k8s.io/structured-merge-diff/v7 v7.0.0\n"
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
    """Test that a go.mod already carrying every STANDARD exclude produces no
    changes — nothing to add, and nothing to drop (cloud.google.com/go is not
    listed in OBSOLETE_EXCLUDES_PREFIXES)."""
    gomod = tmp_path / "go.mod"
    gomod.write_text(
        "module example.com/test\n\ngo 1.23\n\n"
        "exclude cloud.google.com/go v0.26.0\n"
        "exclude sigs.k8s.io/structured-merge-diff/v7 v7.0.0\n"
    )

    # Mock run_command to avoid actual go mod edit calls
    mock_run = mocker.patch("updater.gomod_excludes.run_command")

    result = apply_gomod_excludes_and_replaces(tmp_path)

    assert result is False  # Standard excludes already present, nothing to add
    assert mock_run.call_count == 0  # No commands run


def test_apply_excludes_idempotent(tmp_path, mocker):
    """Test that applying with all standard excludes and all tools.go-era replaces
    present makes no changes when tools.go exists (un-migrated project).
    """
    gomod = tmp_path / "go.mod"
    content = """module example.com/test

go 1.23

exclude cloud.google.com/go v0.26.0
exclude sigs.k8s.io/structured-merge-diff/v7 v7.0.0

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
    """Test that old non-k8s excludes are removed as obsolete.

    cloud.google.com/go@v0.26.0 is left untouched: it is neither a STANDARD
    exclude (it was dropped from STANDARD_EXCLUDES) nor listed in
    OBSOLETE_EXCLUDES_PREFIXES (nothing is actively removed).
    """
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
    sigs.k8s.io/structured-merge-diff/v7 v7.0.0
)
"""
    gomod.write_text(content)

    mock_run = mocker.patch("updater.gomod_excludes.run_command")

    result = apply_gomod_excludes_and_replaces(tmp_path)

    assert result is True  # Changes made — obsolete excludes removed
    # 8 dropexclude (cloud.google.com/go retained) + 1 go mod download
    assert mock_run.call_count == 9
    calls = [str(c) for c in mock_run.call_args_list]
    assert not any("dropexclude" in c and "cloud.google.com/go" in c for c in calls)


def test_apply_does_not_add_cloud_google_exclude(tmp_path, mocker):
    """Test that cloud.google.com/go is NOT added — it was dropped from
    STANDARD_EXCLUDES and the only standard exclude is structured-merge-diff/v7."""
    gomod = tmp_path / "go.mod"
    gomod.write_text("module example.com/test\n\ngo 1.23\n")

    mock_run = mocker.patch("updater.gomod_excludes.run_command")

    result = apply_gomod_excludes_and_replaces(tmp_path)

    assert result is True  # The structured-merge-diff/v7 exclude is added
    calls = [str(c) for c in mock_run.call_args_list]
    assert not any("cloud.google.com/go" in c for c in calls)


def test_apply_adds_structured_merge_diff_v7_exclude(tmp_path, mocker):
    """Test that the standard structured-merge-diff/v7 exclude is added to a
    go.mod that lacks it, followed by go mod download."""
    gomod = tmp_path / "go.mod"
    gomod.write_text("module example.com/test\n\ngo 1.23\n")

    mock_run = mocker.patch("updater.gomod_excludes.run_command")

    result = apply_gomod_excludes_and_replaces(tmp_path)

    assert result is True
    commands = [c.args[0] for c in mock_run.call_args_list]
    assert commands == [
        "go mod edit -exclude sigs.k8s.io/structured-merge-diff/v7@v7.0.0",
        "go mod download",
    ]


def test_apply_skips_structured_merge_diff_v7_exclude_when_present(tmp_path, mocker):
    """Test that a go.mod already excluding structured-merge-diff/v7 makes no
    changes — the standard exclude is not re-added."""
    gomod = tmp_path / "go.mod"
    gomod.write_text(
        "module example.com/test\n\ngo 1.23\n\n"
        "exclude sigs.k8s.io/structured-merge-diff/v7 v7.0.0\n"
    )

    mock_run = mocker.patch("updater.gomod_excludes.run_command")

    result = apply_gomod_excludes_and_replaces(tmp_path)

    assert result is False  # Already present, nothing to add or drop
    assert mock_run.call_count == 0


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
    # The v6 exclude is dropped while the v7 exclude is added in the same pass
    assert any(
        "go mod edit -exclude sigs.k8s.io/structured-merge-diff/v7@v7.0.0" in c for c in calls
    )


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

exclude cloud.google.com/go v0.26.0
exclude sigs.k8s.io/structured-merge-diff/v7 v7.0.0

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

exclude cloud.google.com/go v0.26.0
exclude sigs.k8s.io/structured-merge-diff/v7 v7.0.0

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


# ---------------------------------------------------------------------------
# is_exclude_conflict
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("phrase", EXCLUDE_CONFLICT_PHRASES)
def test_is_exclude_conflict_true_for_each_phrase(phrase):
    """Every phrase in EXCLUDE_CONFLICT_PHRASES is a conflict when v7 is named."""
    error_text = f"sigs.k8s.io/structured-merge-diff/v7/merge: {phrase}"

    assert is_exclude_conflict(error_text) is True


def test_is_exclude_conflict_false_when_v7_named_without_phrase():
    """Naming v7 alone is not enough — a conflict phrase must also be present."""
    error_text = "sigs.k8s.io/structured-merge-diff/v7/merge: some unrelated failure"

    assert is_exclude_conflict(error_text) is False


def test_is_exclude_conflict_false_when_phrase_without_v7():
    """A conflict phrase about another module is not this conflict."""
    error_text = "example.com/other: cannot find module providing package example.com/other"

    assert is_exclude_conflict(error_text) is False


def test_is_exclude_conflict_false_when_neither():
    """Neither v7 nor a conflict phrase — not this conflict."""
    assert is_exclude_conflict("command failed for unrelated reasons") is False


# ---------------------------------------------------------------------------
# drop_exclude
# ---------------------------------------------------------------------------


def test_drop_exclude_present(tmp_path, mocker):
    """Dropping a present exclude runs go mod edit -dropexclude then go mod download."""
    _write_gomod_with_v7_exclude(tmp_path)

    mock_run = mocker.patch("updater.gomod_excludes.run_command")

    assert drop_exclude(tmp_path, STRUCTURED_MERGE_DIFF_V7_EXCLUDE) is True

    calls = [c.args[0] for c in mock_run.call_args_list]
    assert calls[0] == ("go mod edit -dropexclude sigs.k8s.io/structured-merge-diff/v7@v7.0.0")
    assert calls[1] == "go mod download"


def test_drop_exclude_absent(tmp_path, mocker):
    """An absent exclude returns False and runs no go mod edit."""
    gomod = tmp_path / "go.mod"
    gomod.write_text("module example.com/test\n\ngo 1.23\n")

    mock_run = mocker.patch("updater.gomod_excludes.run_command")

    assert drop_exclude(tmp_path, STRUCTURED_MERGE_DIFF_V7_EXCLUDE) is False
    assert mock_run.call_count == 0


# ---------------------------------------------------------------------------
# GoDepUpdateStep — v7 exclude back-off regression
# ---------------------------------------------------------------------------


async def test_go_dep_update_step_backs_off_v7_exclude_on_go_get_conflict(tmp_path, mocker):
    """A go-get-phrased exclude conflict drops the exclude and retries once."""
    _write_gomod_with_v7_exclude(tmp_path)

    mock_update = mocker.patch("updater.pipeline.update_go_dependencies")
    mock_update.side_effect = [RuntimeError(GO_GET_CONFLICT_TEXT), False]
    mock_run = mocker.patch("updater.gomod_excludes.run_command")

    result = await GoDepUpdateStep().run(tmp_path, {})

    calls = [c.args[0] for c in mock_run.call_args_list]
    assert "go mod edit -dropexclude sigs.k8s.io/structured-merge-diff/v7@v7.0.0" in calls
    assert mock_update.call_count == 2
    assert result.status == StepStatus.SUCCESS


async def test_go_dep_update_step_backs_off_v7_exclude_on_tidy_conflict(tmp_path, mocker):
    """A tidy-phrased exclude conflict drops the exclude and retries once."""
    _write_gomod_with_v7_exclude(tmp_path)

    mock_update = mocker.patch("updater.pipeline.update_go_dependencies")
    mock_update.side_effect = [RuntimeError(GO_MOD_TIDY_CONFLICT_TEXT), False]
    mock_run = mocker.patch("updater.gomod_excludes.run_command")

    result = await GoDepUpdateStep().run(tmp_path, {})

    calls = [c.args[0] for c in mock_run.call_args_list]
    assert "go mod edit -dropexclude sigs.k8s.io/structured-merge-diff/v7@v7.0.0" in calls
    assert mock_update.call_count == 2
    assert result.status == StepStatus.SUCCESS
