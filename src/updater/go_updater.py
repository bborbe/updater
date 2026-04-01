"""Go dependency updater."""

import re
import subprocess
from collections.abc import Callable
from pathlib import Path

from . import config
from .log_manager import log_message, run_command


def update_go_dependencies(module_path: Path, log_func: Callable[..., None] = log_message) -> bool:
    """Iteratively update Go dependencies until stable.

    Args:
        module_path: Path to Go module
        log_func: Logging function to use

    Returns:
        True if updates were made, False otherwise
    """
    log_func("\n=== Phase 1c: Update Go Dependencies ===", to_console=True)

    max_iterations = config.GO_MAX_ITERATIONS
    iteration = 0
    any_updates_made = False

    while iteration < max_iterations:
        iteration += 1
        log_func(
            f"\n→ Iteration {iteration}/{max_iterations}",
            to_console=config.VERBOSE_MODE,
        )

        # Check for available updates
        result = run_command(
            "go list -mod=mod -m -u -f '{{if not (or .Main .Indirect)}}{{.Path}}{{end}}' all",
            cwd=module_path,
            capture_output=True,
            quiet=True,
            log_func=log_func,
        )

        outdated_modules = [line for line in result.stdout.strip().split("\n") if line]

        if not outdated_modules:
            log_func("✓ All dependencies are up to date", to_console=config.VERBOSE_MODE)
            break

        log_func(
            f"  Found {len(outdated_modules)} modules to update",
            to_console=config.VERBOSE_MODE,
        )

        # Update modules that have updates available
        updates_made = False
        for module in outdated_modules:
            # Check if update is available
            check_result = run_command(
                f"go list -mod=mod -m -u {module}",
                cwd=module_path,
                capture_output=True,
                quiet=True,
                log_func=log_func,
            )

            if "[" in check_result.stdout:  # Has update available
                log_func(f"  → Updating {module}", to_console=config.VERBOSE_MODE)
                run_command(
                    f"go get {module}@latest",
                    cwd=module_path,
                    quiet=True,
                    log_func=log_func,
                )
                updates_made = True
                any_updates_made = True

        if not updates_made:
            log_func("✓ No more updates available", to_console=config.VERBOSE_MODE)
            break

    if not any_updates_made:
        log_func("\n✓ No dependency updates needed", to_console=True)
        return False

    # Run go mod tidy
    log_func("\n→ Running go mod tidy", to_console=config.VERBOSE_MODE)
    run_command("go mod tidy", cwd=module_path, quiet=True, log_func=log_func)

    log_func("\n✓ Go dependencies updated successfully", to_console=True)
    return True


def _has_makefile_target(module_path: Path, target: str) -> bool:
    """Check if a Makefile target exists."""
    makefile = module_path / "Makefile"
    if not makefile.exists():
        return False
    content = makefile.read_text()
    return bool(re.search(rf"^{re.escape(target)}\s*:", content, re.MULTILINE))


def _parse_osv_go_packages(output: str) -> list[str]:
    """Parse OSV scanner table output and return Go package names."""
    packages = []
    for line in output.split("\n"):
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.split("|")]
        # Table rows have: empty | OSV URL | CVSS | ECOSYSTEM | PACKAGE | VERSION | FIXED | SOURCE
        if len(cells) < 8:
            continue
        ecosystem = cells[3]
        package = cells[4]
        if ecosystem == "Go" and package and package != "PACKAGE":
            packages.append(package)
    return packages


def fix_osv_vulnerabilities(module_path: Path, log_func: Callable[..., None] = log_message) -> bool:
    """Run OSV scanner and fix Go vulnerabilities if found.

    Returns True if vulnerabilities were fixed.
    """
    if not _has_makefile_target(module_path, "osv-scanner"):
        return False

    log_func("\n=== Phase 1d: Fix OSV Vulnerabilities ===", to_console=True)

    result = subprocess.run(
        "make osv-scanner",
        shell=True,
        cwd=module_path,
        capture_output=True,
        text=True,
    )

    if result.returncode == 0:
        log_func("✓ No vulnerabilities found", to_console=True)
        return False

    # Parse vulnerable Go packages from output
    combined_output = (result.stdout or "") + "\n" + (result.stderr or "")
    packages = _parse_osv_go_packages(combined_output)

    if not packages:
        log_func("✓ No fixable Go vulnerabilities found", to_console=True)
        return False

    log_func(f"→ Found {len(packages)} vulnerable Go package(s)", to_console=True)

    for pkg in packages:
        log_func(f"  → Updating {pkg}", to_console=True)
        run_command(f"go get -u {pkg}", cwd=module_path, quiet=True, log_func=log_func)

    run_command("go mod tidy", cwd=module_path, quiet=True, log_func=log_func)

    log_func("✓ OSV vulnerabilities fixed", to_console=True)
    return True


def clean_indirect_deps(module_path: Path, log_func: Callable[..., None] = log_message) -> bool:
    """Remove all indirect dependencies from go.mod and re-add via go mod tidy.

    Parses indirect deps using go list, drops each via go mod edit -droprequire,
    then runs go mod tidy to re-add only the actually needed ones.

    Args:
        module_path: Path to Go module
        log_func: Logging function to use

    Returns:
        True if any indirect deps were removed, False otherwise
    """
    gomod_path = module_path / "go.mod"
    if not gomod_path.exists():
        log_func(f"  ⚠ No go.mod found at {gomod_path}", to_console=True)
        return False

    log_func("\n=== Phase 1d: Clean Indirect Dependencies ===", to_console=True)

    # Parse indirect deps using go list
    result = run_command(
        "go list -m -f '{{if .Indirect}}{{.Path}}@{{.Version}}{{end}}' all",
        cwd=module_path,
        capture_output=True,
        quiet=True,
        log_func=log_func,
    )

    indirect_deps = [line for line in result.stdout.strip().split("\n") if line]

    if not indirect_deps:
        log_func("✓ No indirect dependencies to clean", to_console=True)
        return False

    log_func(f"  → Found {len(indirect_deps)} indirect dep(s) to remove", to_console=True)

    # Drop each indirect dep via go mod edit
    for dep in indirect_deps:
        module_name = dep.split("@")[0]
        run_command(
            f"go mod edit -droprequire {module_name}",
            cwd=module_path,
            quiet=True,
            log_func=log_func,
        )

    # Re-add actually needed indirect deps via go mod tidy
    run_command("go mod tidy", cwd=module_path, quiet=True, log_func=log_func)

    log_func(f"✓ Removed {len(indirect_deps)} indirect dep(s) and ran go mod tidy", to_console=True)
    return True


def run_precommit(module_path: Path, log_func: Callable[..., None] = log_message) -> None:
    """Run make precommit.

    Args:
        module_path: Path to Go module
        log_func: Logging function to use
    """
    log_func("\n=== Phase 2: Run Precommit ===", to_console=True)

    log_func("→ Running make precommit", to_console=config.VERBOSE_MODE)
    run_command("make precommit", cwd=module_path, quiet=True, log_func=log_func)

    log_func("✓ Precommit completed successfully", to_console=True)
