"""Go module excludes and replaces management."""

from collections.abc import Callable
from pathlib import Path

from .log_manager import log_message, run_command

# Standard exclusions for problematic versions
# NOTE: Excludes break `go install`, so keep this list empty unless absolutely necessary.
# Use OBSOLETE_EXCLUDES_PREFIXES to actively remove old excludes from projects.
#
# cloud.google.com/go v0.26.0: the pre-split monorepo version still bundles the
# cloud.google.com/go/compute/metadata package, which now ships as its own
# module. When both land in the build graph (e.g. via golang.org/x/oauth2/google),
# `go mod tidy` fails with "ambiguous import". Excluding the stale version forces
# MVS to drop it so only the split-out module provides the package.
STANDARD_EXCLUDES: list[str] = [
    "cloud.google.com/go@v0.26.0",
]

# Standard replacements
# Format: (old_module, "new_module version")
# Note: go.mod stores as "new_module version" (space-separated)
# NOTE: Replaces break `go install`, so keep this list empty unless absolutely necessary.
# All previous entries (cellbuf, go-header, diskfs, ginkgolinter/types) were workarounds
# for tools.go-induced transitive dep conflicts. After migrating tools.go → tools.env +
# Makefile @version pattern, those replaces are no longer needed and actively hurt
# because they prevent `go run pkg@version` from resolving cleanly.
STANDARD_REPLACES: list[tuple[str, str]] = []

# Exclude prefixes that should be REMOVED from projects (obsolete workarounds)
# These broke `go install` for all modules. The updater actively removes them.
OBSOLETE_EXCLUDES_PREFIXES = [
    "github.com/go-logr/glogr@",
    "github.com/go-logr/logr@",
    "github.com/golangci/golangci-lint@",  # v1 excludes break go mod tidy after v2 migration
    "go.yaml.in/yaml/v3@",
    "golang.org/x/tools@",
    "k8s.io/api@",
    "k8s.io/apiextensions-apiserver@",
    "k8s.io/apimachinery@",
    "k8s.io/client-go@",
    "k8s.io/code-generator@",
    "sigs.k8s.io/structured-merge-diff/v6@",
]

# Replace module names whose directives should be REMOVED from projects (obsolete workarounds)
OBSOLETE_REPLACES = [
    "github.com/anthropics/anthropic-sdk-go",
    "k8s.io/kube-openapi",
]

# Replace module names that should be removed ONLY when the project has migrated
# away from tools.go (i.e., tools.go does not exist). These were workarounds for
# tools.go-induced transitive dep conflicts and are no longer needed once the
# project moves to the tools.env + Makefile @version pattern.
TOOLS_GO_OBSOLETE_REPLACES = [
    "github.com/charmbracelet/x/cellbuf",
    "github.com/denis-tingaikin/go-header",
    "github.com/diskfs/go-diskfs",
    "github.com/nunnatsa/ginkgolinter/types",
]


def read_gomod_excludes_and_replaces(
    module_path: Path,
) -> tuple[set[str], dict[str, str]]:
    """Read existing excludes and replaces from go.mod.

    Args:
        module_path: Path to module

    Returns:
        Tuple of (excludes_set, replaces_dict)
        excludes_set: Set of "module@version" strings
        replaces_dict: Dict of old_module -> new_module@version
    """
    gomod = module_path / "go.mod"
    if not gomod.exists():
        return set(), {}

    content = gomod.read_text()
    lines = content.split("\n")

    excludes = set()
    replaces = {}

    in_exclude_block = False
    in_replace_block = False

    for line in lines:
        stripped = line.strip()

        # Track blocks
        if stripped.startswith("exclude ("):
            in_exclude_block = True
            continue
        elif stripped.startswith("replace ("):
            in_replace_block = True
            continue
        elif stripped == ")":
            in_exclude_block = False
            in_replace_block = False
            continue

        # Parse exclude lines
        if in_exclude_block:
            # Format: "module version" or just "module@version"
            parts = stripped.split()
            if len(parts) >= 2:
                module = parts[0]
                version = parts[1]
                excludes.add(f"{module}@{version}")
            elif "@" in stripped:
                excludes.add(stripped)
        elif stripped.startswith("exclude "):
            # Single line exclude
            rest = stripped[8:].strip()  # Remove "exclude "
            parts = rest.split()
            if len(parts) >= 2:
                module = parts[0]
                version = parts[1]
                excludes.add(f"{module}@{version}")
            elif "@" in rest:
                excludes.add(rest)

        # Parse replace lines
        if in_replace_block:
            # Format: "old => new@version" or "old@version => new@version"
            if "=>" in stripped:
                parts = stripped.split("=>")
                if len(parts) == 2:
                    old = parts[0].strip().split()[0]  # Get just module name, ignore version
                    new = parts[1].strip()
                    replaces[old] = new
        elif stripped.startswith("replace "):
            # Single line replace
            rest = stripped[8:].strip()  # Remove "replace "
            if "=>" in rest:
                parts = rest.split("=>")
                if len(parts) == 2:
                    old = parts[0].strip().split()[0]  # Get just module name, ignore version
                    new = parts[1].strip()
                    replaces[old] = new

    return excludes, replaces


def apply_gomod_excludes_and_replaces(
    module_path: Path, log_func: Callable[..., None] = log_message
) -> bool:
    """Apply standard excludes and replaces to go.mod if not already present.

    Args:
        module_path: Path to module
        log_func: Logging function

    Returns:
        True if any changes were made, False otherwise
    """
    gomod = module_path / "go.mod"
    if not gomod.exists():
        log_func("  ⚠ No go.mod found, skipping excludes/replaces", to_console=True)
        return False

    # Read current state
    existing_excludes, existing_replaces = read_gomod_excludes_and_replaces(module_path)

    changes_made = False

    # Add missing excludes
    for exclude in STANDARD_EXCLUDES:
        if exclude not in existing_excludes:
            log_func(f"  → Adding exclude: {exclude}", to_console=True)
            run_command(
                f"go mod edit -exclude {exclude}",
                cwd=module_path,
                quiet=True,
                log_func=log_func,
            )
            changes_made = True

    # Add missing replaces
    for old_module, new_module_stored in STANDARD_REPLACES:
        # Check if replacement already exists and matches
        if old_module in existing_replaces:
            if existing_replaces[old_module] == new_module_stored:
                continue  # Already correct
            # Different version, update it
            log_func(
                f"  → Updating replace: {old_module} => {new_module_stored}",
                to_console=True,
            )
        else:
            log_func(
                f"  → Adding replace: {old_module} => {new_module_stored}",
                to_console=True,
            )

        # Convert space to @ for go mod edit command
        # go.mod stores as "module version", but go mod edit needs "module@version"
        new_module_cmd = new_module_stored.replace(" ", "@")

        run_command(
            f"go mod edit -replace {old_module}={new_module_cmd}",
            cwd=module_path,
            quiet=True,
            log_func=log_func,
        )
        changes_made = True

    # Remove obsolete excludes
    for exclude in list(existing_excludes):
        if any(exclude.startswith(prefix) for prefix in OBSOLETE_EXCLUDES_PREFIXES):
            log_func(f"  → Removing obsolete exclude: {exclude}", to_console=True)
            run_command(
                f"go mod edit -dropexclude {exclude}",
                cwd=module_path,
                quiet=True,
                log_func=log_func,
            )
            changes_made = True

    # Remove obsolete replaces
    for old_module in list(existing_replaces):
        if old_module in OBSOLETE_REPLACES:
            log_func(f"  → Removing obsolete replace: {old_module}", to_console=True)
            run_command(
                f"go mod edit -dropreplace {old_module}",
                cwd=module_path,
                quiet=True,
                log_func=log_func,
            )
            changes_made = True

    # Remove tools.go-related replaces ONLY if the project has migrated away from
    # tools.go (i.e., tools.go does not exist). For un-migrated projects, these
    # replaces are still needed to resolve tools.go-induced transitive conflicts.
    tools_go_exists = (module_path / "tools.go").exists()
    if not tools_go_exists:
        for old_module in list(existing_replaces):
            if old_module in TOOLS_GO_OBSOLETE_REPLACES:
                log_func(
                    f"  → Removing tools.go-obsolete replace: {old_module}",
                    to_console=True,
                )
                run_command(
                    f"go mod edit -dropreplace {old_module}",
                    cwd=module_path,
                    quiet=True,
                    log_func=log_func,
                )
                changes_made = True

    if not changes_made:
        log_func("  ✓ All excludes and replaces up to date", to_console=True)
    else:
        run_command("go mod download", cwd=module_path, quiet=True, log_func=log_func)

    return changes_made
