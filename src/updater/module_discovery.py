"""Go module discovery and sorting."""

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
