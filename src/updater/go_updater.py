"""Go dependency updater."""

import re
import subprocess
from collections.abc import Callable, Iterable
from pathlib import Path

from . import config
from .log_manager import log_message, run_command

# A Go commit pseudo-version ends in a 14-digit timestamp and 12 lowercase hex
# characters: v0.0.0-20260101120000-abcdef123456, v1.2.3-0.20260101120000-abcdef123456,
# v1.2.3-pre.0.20260101120000-abcdef123456.
_PSEUDO_VERSION_RE = re.compile(r"^\d+\.\d+\.\d+-.*\d{14}-[0-9a-f]{12}$")

# A `go list -m -u` line for a module with an available upgrade:
# `<path> <current> [<candidate>]`.
_UPDATE_LINE_RE = re.compile(r"^(\S+)\s+(\S+)\s+\[([^\]]+)\]")


def _strip_version(version: str) -> str:
    """Strip a leading `v` and any `+build` suffix from a version string."""
    core = version[1:] if version.startswith("v") else version
    return core.split("+", 1)[0]


def _is_prerelease(version: str) -> bool:
    """Return True when a version carries a pre-release suffix.

    The rule is the plain `"-" in core` check: strip the leading `v` and any
    `+build` suffix, then look for a hyphen. Go writes every pre-release,
    release candidate and pseudo-version that way.

    Args:
        version: A module version such as `v0.38.0-beta.0` or `v0.37.2`

    Returns:
        True for `v0.38.0-beta.0`, `v1.0.0-rc.1`, `v2.0.0-alpha` and
        `v0.0.0-20260101120000-abcdef123456`; False for `v0.37.2`, `v1.14.33`,
        `v1.2.3+build.7` and `1.2.3`
    """
    return "-" in _strip_version(version)


def _is_pseudo_version(version: str) -> bool:
    """Return True when a version is a Go commit pseudo-version.

    A pseudo-version is a deliberate commit pin, not an upgrade accident, so
    callers leave it alone rather than correcting it to a release.

    Args:
        version: A module version such as `v0.0.0-20260101120000-abcdef123456`

    Returns:
        True for the three pseudo-version forms Go emits, False otherwise
    """
    return bool(_PSEUDO_VERSION_RE.match(_strip_version(version)))


def _version_parts(version: str) -> tuple[int, int, int] | None:
    """Return the numeric `(major, minor, patch)` triple of a version.

    The pre-release suffix is stripped before parsing, so the major component of
    a pre-release such as `v0.38.0-beta.0` is available — the correction path
    needs it to stay inside the major version the module already requires.

    Args:
        version: A module version such as `v0.38.0-beta.0` or `v1.2.3+build.7`

    Returns:
        The three components as ints, or None when any is missing or non-numeric
    """
    core = _strip_version(version).split("-", 1)[0]
    parts = core.split(".")
    if len(parts) != 3 or not all(part.isdigit() for part in parts):
        return None
    return int(parts[0]), int(parts[1]), int(parts[2])


def _highest_stable(versions: Iterable[str], major: int | None = None) -> str | None:
    """Return the highest stable version, optionally restricted to one major version.

    A pre-release never wins over a stable version, even when it is numerically
    higher. Ordering is numeric per component, so `v0.10.0` outranks `v0.9.0`.
    Entries that do not parse as a numeric triple are ignored.

    Args:
        versions: Version strings, as printed by `go list -m -versions`
        major: When set, only versions of this major version are candidates

    Returns:
        The highest eligible stable version, or None when no eligible stable
        release exists — callers must treat None as "leave it alone"
    """
    best: str | None = None
    best_key: tuple[int, int, int] | None = None
    for version in versions:
        if _is_prerelease(version):
            continue
        parts = _version_parts(version)
        if parts is None:
            continue
        if major is not None and parts[0] != major:
            continue
        if best_key is None or parts > best_key:
            best = version
            best_key = parts
    return best


def _parse_update_candidate(output: str) -> tuple[str, str] | None:
    """Return `(current_version, candidate_version)` from `go list -m -u` output.

    Args:
        output: The stdout of `go list -mod=mod -m -u <module>`

    Returns:
        The current and bracketed candidate versions, or None when the line does
        not carry an upgrade bracket
    """
    match = _UPDATE_LINE_RE.search(output)
    if match is None:
        return None
    tokens = match.group(3).split()
    if not tokens:
        return None
    return match.group(2), tokens[0]


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
                parsed = _parse_update_candidate(check_result.stdout)
                if parsed is None:
                    log_func(
                        f"  → Skipping {module}: could not read the candidate version",
                        to_console=True,
                    )
                    continue
                current, candidate = parsed

                if _is_prerelease(candidate):
                    parts = _version_parts(current)
                    major = parts[0] if parts else None
                    versions_result = run_command(
                        f"go list -mod=mod -m -versions {module}",
                        cwd=module_path,
                        capture_output=True,
                        quiet=True,
                        log_func=log_func,
                    )
                    stable = _highest_stable(versions_result.stdout.split(), major=major)
                    if stable is None:
                        log_func(
                            f"  → Skipping {module}: {candidate} is a pre-release and no stable "
                            f"release of major {major} exists; leaving it",
                            to_console=True,
                        )
                        continue
                    log_func(
                        f"  → Skipping {module}: {candidate} is a pre-release; "
                        f"selecting highest stable {stable}",
                        to_console=True,
                    )
                    run_command(
                        f"go get {module}@{stable}",
                        cwd=module_path,
                        quiet=True,
                        log_func=log_func,
                    )
                else:
                    log_func(f"  → Updating {module}", to_console=config.VERBOSE_MODE)
                    run_command(
                        f"go get {module}@{candidate}",
                        cwd=module_path,
                        quiet=True,
                        log_func=log_func,
                    )
                updates_made = True
                any_updates_made = True

        if not updates_made:
            log_func("✓ No more updates available", to_console=config.VERBOSE_MODE)
            break

    corrected = downgrade_prerelease_requirements(module_path, log_func=log_func)
    any_updates_made = any_updates_made or corrected

    if not any_updates_made:
        log_func("\n✓ No dependency updates needed", to_console=True)
        return False

    # Run go mod tidy
    log_func("\n→ Running go mod tidy", to_console=config.VERBOSE_MODE)
    run_command("go mod tidy", cwd=module_path, quiet=True, log_func=log_func)

    log_func("\n✓ Go dependencies updated successfully", to_console=True)
    return True


def downgrade_prerelease_requirements(
    module_path: Path, log_func: Callable[..., None] = log_message
) -> bool:
    """Move every direct module off a pre-release requirement onto its highest stable release.

    `update_go_dependencies` only reacts to an upgrade bracket, so a module whose
    go.mod already requires a pre-release prints no bracket and would survive
    every sweep untouched. This audit reads the direct requirements and corrects
    that, staying inside the major version the module already requires. A commit
    pseudo-version is a deliberate pin and is left alone. Every skip is logged,
    so a pre-release that survives the sweep is always visible in the output.

    Args:
        module_path: Path to the Go module
        log_func: Logging function to use

    Returns:
        True if at least one module was corrected, False otherwise
    """
    result = run_command(
        "go list -mod=mod -m -f '{{if not (or .Main .Indirect)}}{{.Path}}@{{.Version}}{{end}}' all",
        cwd=module_path,
        capture_output=True,
        quiet=True,
        log_func=log_func,
    )

    corrected = False
    for line in result.stdout.splitlines():
        entry = line.strip()
        if not entry or "@" not in entry:
            continue
        path, version = entry.rsplit("@", 1)
        if not _is_prerelease(version):
            continue

        if _is_pseudo_version(version):
            log_func(
                f"  → {path} {version} is a commit pseudo-version; leaving it",
                to_console=True,
            )
            continue

        parts = _version_parts(version)
        if parts is None:
            log_func(
                f"  → {path} {version} is a pre-release and its version cannot be parsed; leaving it",
                to_console=True,
            )
            continue
        major = parts[0]

        versions_result = run_command(
            f"go list -mod=mod -m -versions {path}",
            cwd=module_path,
            capture_output=True,
            quiet=True,
            log_func=log_func,
        )
        stable = _highest_stable(versions_result.stdout.split(), major=major)

        if stable is None or stable == version:
            log_func(
                f"  → {path} {version} is a pre-release and no stable release of major "
                f"{major} exists; leaving it",
                to_console=True,
            )
            continue

        log_func(
            f"  → {path} {version} is a pre-release; selecting highest stable {stable}",
            to_console=True,
        )
        run_command(
            f"go get {path}@{stable}",
            cwd=module_path,
            quiet=True,
            log_func=log_func,
        )
        corrected = True

    return corrected


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
