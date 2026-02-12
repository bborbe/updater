"""Module discovery for Go and Python projects."""

from pathlib import Path


def _module_sort_key(module_path: Path, parent_path: Path) -> tuple:
    """Generate sort key for module to ensure lib/ packages are processed first.

    Priority order (packages before services that depend on them):
    1. lib/** (root-level shared packages - dependencies)
    2. other root-level modules (services using root packages)
    3. {dir}/lib/** (shared packages in each subdirectory)
    4. {dir}/** (services in that subdirectory using those packages)

    Args:
        module_path: Full path to module
        parent_path: Parent directory being searched

    Returns:
        Tuple for sorting (priority, path_parts...)
    """
    # Get relative path from parent
    try:
        rel_path = module_path.relative_to(parent_path)
    except ValueError:
        # If relative_to fails, just use the path as-is
        rel_path = module_path

    parts = rel_path.parts

    # Single-level modules (direct children)
    if len(parts) == 1:
        # lib/* modules have highest priority
        if parts[0] == "lib":
            return (0, parts[0])
        # Other direct children
        else:
            return (1, parts[0])

    # Multi-level modules (in subdirectories)
    # parts[0] is the top-level directory, parts[1] might be "lib"
    if len(parts) >= 2:
        top_dir = parts[0]

        # If this is lib/ at root level: lib/alert, lib/core
        if top_dir == "lib":
            return (0, top_dir, *parts[1:])

        # If second part is "lib": hubspot/lib/something
        elif parts[1] == "lib":
            return (2, top_dir, 0, *parts[1:])

        # Other modules in subdirectory: hubspot/service1
        else:
            return (2, top_dir, 1, *parts[1:])

    # Fallback
    return (999, *parts)


def discover_go_modules(parent_path: Path, recursive: bool = False) -> list[Path]:
    """Discover all Go modules (directories with go.mod) in subdirectories.

    Args:
        parent_path: Parent directory to search in
        recursive: If True, search recursively in all subdirectories

    Returns:
        List of paths to Go modules, sorted with lib/ folders first
    """
    modules = []
    parent = Path(parent_path)

    if recursive:
        # Recursive search - find all go.mod files
        for item in parent.rglob("go.mod"):
            if item.is_file():
                module_dir = item.parent
                # Skip vendor directories
                if "vendor" not in module_dir.parts:
                    modules.append(module_dir)
    else:
        # Non-recursive - only direct children (original behavior)
        for item in sorted(parent.iterdir()):
            if item.is_dir() and (item / "go.mod").exists():
                modules.append(item)

    # Sort with custom priority (lib/ first at each level)
    if recursive:
        modules.sort(key=lambda m: _module_sort_key(m, parent))
    else:
        # Keep original alphabetical sorting for non-recursive
        modules.sort()

    return modules


def discover_python_modules(parent_path: Path, recursive: bool = False) -> list[Path]:
    """Discover Python modules (directories with pyproject.toml + uv.lock).

    Only modern uv-based projects are supported. Legacy projects with only
    requirements.txt are skipped (use is_legacy_python_project to detect them).

    Args:
        parent_path: Parent directory to search in
        recursive: If True, search recursively in all subdirectories

    Returns:
        List of paths to Python modules, sorted alphabetically
    """
    modules = []
    parent = Path(parent_path)

    if recursive:
        # Recursive search - find all pyproject.toml files
        for item in parent.rglob("pyproject.toml"):
            if item.is_file():
                module_dir = item.parent
                # Skip .venv directories
                if ".venv" in module_dir.parts:
                    continue
                # Require uv.lock for modern project detection
                if (module_dir / "uv.lock").exists():
                    modules.append(module_dir)
    else:
        # Non-recursive - only direct children
        for item in sorted(parent.iterdir()):
            if item.is_dir():
                if (item / "pyproject.toml").exists() and (item / "uv.lock").exists():
                    modules.append(item)

    # Sort alphabetically
    modules.sort()

    return modules


def is_legacy_python_project(path: Path) -> bool:
    """Check if a directory is a legacy Python project.

    Legacy projects have:
    - requirements.txt without uv.lock, OR
    - setup.py without pyproject.toml

    Modern projects (pyproject.toml + uv.lock) are NOT legacy.
    Non-Python projects (Go, etc.) are NOT legacy.

    Args:
        path: Directory to check

    Returns:
        True if legacy Python project, False otherwise
    """
    path = Path(path)

    has_requirements = (path / "requirements.txt").exists()
    has_setup_py = (path / "setup.py").exists()
    has_pyproject = (path / "pyproject.toml").exists()
    has_uv_lock = (path / "uv.lock").exists()

    # Modern uv project - not legacy
    if has_pyproject and has_uv_lock:
        return False

    # Has requirements.txt without modern setup
    if has_requirements and not has_uv_lock:
        return True

    # Has setup.py without pyproject.toml
    if has_setup_py and not has_pyproject:
        return True

    return False


def discover_legacy_python_projects(parent_path: Path, recursive: bool = False) -> list[Path]:
    """Discover legacy Python projects (requirements.txt without uv.lock).

    Args:
        parent_path: Parent directory to search in
        recursive: If True, search recursively in all subdirectories

    Returns:
        List of paths to legacy Python projects
    """
    projects = []
    parent = Path(parent_path)

    if recursive:
        # Find requirements.txt files
        for item in parent.rglob("requirements.txt"):
            if item.is_file():
                project_dir = item.parent
                # Skip .venv directories
                if ".venv" in project_dir.parts:
                    continue
                if is_legacy_python_project(project_dir):
                    projects.append(project_dir)

        # Also find setup.py without pyproject.toml
        for item in parent.rglob("setup.py"):
            if item.is_file():
                project_dir = item.parent
                if ".venv" in project_dir.parts:
                    continue
                if is_legacy_python_project(project_dir) and project_dir not in projects:
                    projects.append(project_dir)
    else:
        for item in sorted(parent.iterdir()):
            if item.is_dir() and is_legacy_python_project(item):
                projects.append(item)

    projects.sort()
    return projects


def discover_docker_projects(parent_path: Path, recursive: bool = False) -> list[Path]:
    """Discover standalone Docker projects (Dockerfile without go.mod/pyproject.toml).

    Args:
        parent_path: Parent directory to search in
        recursive: If True, search recursively in all subdirectories

    Returns:
        List of paths to directories with standalone Dockerfiles
    """
    projects = []
    parent = Path(parent_path)

    if recursive:
        # Find all Dockerfiles
        for item in parent.rglob("Dockerfile"):
            if item.is_file():
                project_dir = item.parent
                # Skip .venv, vendor, and node_modules directories
                if any(d in project_dir.parts for d in (".venv", "vendor", "node_modules")):
                    continue
                # Only include if NOT a Go or Python module
                has_go_mod = (project_dir / "go.mod").exists()
                has_python = (project_dir / "pyproject.toml").exists()
                if not has_go_mod and not has_python:
                    projects.append(project_dir)
    else:
        for item in sorted(parent.iterdir()):
            if item.is_dir():
                dockerfile = item / "Dockerfile"
                if dockerfile.exists():
                    # Only include if NOT a Go or Python module
                    has_go_mod = (item / "go.mod").exists()
                    has_python = (item / "pyproject.toml").exists()
                    if not has_go_mod and not has_python:
                        projects.append(item)

    # Remove duplicates and sort
    projects = list(dict.fromkeys(projects))
    projects.sort()
    return projects


def discover_all_modules(parent_path: Path, recursive: bool = False) -> dict[str, list[Path]]:
    """Discover all modules (Go, Python, and Docker) in a directory.

    Args:
        parent_path: Parent directory to search in
        recursive: If True, search recursively in all subdirectories

    Returns:
        Dictionary with keys 'go', 'python', 'docker', 'legacy' mapping to lists of paths
    """
    return {
        "go": discover_go_modules(parent_path, recursive=recursive),
        "python": discover_python_modules(parent_path, recursive=recursive),
        "docker": discover_docker_projects(parent_path, recursive=recursive),
        "legacy": discover_legacy_python_projects(parent_path, recursive=recursive),
    }
