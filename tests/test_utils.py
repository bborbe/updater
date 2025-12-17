"""Tests for utility functions."""

from pathlib import Path

from updater.git_operations import find_git_repo
from updater.module_discovery import discover_go_modules


def test_find_git_repo_found(tmp_path):
    """Test find_git_repo when .git exists."""
    git_dir = tmp_path / ".git"
    git_dir.mkdir()

    result = find_git_repo(tmp_path)
    assert result == tmp_path


def test_find_git_repo_parent(tmp_path):
    """Test find_git_repo finds parent repository."""
    git_dir = tmp_path / ".git"
    git_dir.mkdir()

    subdir = tmp_path / "subdir" / "nested"
    subdir.mkdir(parents=True)

    result = find_git_repo(subdir)
    assert result == tmp_path


def test_find_git_repo_not_found(tmp_path):
    """Test find_git_repo returns None when no repo found."""
    result = find_git_repo(tmp_path)
    assert result is None


def test_discover_go_modules_empty(tmp_path):
    """Test discover_go_modules with no modules."""
    result = discover_go_modules(tmp_path)
    assert result == []


def test_discover_go_modules_single(tmp_path):
    """Test discover_go_modules with one module."""
    module_dir = tmp_path / "alert"
    module_dir.mkdir()
    (module_dir / "go.mod").write_text("module example.com/alert")

    result = discover_go_modules(tmp_path)
    assert len(result) == 1
    assert result[0] == module_dir


def test_discover_go_modules_multiple(tmp_path):
    """Test discover_go_modules with multiple modules."""
    for name in ["alert", "bigquery", "core"]:
        module_dir = tmp_path / name
        module_dir.mkdir()
        (module_dir / "go.mod").write_text(f"module example.com/{name}")

    result = discover_go_modules(tmp_path)
    assert len(result) == 3
    # Results should be sorted
    assert result[0].name == "alert"
    assert result[1].name == "bigquery"
    assert result[2].name == "core"


def test_discover_go_modules_skips_files(tmp_path):
    """Test discover_go_modules ignores files."""
    # Create a file named go.mod in parent (should be ignored)
    (tmp_path / "go.mod").write_text("module example.com/parent")

    # Create a proper module directory
    module_dir = tmp_path / "alert"
    module_dir.mkdir()
    (module_dir / "go.mod").write_text("module example.com/alert")

    result = discover_go_modules(tmp_path)
    assert len(result) == 1
    assert result[0] == module_dir


def test_discover_go_modules_skips_non_go(tmp_path):
    """Test discover_go_modules skips directories without go.mod."""
    # Directory without go.mod
    (tmp_path / "notamodule").mkdir()

    # Directory with go.mod
    module_dir = tmp_path / "realmodule"
    module_dir.mkdir()
    (module_dir / "go.mod").write_text("module example.com/realmodule")

    result = discover_go_modules(tmp_path)
    assert len(result) == 1
    assert result[0] == module_dir


def test_discover_go_modules_recursive_monorepo(tmp_path):
    """Test recursive discovery with lib/ prioritization (monorepo pattern)."""
    # Create structure:
    # lib/alert, lib/core (priority 1 - base packages)
    # service1 (priority 2 - root service)
    # module-a/lib/something (priority 3 - module-a package)
    # module-a/service2 (priority 4 - module-a service)

    # Root-level lib packages
    lib_alert = tmp_path / "lib" / "alert"
    lib_alert.mkdir(parents=True)
    (lib_alert / "go.mod").write_text("module example.com/lib/alert")

    lib_core = tmp_path / "lib" / "core"
    lib_core.mkdir(parents=True)
    (lib_core / "go.mod").write_text("module example.com/lib/core")

    # Root-level service
    service1 = tmp_path / "service1"
    service1.mkdir()
    (service1 / "go.mod").write_text("module example.com/service1")

    # Subdirectory with lib/
    module_a_lib = tmp_path / "module-a" / "lib" / "something"
    module_a_lib.mkdir(parents=True)
    (module_a_lib / "go.mod").write_text("module example.com/module-a/lib/something")

    module_a_service = tmp_path / "module-a" / "service2"
    module_a_service.mkdir(parents=True)
    (module_a_service / "go.mod").write_text("module example.com/module-a/service2")

    result = discover_go_modules(tmp_path, recursive=True)

    assert len(result) == 5

    # Verify order: lib/* first, then service1, then module-a/lib/*, then module-a/*
    relative_paths = [str(m.relative_to(tmp_path)) for m in result]

    # lib/ packages should come first (alphabetically)
    assert relative_paths[0] == "lib/alert"
    assert relative_paths[1] == "lib/core"

    # Root-level service
    assert relative_paths[2] == "service1"

    # module-a/lib/ before module-a/service
    assert relative_paths[3] == "module-a/lib/something"
    assert relative_paths[4] == "module-a/service2"


def test_discover_go_modules_recursive_skips_vendor(tmp_path):
    """Test recursive discovery skips vendor directories."""
    # Regular module
    module = tmp_path / "alert"
    module.mkdir()
    (module / "go.mod").write_text("module example.com/alert")

    # Module in vendor (should be skipped)
    vendor_module = tmp_path / "vendor" / "github.com" / "some" / "dep"
    vendor_module.mkdir(parents=True)
    (vendor_module / "go.mod").write_text("module github.com/some/dep")

    result = discover_go_modules(tmp_path, recursive=True)

    assert len(result) == 1
    assert result[0] == module


def test_discover_go_modules_recursive_complex_structure(tmp_path):
    """Test recursive discovery with complex nested structure."""
    # Create monorepo structure:
    # lib/alert, lib/bolt (base packages)
    # api-gateway (root service)
    # module-a/lib/client, module-a/lib/types (module-a packages)
    # module-a/service1, module-a/service2 (module-a services)
    # module-b/lib/template (module-b packages)
    # module-b/sender (module-b services)

    modules_structure = [
        "lib/alert",
        "lib/bolt",
        "api-gateway",
        "module-a/lib/client",
        "module-a/lib/types",
        "module-a/service1",
        "module-a/service2",
        "module-b/lib/template",
        "module-b/sender",
    ]

    for mod_path in modules_structure:
        full_path = tmp_path / mod_path
        full_path.mkdir(parents=True)
        (full_path / "go.mod").write_text(f"module example.com/{mod_path}")

    result = discover_go_modules(tmp_path, recursive=True)
    relative_paths = [str(m.relative_to(tmp_path)) for m in result]

    # Verify lib/ packages come first
    assert relative_paths[0] == "lib/alert"
    assert relative_paths[1] == "lib/bolt"

    # Root-level service
    assert "api-gateway" in relative_paths[2:4]  # Before subdirectory modules

    # Within each subdirectory, lib/ comes first
    module_a_start = relative_paths.index("module-a/lib/client")
    module_b_start = relative_paths.index("module-b/lib/template")

    # module-a/lib/* before module-a/*
    assert relative_paths[module_a_start] == "module-a/lib/client"
    assert relative_paths[module_a_start + 1] == "module-a/lib/types"
    assert "module-a/service1" in relative_paths[module_a_start + 2:]
    assert "module-a/service2" in relative_paths[module_a_start + 2:]

    # module-b/lib/* before module-b/*
    assert relative_paths[module_b_start] == "module-b/lib/template"
    assert "module-b/sender" in relative_paths[module_b_start + 1:]
