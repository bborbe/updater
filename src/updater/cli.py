"""CLI orchestration and workflow."""

import argparse
import asyncio
import traceback
from datetime import datetime
from pathlib import Path

from . import config
from .changelog import update_changelog_with_suggestions
from .claude_analyzer import analyze_changes_with_claude, verify_claude_auth
from .docker_updater import update_dockerfile_images
from .file_utils import condense_file_list
from .git_operations import (
    check_git_status,
    ensure_changelog_tag,
    ensure_gitignore_entry,
    find_git_repo,
    git_commit,
    git_tag_from_changelog,
    update_git_branch,
)
from .go_updater import run_precommit as run_go_precommit
from .go_updater import update_go_dependencies
from .gomod_excludes import apply_gomod_excludes_and_replaces
from .log_manager import (
    cleanup_old_logs,
    close_module_logging,
    log_message,
    setup_module_logging,
)
from .module_discovery import (
    discover_all_modules,
    discover_go_modules,
    discover_legacy_python_projects,
    discover_python_modules,
)
from .prompts import prompt_skip_or_retry, prompt_yes_no
from .python_updater import run_precommit as run_python_precommit
from .python_updater import update_python_dependencies
from .python_version_updater import update_python_versions
from .sound import play_completion_sound, play_error_sound
from .version_updater import update_versions


def print_commit_summary(
    module_name: str,
    analysis: dict,
    new_version: str | None = None,
    note: str | None = None,
) -> None:
    """Print commit summary to console.

    Args:
        module_name: Name of the module being committed
        analysis: Analysis dict with commit_message, version_bump, changelog
        new_version: Optional version string (for versioned commits)
        note: Optional note to display (e.g., "No CHANGELOG.md found")
    """
    print("\n" + "=" * 60)
    print(f"READY TO COMMIT: {module_name}")
    print("=" * 60)
    if new_version:
        print(f"Version:        {new_version} ({analysis['version_bump']} bump)")
    print(f"Commit message: {analysis['commit_message']}")
    if new_version:
        print(f"Git tag:        {new_version} (will be created)")
        print("\nChangelog entries:")
    else:
        print("\nChanges:")
    for bullet in analysis["changelog"]:
        print(f"  - {bullet.lstrip('- ')}")
    if note:
        print(f"\nNote: {note}")
    print("=" * 60)


async def process_single_go_module(module_path: Path) -> bool:
    """Process a single Go module.

    Creates a new Claude session for analyzing changes to ensure clean, isolated analysis.

    Args:
        module_path: Path to the module

    Returns:
        True if successful, False on error
    """
    log_file = None
    try:
        # Setup logging for this module
        log_file = setup_module_logging(module_path)

        log_message(f"\n{'=' * 70}", to_console=True)
        log_message(f"Module: {module_path.name}", to_console=True)
        log_message("=" * 70, to_console=True)
        if log_file and not config.VERBOSE_MODE:
            print(f"  Log: {log_file}")

        # Ensure .update-logs/ is in .gitignore
        ensure_gitignore_entry(module_path, log_func=log_message)

        # Find git repo first
        git_repo = find_git_repo(module_path)
        if not git_repo:
            log_message("✗ No git repository found", to_console=True)
            return False

        # Phase 1a: Update runtime versions (golang, alpine)
        version_updates = update_versions(module_path, log_func=log_message)

        # Phase 1b: Apply standard excludes and replaces
        log_message("\n=== Phase 1b: Apply Standard Excludes/Replaces ===", to_console=True)
        excludes_updates = apply_gomod_excludes_and_replaces(module_path, log_func=log_message)

        # Phase 1c: Update dependencies
        dep_updates = update_go_dependencies(module_path, log_func=log_message)

        updates_made = version_updates or excludes_updates or dep_updates

        # Phase 1d: Check if git shows any changes (from this run or previous runs)
        change_count, files = check_git_status(module_path)

        if change_count == 0 and not updates_made:
            log_message("\n✓ No updates needed - module is already up to date", to_console=True)
            return True

        if change_count == 0:
            log_message("\n✓ No changes detected after dependency update", to_console=True)
            return True

        if updates_made:
            log_message(
                f"\n→ {change_count} file(s) changed after dependency update",
                to_console=True,
            )
        else:
            log_message(
                f"\n→ Processing {change_count} uncommitted file(s) from previous run",
                to_console=True,
            )

        # Show condensed file list if 20 or fewer lines
        condensed_files = condense_file_list(files)
        if len(condensed_files) <= 20:
            for f in condensed_files:
                log_message(f"  {f}", to_console=True)

        # Phase 2: Run precommit (validate and auto-format)
        run_go_precommit(module_path, log_func=log_message)

        # Phase 2b: Check if changes remain after precommit
        change_count, files = check_git_status(module_path)
        if change_count == 0:
            log_message(
                "\n✓ No changes remain after precommit (auto-formatted/fixed)",
                to_console=True,
            )
            return True

        log_message(f"→ {change_count} file(s) changed after precommit", to_console=True)

        # Show condensed file list if 20 or fewer lines
        condensed_files = condense_file_list(files)
        if len(condensed_files) <= 20:
            for f in condensed_files:
                log_message(f"  {f}", to_console=True)

        # Phase 3: Analyze changes with Claude
        analysis = await analyze_changes_with_claude(module_path, log_func=log_message)

        # Check if version bump is needed
        if analysis["version_bump"] == "none":
            # No version bump needed - just commit without CHANGELOG/tag
            log_message(
                "\n→ No version bump needed (infrastructure changes only)",
                to_console=True,
            )

            print_commit_summary(
                module_path.name,
                analysis,
                note="No version bump or tag (infrastructure changes only)",
            )

            # Ask for confirmation if required
            if config.REQUIRE_CONFIRM:
                if not prompt_yes_no("\nProceed with commit (no tag)?", default_yes=True):
                    log_message("\n⚠ Skipped by user", to_console=True)
                    log_message("  Changes are staged but not committed", to_console=True)
                    return True

            git_commit(module_path, analysis["commit_message"], log_func=log_message)
            ensure_changelog_tag(module_path, log_func=log_message)
            log_message("\n✓ Commit completed successfully!", to_console=True)
            return True

        # Phase 4: Update CHANGELOG with Claude's suggestions
        changelog_path = module_path / "CHANGELOG.md"

        if not changelog_path.exists():
            # No CHANGELOG.md - commit without tag
            log_message("\n→ No CHANGELOG.md found, committing without tag", to_console=True)

            print_commit_summary(
                module_path.name,
                analysis,
                note="No CHANGELOG.md found, no version tag will be created",
            )

            # Ask for confirmation if required
            if config.REQUIRE_CONFIRM:
                if not prompt_yes_no("\nProceed with commit (no tag)?", default_yes=True):
                    log_message("\n⚠ Skipped by user", to_console=True)
                    log_message("  Changes are staged but not committed", to_console=True)
                    return True

            git_commit(module_path, analysis["commit_message"], log_func=log_message)
            log_message("\n✓ Commit completed successfully!", to_console=True)
            return True

        # CHANGELOG.md exists - update and create tag
        new_version = update_changelog_with_suggestions(module_path, analysis, log_func=log_message)

        # Show summary and ask for confirmation (always to console)
        print_commit_summary(module_path.name, analysis, new_version=new_version)

        # Ask for confirmation if required
        if config.REQUIRE_CONFIRM:
            if not prompt_yes_no("\nProceed with commit and tag?", default_yes=True):
                log_message("\n⚠ Skipped by user", to_console=True)
                log_message("  Changes are staged but not committed", to_console=True)
                return True

        git_commit(module_path, analysis["commit_message"], log_func=log_message)
        git_tag_from_changelog(module_path, log_func=log_message)
        log_message("\n✓ Update completed successfully!", to_console=True)
        return True

    except Exception as e:
        log_message(f"\n✗ Error processing {module_path}: {e}", to_console=True)
        if config.VERBOSE_MODE:
            traceback.print_exc()
        return False
    finally:
        # Close logging and cleanup old logs
        close_module_logging()
        cleanup_old_logs(module_path)


async def process_single_python_module(module_path: Path) -> bool:
    """Process a single Python module.

    Creates a new Claude session for analyzing changes to ensure clean, isolated analysis.

    Args:
        module_path: Path to the module

    Returns:
        True if successful, False on error
    """
    log_file = None
    try:
        # Setup logging for this module
        log_file = setup_module_logging(module_path)

        log_message(f"\n{'=' * 70}", to_console=True)
        log_message(f"Module: {module_path.name} (Python)", to_console=True)
        log_message("=" * 70, to_console=True)
        if log_file and not config.VERBOSE_MODE:
            print(f"  Log: {log_file}")

        # Ensure .update-logs/ is in .gitignore
        ensure_gitignore_entry(module_path, log_func=log_message)

        # Find git repo first
        git_repo = find_git_repo(module_path)
        if not git_repo:
            log_message("✗ No git repository found", to_console=True)
            return False

        # Phase 1a: Update Python versions
        version_updates = update_python_versions(module_path, log_func=log_message)

        # Phase 1b: Update dependencies
        dep_updates = update_python_dependencies(module_path, log_func=log_message)

        updates_made = version_updates or dep_updates

        # Check if git shows any changes
        change_count, files = check_git_status(module_path)

        if change_count == 0 and not updates_made:
            log_message("\n✓ No updates needed - module is already up to date", to_console=True)
            return True

        if change_count == 0:
            log_message("\n✓ No changes detected after dependency update", to_console=True)
            return True

        if updates_made:
            log_message(
                f"\n→ {change_count} file(s) changed after dependency update",
                to_console=True,
            )
        else:
            log_message(
                f"\n→ Processing {change_count} uncommitted file(s) from previous run",
                to_console=True,
            )

        # Show condensed file list if 20 or fewer lines
        condensed_files = condense_file_list(files)
        if len(condensed_files) <= 20:
            for f in condensed_files:
                log_message(f"  {f}", to_console=True)

        # Phase 2: Run precommit (validate and auto-format)
        run_python_precommit(module_path, log_func=log_message)

        # Phase 2b: Check if changes remain after precommit
        change_count, files = check_git_status(module_path)
        if change_count == 0:
            log_message(
                "\n✓ No changes remain after precommit (auto-formatted/fixed)",
                to_console=True,
            )
            return True

        log_message(f"→ {change_count} file(s) changed after precommit", to_console=True)

        # Show condensed file list if 20 or fewer lines
        condensed_files = condense_file_list(files)
        if len(condensed_files) <= 20:
            for f in condensed_files:
                log_message(f"  {f}", to_console=True)

        # Phase 3: Analyze changes with Claude
        analysis = await analyze_changes_with_claude(module_path, log_func=log_message)

        # Check if version bump is needed
        if analysis["version_bump"] == "none":
            log_message(
                "\n→ No version bump needed (infrastructure changes only)",
                to_console=True,
            )

            print_commit_summary(
                module_path.name,
                analysis,
                note="No version bump or tag (infrastructure changes only)",
            )

            if config.REQUIRE_CONFIRM:
                if not prompt_yes_no("\nProceed with commit (no tag)?", default_yes=True):
                    log_message("\n⚠ Skipped by user", to_console=True)
                    log_message("  Changes are staged but not committed", to_console=True)
                    return True

            git_commit(module_path, analysis["commit_message"], log_func=log_message)
            ensure_changelog_tag(module_path, log_func=log_message)
            log_message("\n✓ Commit completed successfully!", to_console=True)
            return True

        # Phase 4: Update CHANGELOG with Claude's suggestions
        changelog_path = module_path / "CHANGELOG.md"

        if not changelog_path.exists():
            log_message("\n→ No CHANGELOG.md found, committing without tag", to_console=True)

            print_commit_summary(
                module_path.name,
                analysis,
                note="No CHANGELOG.md found, no version tag will be created",
            )

            if config.REQUIRE_CONFIRM:
                if not prompt_yes_no("\nProceed with commit (no tag)?", default_yes=True):
                    log_message("\n⚠ Skipped by user", to_console=True)
                    log_message("  Changes are staged but not committed", to_console=True)
                    return True

            git_commit(module_path, analysis["commit_message"], log_func=log_message)
            log_message("\n✓ Commit completed successfully!", to_console=True)
            return True

        # CHANGELOG.md exists - update and create tag
        new_version = update_changelog_with_suggestions(module_path, analysis, log_func=log_message)

        print_commit_summary(module_path.name, analysis, new_version=new_version)

        if config.REQUIRE_CONFIRM:
            if not prompt_yes_no("\nProceed with commit and tag?", default_yes=True):
                log_message("\n⚠ Skipped by user", to_console=True)
                log_message("  Changes are staged but not committed", to_console=True)
                return True

        git_commit(module_path, analysis["commit_message"], log_func=log_message)
        git_tag_from_changelog(module_path, log_func=log_message)
        log_message("\n✓ Update completed successfully!", to_console=True)
        return True

    except Exception as e:
        log_message(f"\n✗ Error processing {module_path}: {e}", to_console=True)
        if config.VERBOSE_MODE:
            traceback.print_exc()
        return False
    finally:
        close_module_logging()
        cleanup_old_logs(module_path)


async def process_module_with_retry(
    module_path: Path, project_type: str = "go"
) -> tuple[bool, str]:
    """Process a single module with retry on failure.

    Args:
        module_path: Path to the module
        project_type: Type of project ("go" or "python")

    Returns:
        Tuple of (success: bool, status: str)
        status can be: 'success', 'skipped'
    """
    attempt = 1

    while True:
        if attempt > 1:
            print(f"\n=== Retrying {module_path} (attempt {attempt}) ===\n")

        if project_type == "python":
            success = await process_single_python_module(module_path)
        else:
            success = await process_single_go_module(module_path)

        if success:
            return True, "success"

        # Failed - prompt for skip or retry
        play_error_sound()
        print(f"\n✗ Module {module_path} failed")
        print("  → Fix the issues and retry, or skip this module")

        choice = prompt_skip_or_retry()

        if choice == "skip":
            print(f"⚠ Skipping {module_path}\n")
            return False, "skipped"

        # Retry - increment attempt counter
        attempt += 1


async def main_async() -> int:
    """Main async workflow with auto-detection of project types.

    Returns:
        Exit code (0 for success, 1 for error)
    """
    parser = argparse.ArgumentParser(
        description="Update dependencies for Go and Python projects (auto-detect)"
    )
    parser.add_argument(
        "modules",
        nargs="*",
        default=["."],
        help="Path(s) to module(s) or parent directories (default: current directory)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show full command output (default: quiet with logs in .update-logs/)",
    )
    parser.add_argument(
        "--model",
        choices=["sonnet", "opus", "haiku"],
        default="sonnet",
        help="Claude model to use (default: sonnet)",
    )
    parser.add_argument(
        "--require-commit-confirm",
        action="store_true",
        help="Require user confirmation before committing (default: auto-commit)",
    )

    args = parser.parse_args()

    # Set global state
    config.VERBOSE_MODE = args.verbose
    config.MODEL = args.model
    config.REQUIRE_CONFIRM = args.require_commit_confirm
    config.RUN_TIMESTAMP = datetime.now().strftime("%Y-%m-%d-%H%M%S")

    # Step 0: Verify Claude authentication
    print("=== Step 0: Verify Claude Authentication ===\n")
    auth_ok, auth_error = await verify_claude_auth()
    if not auth_ok:
        print(f"✗ {auth_error}")
        play_completion_sound()
        return 1
    print("✓ Claude authentication verified\n")

    # Step 1: Discover all modules (Go and Python)
    print("=== Step 1: Discover Modules ===\n")

    # Resolve and validate all module paths
    module_paths = []
    for path_str in args.modules:
        path = Path(path_str).resolve()
        if not path.exists():
            print(f"✗ Module path does not exist: {path}")
            play_completion_sound()
            return 1
        module_paths.append(path)

    # Discover modules from each provided path
    go_modules: list[Path] = []
    python_modules: list[Path] = []
    legacy_projects: list[Path] = []

    for module_path in module_paths:
        # Check if this is a single module
        if (module_path / "go.mod").exists():
            go_modules.append(module_path)
        elif (module_path / "pyproject.toml").exists() and (module_path / "uv.lock").exists():
            python_modules.append(module_path)
        else:
            # Search recursively
            discovered = discover_all_modules(module_path, recursive=True)
            go_modules.extend(discovered["go"])
            python_modules.extend(discovered["python"])
            legacy_projects.extend(discovered["legacy"])

    # Remove duplicates while preserving order
    go_modules = list(dict.fromkeys(go_modules))
    python_modules = list(dict.fromkeys(python_modules))
    legacy_projects = list(dict.fromkeys(legacy_projects))

    # Warn about legacy projects
    if legacy_projects:
        print("⚠ Legacy Python projects detected (skipped):\n")
        for proj in legacy_projects:
            print(f"  - {proj}")
        print('  → Run "uv init" to migrate to modern Python packaging\n')

    total_modules = len(go_modules) + len(python_modules)

    if total_modules == 0:
        print("✗ No modules found in provided path(s)")
        play_completion_sound()
        return 1

    if go_modules:
        print(f"Go modules:     {len(go_modules)}")
        for mod in go_modules:
            print(f"  - {mod}")

    if python_modules:
        print(f"Python modules: {len(python_modules)}")
        for mod in python_modules:
            print(f"  - {mod}")

    print()

    # Combine all modules with their types
    all_modules: list[tuple[Path, str]] = []
    all_modules.extend((mod, "go") for mod in go_modules)
    all_modules.extend((mod, "python") for mod in python_modules)

    # Find unique git repos for all modules
    module_repos = set()
    for module, _ in all_modules:
        module_repo = find_git_repo(module)
        if module_repo:
            module_repos.add(module_repo)

    # Step 2: Update git repositories
    print("=== Step 2: Update Git Repositories ===\n")
    print(f"Updating {len(module_repos)} unique git repository(ies)\n")

    update_errors = []

    for repo in sorted(module_repos):
        print(f"→ {repo.name}")
        if not update_git_branch(repo):
            update_errors.append(repo)

    print()

    if update_errors:
        print("✗ Failed to update repositories:\n")
        for repo in update_errors:
            print(f"  - {repo}")
        print("\nCannot proceed. Please fix errors and try again.")
        play_completion_sound()
        return 1

    # Step 3: Check for uncommitted changes
    print("=== Step 3: Check for Uncommitted Changes ===\n")

    dirty_modules = []

    for module, project_type in all_modules:
        change_count, files = check_git_status(module)

        if change_count == -1:
            print(f"✗ Failed to check status: {module.name}")
            play_completion_sound()
            return 1

        if change_count > 0:
            dirty_modules.append((module, change_count, files, project_type))

    if dirty_modules:
        print("⚠ Uncommitted changes detected in module(s):\n")
        for module, count, files, _ in dirty_modules:
            print(f"  - {module.name}: {count} file(s)")

            condensed_files = condense_file_list(files)
            if len(condensed_files) <= 20:
                for f in condensed_files:
                    print(f"      {f}")
            print()

        if not prompt_yes_no("Continue anyway?", default_yes=True):
            print("\n✗ Aborted by user")
            play_completion_sound()
            return 1
        print()
    else:
        print("✓ No uncommitted changes in module(s)\n")

    print("=" * 70 + "\n")

    # Process modules
    if total_modules == 1:
        module, project_type = all_modules[0]
        lang = "Go" if project_type == "go" else "Python"
        print(f"=== Updating {lang} Module: {module} ===\n")
        success, status = await process_module_with_retry(module, project_type=project_type)
        play_completion_sound()
        return 0 if success else 1

    else:
        print(f"=== Processing {total_modules} Modules ===\n")

        results = []
        for i, (mod, project_type) in enumerate(all_modules, 1):
            lang = "Go" if project_type == "go" else "Python"
            print(f"\n{'#' * 70}")
            print(f"[{i}/{total_modules}] Processing {mod.name} ({lang})")
            print("#" * 70)

            success, status = await process_module_with_retry(mod, project_type=project_type)
            results.append((mod, success, status, project_type))

        # Summary
        print("\n" + "=" * 70)
        print(f"SUMMARY: {total_modules} module(s)")
        print("=" * 70)

        successful = [mod for mod, _, status, _ in results if status == "success"]
        skipped = [mod for mod, _, status, _ in results if status == "skipped"]

        print(f"\n✓ Successful: {len(successful)}/{total_modules}")
        for mod in successful:
            print(f"  - {mod}")

        if skipped:
            print(f"\n⚠ Skipped: {len(skipped)}/{total_modules}")
            for mod in skipped:
                print(f"  - {mod}")

        print("\n" + "=" * 70)

        play_completion_sound()
        return 0


def main() -> int:
    """Main entry point (auto-detect project type).

    Returns:
        Exit code (0 for success, 1 for error)
    """
    return asyncio.run(main_async())


# --- Explicit entry points ---


async def main_go_async() -> int:
    """Go-only async workflow."""
    parser = argparse.ArgumentParser(
        description="Update Go module dependencies, CHANGELOG, and create git tags"
    )
    parser.add_argument(
        "modules",
        nargs="*",
        default=["."],
        help="Path(s) to Go module(s) or parent directories (default: current directory)",
    )
    parser.add_argument("--verbose", action="store_true", help="Show full command output")
    parser.add_argument(
        "--model",
        choices=["sonnet", "opus", "haiku"],
        default="sonnet",
        help="Claude model to use (default: sonnet)",
    )
    parser.add_argument(
        "--require-commit-confirm",
        action="store_true",
        help="Require user confirmation before committing",
    )

    args = parser.parse_args()
    config.VERBOSE_MODE = args.verbose
    config.MODEL = args.model
    config.REQUIRE_CONFIRM = args.require_commit_confirm
    config.RUN_TIMESTAMP = datetime.now().strftime("%Y-%m-%d-%H%M%S")

    # Discover Go modules only
    print("=== Discover Go Modules ===\n")

    module_paths = []
    for path_str in args.modules:
        path = Path(path_str).resolve()
        if not path.exists():
            print(f"✗ Path does not exist: {path}")
            return 1
        module_paths.append(path)

    modules = []
    for module_path in module_paths:
        if (module_path / "go.mod").exists():
            modules.append(module_path)
        else:
            discovered = discover_go_modules(module_path, recursive=True)
            modules.extend(discovered)

    if not modules:
        print("✗ No Go modules found")
        return 1

    # Remove duplicates
    modules = list(dict.fromkeys(modules))

    print(f"Found {len(modules)} Go module(s)\n")

    # Process each module
    for i, mod in enumerate(modules, 1):
        if len(modules) > 1:
            print(f"\n[{i}/{len(modules)}] {mod.name}")
        success, _ = await process_module_with_retry(mod, project_type="go")
        if not success:
            return 1

    play_completion_sound()
    return 0


def main_go() -> int:
    """Go-only entry point."""
    return asyncio.run(main_go_async())


async def main_python_async() -> int:
    """Python-only async workflow."""
    parser = argparse.ArgumentParser(
        description="Update Python dependencies, CHANGELOG, and create git tags"
    )
    parser.add_argument(
        "modules",
        nargs="*",
        default=["."],
        help="Path(s) to Python module(s) or parent directories (default: current directory)",
    )
    parser.add_argument("--verbose", action="store_true", help="Show full command output")
    parser.add_argument(
        "--model",
        choices=["sonnet", "opus", "haiku"],
        default="sonnet",
        help="Claude model to use (default: sonnet)",
    )
    parser.add_argument(
        "--require-commit-confirm",
        action="store_true",
        help="Require user confirmation before committing",
    )

    args = parser.parse_args()
    config.VERBOSE_MODE = args.verbose
    config.MODEL = args.model
    config.REQUIRE_CONFIRM = args.require_commit_confirm
    config.RUN_TIMESTAMP = datetime.now().strftime("%Y-%m-%d-%H%M%S")

    # Discover Python modules only
    print("=== Discover Python Modules ===\n")

    module_paths = []
    for path_str in args.modules:
        path = Path(path_str).resolve()
        if not path.exists():
            print(f"✗ Path does not exist: {path}")
            return 1
        module_paths.append(path)

    modules = []
    legacy = []
    for module_path in module_paths:
        if (module_path / "pyproject.toml").exists() and (module_path / "uv.lock").exists():
            modules.append(module_path)
        else:
            discovered = discover_python_modules(module_path, recursive=True)
            modules.extend(discovered)
            legacy.extend(discover_legacy_python_projects(module_path, recursive=True))

    # Warn about legacy projects
    if legacy:
        print("⚠ Legacy Python projects detected (skipped):\n")
        for proj in legacy:
            print(f"  - {proj}")
        print('  → Run "uv init" to migrate to modern Python packaging\n')

    if not modules:
        print("✗ No Python modules found (requires pyproject.toml + uv.lock)")
        return 1

    # Remove duplicates
    modules = list(dict.fromkeys(modules))

    print(f"Found {len(modules)} Python module(s)\n")

    # Process each module
    for i, mod in enumerate(modules, 1):
        if len(modules) > 1:
            print(f"\n[{i}/{len(modules)}] {mod.name}")
        success, _ = await process_module_with_retry(mod, project_type="python")
        if not success:
            return 1

    play_completion_sound()
    return 0


def main_python() -> int:
    """Python-only entry point."""
    return asyncio.run(main_python_async())


async def main_docker_async() -> int:
    """Docker-only async workflow (update base images only, no commit)."""
    parser = argparse.ArgumentParser(
        description="Update Dockerfile base images to latest versions (no commit)"
    )
    parser.add_argument(
        "paths",
        nargs="*",
        default=["."],
        help="Path(s) to directories containing Dockerfile (default: current directory)",
    )
    parser.add_argument("--verbose", action="store_true", help="Show full command output")

    args = parser.parse_args()
    config.VERBOSE_MODE = args.verbose

    print("=== Docker Image Updates ===\n")

    any_updates = False
    for path_str in args.paths:
        path = Path(path_str).resolve()
        if not path.exists():
            print(f"✗ Path does not exist: {path}")
            continue

        dockerfile = path / "Dockerfile"
        if not dockerfile.exists():
            # Search for Dockerfiles in subdirectories
            for df in path.rglob("Dockerfile"):
                if ".venv" not in df.parts:
                    print(f"\n→ {df.parent}")
                    if update_dockerfile_images(df.parent, log_func=log_message):
                        any_updates = True
        else:
            print(f"\n→ {path}")
            if update_dockerfile_images(path, log_func=log_message):
                any_updates = True

    if any_updates:
        print("\n✓ Dockerfile(s) updated - review and commit manually")
    else:
        print("\n✓ All Dockerfiles are up to date")

    return 0


def main_docker() -> int:
    """Docker-only entry point."""
    return asyncio.run(main_docker_async())
