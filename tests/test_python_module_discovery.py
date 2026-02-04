"""Tests for Python module discovery."""

import pytest

from updater.module_discovery import (
    discover_all_modules,
    discover_python_modules,
    is_legacy_python_project,
)


@pytest.fixture
def python_project(tmp_path):
    """Create a modern Python project with pyproject.toml + uv.lock."""
    project = tmp_path / "myproject"
    project.mkdir()
    (project / "pyproject.toml").write_text("[project]\nname = 'myproject'\n")
    (project / "uv.lock").write_text("# uv lockfile\n")
    return project


@pytest.fixture
def legacy_python_project(tmp_path):
    """Create a legacy Python project with only requirements.txt."""
    project = tmp_path / "legacy"
    project.mkdir()
    (project / "requirements.txt").write_text("requests>=2.0\n")
    return project


@pytest.fixture
def go_project(tmp_path):
    """Create a Go project with go.mod."""
    project = tmp_path / "goproject"
    project.mkdir()
    (project / "go.mod").write_text("module goproject\ngo 1.23\n")
    return project


@pytest.fixture
def mixed_monorepo(tmp_path):
    """Create a monorepo with both Go and Python projects.

    Structure:
    tmp_path/
        go-service/go.mod
        python-api/pyproject.toml, uv.lock
        python-worker/pyproject.toml, uv.lock
        legacy-script/requirements.txt (legacy, should be skipped)
        lib/
            go-lib/go.mod
    """
    # Go service
    go_svc = tmp_path / "go-service"
    go_svc.mkdir()
    (go_svc / "go.mod").write_text("module go-service\ngo 1.23\n")

    # Python API
    py_api = tmp_path / "python-api"
    py_api.mkdir()
    (py_api / "pyproject.toml").write_text("[project]\nname = 'api'\n")
    (py_api / "uv.lock").write_text("# uv lockfile\n")

    # Python worker
    py_worker = tmp_path / "python-worker"
    py_worker.mkdir()
    (py_worker / "pyproject.toml").write_text("[project]\nname = 'worker'\n")
    (py_worker / "uv.lock").write_text("# uv lockfile\n")

    # Legacy Python (should be detected as legacy)
    legacy = tmp_path / "legacy-script"
    legacy.mkdir()
    (legacy / "requirements.txt").write_text("requests>=2.0\n")

    # Go lib
    go_lib = tmp_path / "lib" / "go-lib"
    go_lib.mkdir(parents=True)
    (go_lib / "go.mod").write_text("module lib/go-lib\ngo 1.23\n")

    return tmp_path


class TestDiscoverPythonModules:
    """Tests for discover_python_modules function."""

    def test_finds_python_project(self, tmp_path, python_project):
        """Test finding a single Python project."""
        modules = discover_python_modules(tmp_path, recursive=True)

        assert len(modules) == 1
        assert python_project in modules

    def test_skips_legacy_project(self, tmp_path, legacy_python_project):
        """Test that legacy projects (requirements.txt only) are not included."""
        modules = discover_python_modules(tmp_path, recursive=True)

        assert len(modules) == 0
        assert legacy_python_project not in modules

    def test_requires_both_pyproject_and_uvlock(self, tmp_path):
        """Test that both pyproject.toml and uv.lock are required."""
        # Only pyproject.toml (no uv.lock)
        pyproject_only = tmp_path / "pyproject-only"
        pyproject_only.mkdir()
        (pyproject_only / "pyproject.toml").write_text("[project]\nname = 'test'\n")

        # Only uv.lock (no pyproject.toml) - unusual but test it
        uvlock_only = tmp_path / "uvlock-only"
        uvlock_only.mkdir()
        (uvlock_only / "uv.lock").write_text("# uv lockfile\n")

        modules = discover_python_modules(tmp_path, recursive=True)

        assert len(modules) == 0

    def test_finds_nested_python_projects(self, tmp_path):
        """Test finding nested Python projects recursively."""
        # Nested project
        nested = tmp_path / "services" / "api"
        nested.mkdir(parents=True)
        (nested / "pyproject.toml").write_text("[project]\nname = 'api'\n")
        (nested / "uv.lock").write_text("# uv lockfile\n")

        # Deep nested project
        deep = tmp_path / "apps" / "internal" / "worker"
        deep.mkdir(parents=True)
        (deep / "pyproject.toml").write_text("[project]\nname = 'worker'\n")
        (deep / "uv.lock").write_text("# uv lockfile\n")

        modules = discover_python_modules(tmp_path, recursive=True)

        assert len(modules) == 2
        assert nested in modules
        assert deep in modules

    def test_non_recursive_only_direct_children(self, tmp_path):
        """Test non-recursive mode only finds direct children."""
        # Direct child
        direct = tmp_path / "direct"
        direct.mkdir()
        (direct / "pyproject.toml").write_text("[project]\nname = 'direct'\n")
        (direct / "uv.lock").write_text("# uv lockfile\n")

        # Nested (should not be found in non-recursive)
        nested = tmp_path / "parent" / "nested"
        nested.mkdir(parents=True)
        (nested / "pyproject.toml").write_text("[project]\nname = 'nested'\n")
        (nested / "uv.lock").write_text("# uv lockfile\n")

        modules = discover_python_modules(tmp_path, recursive=False)

        assert len(modules) == 1
        assert direct in modules
        assert nested not in modules

    def test_skips_venv_directory(self, tmp_path):
        """Test that .venv directories are skipped."""
        # Real project
        project = tmp_path / "project"
        project.mkdir()
        (project / "pyproject.toml").write_text("[project]\nname = 'project'\n")
        (project / "uv.lock").write_text("# uv lockfile\n")

        # Venv with pyproject.toml (should be skipped)
        venv = project / ".venv" / "lib" / "python3.12"
        venv.mkdir(parents=True)
        (venv / "pyproject.toml").write_text("[project]\nname = 'venv'\n")
        (venv / "uv.lock").write_text("# uv lockfile\n")

        modules = discover_python_modules(tmp_path, recursive=True)

        assert len(modules) == 1
        assert project in modules

    def test_empty_directory(self, tmp_path):
        """Test discovery in empty directory."""
        modules = discover_python_modules(tmp_path, recursive=True)

        assert len(modules) == 0

    def test_alphabetical_order(self, tmp_path):
        """Test that modules are returned in alphabetical order."""
        # Create in reverse order: z, m, a
        for name in ["z", "m", "a"]:
            project = tmp_path / name
            project.mkdir()
            (project / "pyproject.toml").write_text(f"[project]\nname = '{name}'\n")
            (project / "uv.lock").write_text("# uv lockfile\n")

        modules = discover_python_modules(tmp_path, recursive=True)

        names = [m.name for m in modules]
        assert names == ["a", "m", "z"]


class TestIsLegacyPythonProject:
    """Tests for is_legacy_python_project function."""

    def test_requirements_only_is_legacy(self, tmp_path):
        """Test that requirements.txt without uv.lock is legacy."""
        project = tmp_path / "legacy"
        project.mkdir()
        (project / "requirements.txt").write_text("requests>=2.0\n")

        assert is_legacy_python_project(project) is True

    def test_setup_py_only_is_legacy(self, tmp_path):
        """Test that setup.py without pyproject.toml is legacy."""
        project = tmp_path / "legacy"
        project.mkdir()
        (project / "setup.py").write_text("from setuptools import setup\nsetup()\n")

        assert is_legacy_python_project(project) is True

    def test_modern_project_not_legacy(self, tmp_path, python_project):
        """Test that pyproject.toml + uv.lock is not legacy."""
        assert is_legacy_python_project(python_project) is False

    def test_go_project_not_legacy(self, tmp_path, go_project):
        """Test that Go projects are not flagged as legacy Python."""
        assert is_legacy_python_project(go_project) is False

    def test_empty_dir_not_legacy(self, tmp_path):
        """Test that empty directory is not legacy."""
        assert is_legacy_python_project(tmp_path) is False

    def test_pyproject_without_uvlock_not_legacy(self, tmp_path):
        """Test pyproject.toml without uv.lock (might be poetry/pip-tools)."""
        project = tmp_path / "poetry"
        project.mkdir()
        (project / "pyproject.toml").write_text("[project]\nname = 'test'\n")
        # Has pyproject.toml but no uv.lock - not legacy, just not uv-based
        # This is NOT a legacy project, it's just not a uv project
        # We should skip it but not call it legacy
        assert is_legacy_python_project(project) is False


class TestDiscoverAllModules:
    """Tests for discover_all_modules function."""

    def test_finds_go_and_python(self, mixed_monorepo):
        """Test finding both Go and Python modules."""
        result = discover_all_modules(mixed_monorepo, recursive=True)

        assert "go" in result
        assert "python" in result
        assert "legacy" in result

        # Go modules: go-service, lib/go-lib
        assert len(result["go"]) == 2

        # Python modules: python-api, python-worker
        assert len(result["python"]) == 2

        # Legacy: legacy-script
        assert len(result["legacy"]) == 1

    def test_empty_categories_when_none_found(self, tmp_path):
        """Test that empty lists are returned when no modules found."""
        result = discover_all_modules(tmp_path, recursive=True)

        assert result["go"] == []
        assert result["python"] == []
        assert result["legacy"] == []

    def test_go_only_monorepo(self, tmp_path):
        """Test monorepo with only Go modules."""
        go1 = tmp_path / "service1"
        go1.mkdir()
        (go1 / "go.mod").write_text("module service1\ngo 1.23\n")

        go2 = tmp_path / "service2"
        go2.mkdir()
        (go2 / "go.mod").write_text("module service2\ngo 1.23\n")

        result = discover_all_modules(tmp_path, recursive=True)

        assert len(result["go"]) == 2
        assert len(result["python"]) == 0
        assert len(result["legacy"]) == 0

    def test_python_only_monorepo(self, tmp_path):
        """Test monorepo with only Python modules."""
        py1 = tmp_path / "api"
        py1.mkdir()
        (py1 / "pyproject.toml").write_text("[project]\nname = 'api'\n")
        (py1 / "uv.lock").write_text("# uv lockfile\n")

        py2 = tmp_path / "worker"
        py2.mkdir()
        (py2 / "pyproject.toml").write_text("[project]\nname = 'worker'\n")
        (py2 / "uv.lock").write_text("# uv lockfile\n")

        result = discover_all_modules(tmp_path, recursive=True)

        assert len(result["go"]) == 0
        assert len(result["python"]) == 2
        assert len(result["legacy"]) == 0

    def test_non_recursive_mode(self, mixed_monorepo):
        """Test non-recursive discovery."""
        result = discover_all_modules(mixed_monorepo, recursive=False)

        # Should only find direct children, not lib/go-lib
        go_names = [m.name for m in result["go"]]
        assert "go-service" in go_names
        assert "go-lib" not in go_names

        # Python direct children
        py_names = [m.name for m in result["python"]]
        assert "python-api" in py_names
        assert "python-worker" in py_names
