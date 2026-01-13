"""Tests for Go module discovery and sorting."""

import pytest

from updater.module_discovery import _module_sort_key, discover_go_modules


@pytest.fixture
def monorepo_structure(tmp_path):
    """Create a monorepo structure for testing.

    Structure:
    tmp_path/
        lib/
            alert/go.mod
            core/go.mod
        service1/go.mod
        service2/go.mod
        k8s/
            lib/
                util/go.mod
            deployer/go.mod
            monitor/go.mod
        raw/
            api/go.mod
    """
    # Root lib modules
    lib_alert = tmp_path / "lib" / "alert"
    lib_alert.mkdir(parents=True)
    (lib_alert / "go.mod").write_text("module lib/alert\n")

    lib_core = tmp_path / "lib" / "core"
    lib_core.mkdir(parents=True)
    (lib_core / "go.mod").write_text("module lib/core\n")

    # Root services
    service1 = tmp_path / "service1"
    service1.mkdir()
    (service1 / "go.mod").write_text("module service1\n")

    service2 = tmp_path / "service2"
    service2.mkdir()
    (service2 / "go.mod").write_text("module service2\n")

    # k8s subdirectory with lib
    k8s_lib_util = tmp_path / "k8s" / "lib" / "util"
    k8s_lib_util.mkdir(parents=True)
    (k8s_lib_util / "go.mod").write_text("module k8s/lib/util\n")

    k8s_deployer = tmp_path / "k8s" / "deployer"
    k8s_deployer.mkdir(parents=True)
    (k8s_deployer / "go.mod").write_text("module k8s/deployer\n")

    k8s_monitor = tmp_path / "k8s" / "monitor"
    k8s_monitor.mkdir(parents=True)
    (k8s_monitor / "go.mod").write_text("module k8s/monitor\n")

    # raw subdirectory (no lib)
    raw_api = tmp_path / "raw" / "api"
    raw_api.mkdir(parents=True)
    (raw_api / "go.mod").write_text("module raw/api\n")

    return tmp_path


class TestModuleSortKey:
    """Tests for _module_sort_key function."""

    def test_root_lib_module_priority(self, tmp_path):
        """Test that root lib/ modules have highest priority."""
        parent = tmp_path
        lib_path = tmp_path / "lib"

        key = _module_sort_key(lib_path, parent)

        # lib at root should be (0, "lib")
        assert key[0] == 0
        assert key[1] == "lib"

    def test_root_lib_submodule_priority(self, tmp_path):
        """Test that lib/submodule has highest priority."""
        parent = tmp_path
        lib_alert = tmp_path / "lib" / "alert"

        key = _module_sort_key(lib_alert, parent)

        # lib/alert should be (0, "lib", "alert")
        assert key[0] == 0
        assert key[1] == "lib"
        assert key[2] == "alert"

    def test_root_service_priority(self, tmp_path):
        """Test that root services have second priority."""
        parent = tmp_path
        service1 = tmp_path / "service1"

        key = _module_sort_key(service1, parent)

        # service1 should be (1, "service1")
        assert key[0] == 1
        assert key[1] == "service1"

    def test_subdirectory_lib_priority(self, tmp_path):
        """Test that subdirectory lib/ modules come before subdirectory services."""
        parent = tmp_path
        k8s_lib = tmp_path / "k8s" / "lib" / "util"

        key = _module_sort_key(k8s_lib, parent)

        # k8s/lib/util should be (2, "k8s", 0, "lib", "util")
        assert key[0] == 2
        assert key[1] == "k8s"
        assert key[2] == 0  # lib has priority 0 within subdirectory

    def test_subdirectory_service_priority(self, tmp_path):
        """Test that subdirectory services come after subdirectory lib/."""
        parent = tmp_path
        k8s_deployer = tmp_path / "k8s" / "deployer"

        key = _module_sort_key(k8s_deployer, parent)

        # k8s/deployer should be (2, "k8s", 1, "deployer")
        assert key[0] == 2
        assert key[1] == "k8s"
        assert key[2] == 1  # non-lib has priority 1 within subdirectory

    def test_relative_to_failure_fallback(self, tmp_path):
        """Test fallback when relative_to fails."""
        parent = tmp_path / "parent"
        module_dir = tmp_path / "different"
        module_dir.mkdir(parents=True)
        module = module_dir / "path"
        module.mkdir()

        key = _module_sort_key(module, parent)

        # Should still return a valid key (uses the path as-is for sorting)
        assert isinstance(key, tuple)
        # When relative_to fails, it uses the module path directly which gives (2, ...)
        assert key[0] in (1, 2, 999)  # Various fallback priorities based on path structure


class TestDiscoverGoModules:
    """Tests for discover_go_modules function."""

    def test_non_recursive_single_level(self, tmp_path):
        """Test non-recursive discovery in single level."""
        # Create modules at root level
        mod1 = tmp_path / "mod1"
        mod1.mkdir()
        (mod1 / "go.mod").write_text("module mod1\n")

        mod2 = tmp_path / "mod2"
        mod2.mkdir()
        (mod2 / "go.mod").write_text("module mod2\n")

        modules = discover_go_modules(tmp_path, recursive=False)

        assert len(modules) == 2
        assert mod1 in modules
        assert mod2 in modules

    def test_non_recursive_skips_nested(self, tmp_path):
        """Test that non-recursive mode skips nested modules."""
        # Root module
        root_mod = tmp_path / "root"
        root_mod.mkdir()
        (root_mod / "go.mod").write_text("module root\n")

        # Nested module
        nested = tmp_path / "parent" / "nested"
        nested.mkdir(parents=True)
        (nested / "go.mod").write_text("module nested\n")

        modules = discover_go_modules(tmp_path, recursive=False)

        # Should only find root module, not nested
        assert len(modules) == 1
        assert root_mod in modules
        assert nested not in modules

    def test_recursive_finds_all_nested(self, tmp_path):
        """Test that recursive mode finds all nested modules."""
        # Root module
        root_mod = tmp_path / "root"
        root_mod.mkdir()
        (root_mod / "go.mod").write_text("module root\n")

        # Nested modules at various depths
        nested1 = tmp_path / "parent" / "nested1"
        nested1.mkdir(parents=True)
        (nested1 / "go.mod").write_text("module nested1\n")

        nested2 = tmp_path / "parent" / "child" / "nested2"
        nested2.mkdir(parents=True)
        (nested2 / "go.mod").write_text("module nested2\n")

        modules = discover_go_modules(tmp_path, recursive=True)

        assert len(modules) == 3
        assert root_mod in modules
        assert nested1 in modules
        assert nested2 in modules

    def test_recursive_skips_vendor(self, tmp_path):
        """Test that vendor directories are skipped."""
        # Regular module
        regular = tmp_path / "regular"
        regular.mkdir()
        (regular / "go.mod").write_text("module regular\n")

        # Module in vendor (should be skipped)
        vendor_mod = tmp_path / "vendor" / "github.com" / "foo" / "bar"
        vendor_mod.mkdir(parents=True)
        (vendor_mod / "go.mod").write_text("module vendor\n")

        modules = discover_go_modules(tmp_path, recursive=True)

        assert len(modules) == 1
        assert regular in modules
        assert vendor_mod not in modules

    def test_monorepo_ordering(self, monorepo_structure):
        """Test correct ordering of modules in monorepo."""
        modules = discover_go_modules(monorepo_structure, recursive=True)

        # Convert to names for easier assertion
        names = [m.relative_to(monorepo_structure).as_posix() for m in modules]

        # Check expected order:
        # 1. Root lib/ modules (lib/alert, lib/core - alphabetical)
        # 2. Root services (service1, service2 - alphabetical)
        # 3. k8s/lib/ modules (k8s/lib/util)
        # 4. k8s services (k8s/deployer, k8s/monitor - alphabetical)
        # 5. raw services (raw/api)

        assert names[0].startswith("lib/")
        assert names[1].startswith("lib/")
        assert names[2] == "service1"
        assert names[3] == "service2"
        assert names[4] == "k8s/lib/util"
        assert names[5].startswith("k8s/") and "lib" not in names[5]
        assert names[6].startswith("k8s/") and "lib" not in names[6]
        assert names[7] == "raw/api"

    def test_lib_modules_before_services_at_same_level(self, monorepo_structure):
        """Test that lib/ modules come before service modules at the same directory level."""
        modules = discover_go_modules(monorepo_structure, recursive=True)

        names = [m.relative_to(monorepo_structure).as_posix() for m in modules]

        # Within root level: lib/ modules should come before root services
        root_lib = [i for i, name in enumerate(names) if name.startswith("lib/")]
        root_services = [
            i for i, name in enumerate(names) if "/" not in name or name in ["service1", "service2"]
        ]
        root_services = [i for i in root_services if not names[i].startswith("lib")]

        if root_lib and root_services:
            assert max(root_lib) < min(root_services)

        # Within k8s/ subdirectory: k8s/lib/ should come before k8s services
        k8s_lib = [i for i, name in enumerate(names) if name.startswith("k8s/lib/")]
        k8s_services = [
            i for i, name in enumerate(names) if name.startswith("k8s/") and "lib" not in name
        ]

        if k8s_lib and k8s_services:
            assert max(k8s_lib) < min(k8s_services)

    def test_empty_directory(self, tmp_path):
        """Test discovery in empty directory."""
        modules = discover_go_modules(tmp_path, recursive=True)

        assert len(modules) == 0

    def test_directory_without_go_mod(self, tmp_path):
        """Test that directories without go.mod are skipped."""
        no_mod = tmp_path / "no-mod"
        no_mod.mkdir()
        (no_mod / "main.go").write_text("package main\n")

        modules = discover_go_modules(tmp_path, recursive=True)

        assert len(modules) == 0

    def test_multiple_lib_submodules_sorted(self, tmp_path):
        """Test that multiple lib/ submodules are sorted alphabetically."""
        # Create lib/z, lib/a, lib/m
        lib_z = tmp_path / "lib" / "z"
        lib_z.mkdir(parents=True)
        (lib_z / "go.mod").write_text("module lib/z\n")

        lib_a = tmp_path / "lib" / "a"
        lib_a.mkdir(parents=True)
        (lib_a / "go.mod").write_text("module lib/a\n")

        lib_m = tmp_path / "lib" / "m"
        lib_m.mkdir(parents=True)
        (lib_m / "go.mod").write_text("module lib/m\n")

        modules = discover_go_modules(tmp_path, recursive=True)

        names = [m.name for m in modules]

        # Should be alphabetically sorted: a, m, z
        assert names == ["a", "m", "z"]

    def test_subdirectory_lib_before_subdirectory_services(self, tmp_path):
        """Test that within a subdirectory, lib/ comes before services."""
        # Create k8s/lib/util and k8s/service1
        k8s_lib = tmp_path / "k8s" / "lib" / "util"
        k8s_lib.mkdir(parents=True)
        (k8s_lib / "go.mod").write_text("module k8s/lib/util\n")

        k8s_service = tmp_path / "k8s" / "service1"
        k8s_service.mkdir(parents=True)
        (k8s_service / "go.mod").write_text("module k8s/service1\n")

        modules = discover_go_modules(tmp_path, recursive=True)

        # k8s/lib/util should come before k8s/service1
        assert modules[0] == k8s_lib
        assert modules[1] == k8s_service

    def test_non_recursive_alphabetical_order(self, tmp_path):
        """Test that non-recursive mode maintains alphabetical order."""
        # Create modules: z, a, m
        mod_z = tmp_path / "z"
        mod_z.mkdir()
        (mod_z / "go.mod").write_text("module z\n")

        mod_a = tmp_path / "a"
        mod_a.mkdir()
        (mod_a / "go.mod").write_text("module a\n")

        mod_m = tmp_path / "m"
        mod_m.mkdir()
        (mod_m / "go.mod").write_text("module m\n")

        modules = discover_go_modules(tmp_path, recursive=False)

        names = [m.name for m in modules]

        # Should be alphabetically sorted
        assert names == ["a", "m", "z"]

    def test_deeply_nested_lib(self, tmp_path):
        """Test discovery of deeply nested lib/ modules."""
        deep_lib = tmp_path / "level1" / "level2" / "level3" / "lib" / "util"
        deep_lib.mkdir(parents=True)
        (deep_lib / "go.mod").write_text("module lib/util\n")

        modules = discover_go_modules(tmp_path, recursive=True)

        assert len(modules) == 1
        assert modules[0] == deep_lib

    def test_mixed_lib_and_non_lib_at_root(self, tmp_path):
        """Test correct ordering when mixing lib/ and non-lib at root."""
        # Create lib/a, service1, lib/z, service2
        lib_a = tmp_path / "lib" / "a"
        lib_a.mkdir(parents=True)
        (lib_a / "go.mod").write_text("module lib/a\n")

        service1 = tmp_path / "service1"
        service1.mkdir()
        (service1 / "go.mod").write_text("module service1\n")

        lib_z = tmp_path / "lib" / "z"
        lib_z.mkdir(parents=True)
        (lib_z / "go.mod").write_text("module lib/z\n")

        service2 = tmp_path / "service2"
        service2.mkdir()
        (service2 / "go.mod").write_text("module service2\n")

        modules = discover_go_modules(tmp_path, recursive=True)

        names = [m.relative_to(tmp_path).as_posix() for m in modules]

        # lib/a and lib/z should come before service1 and service2
        assert names[0] == "lib/a"
        assert names[1] == "lib/z"
        assert names[2] == "service1"
        assert names[3] == "service2"
