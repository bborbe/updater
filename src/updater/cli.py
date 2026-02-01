"""CLI orchestration and workflow."""

import argparse
import asyncio
import traceback
from datetime import datetime
from pathlib import Path

from . import config
from .changelog import update_changelog_with_suggestions
from .claude_analyzer import analyze_changes_with_claude, verify_claude_auth
from .file_utils import condense_file_list
from .git_operations import (
    check_git_status,
    ensure_gitignore_entry,
    find_git_repo,
    git_commit,
    git_tag_from_changelog,
    update_git_branch,
)
from .go_updater import run_precommit, update_go_dependencies
from .gomod_excludes import apply_gomod_excludes_and_replaces
from .log_manager import (
    cleanup_old_logs,
    close_module_logging,
    log_message,
    setup_module_logging,
)
from .module_discovery import discover_go_modules
from .prompts import prompt_skip_or_retry, prompt_yes_no
from .sound import play_completion_sound, play_error_sound
from .version_updater import update_versions


async def process_single_module(module_path: Path) -> bool:
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
        run_precommit(module_path, log_func=log_message)

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

            print("\n" + "=" * 60)
            print(f"READY TO COMMIT: {module_path.name}")
            print("=" * 60)
            print(f"Commit message: {analysis['commit_message']}")
            print("\nChanges:")
            for bullet in analysis["changelog"]:
                print(f"  - {bullet.lstrip('- ')}")
            print("\nNote: No version bump or tag (infrastructure changes only)")
            print("=" * 60)

            # Ask for confirmation if required
            if config.REQUIRE_CONFIRM:
                if not prompt_yes_no("\nProceed with commit (no tag)?", default_yes=True):
                    log_message("\n⚠ Skipped by user", to_console=True)
                    log_message("  Changes are staged but not committed", to_console=True)
                    return True

            git_commit(module_path, analysis["commit_message"], log_func=log_message)
            log_message("\n✓ Commit completed successfully (no tag)!", to_console=True)
            return True

        # Phase 4: Update CHANGELOG with Claude's suggestions
        changelog_path = module_path / "CHANGELOG.md"

        if not changelog_path.exists():
            # No CHANGELOG.md - commit without tag
            log_message("\n→ No CHANGELOG.md found, committing without tag", to_console=True)

            print("\n" + "=" * 60)
            print(f"READY TO COMMIT: {module_path.name}")
            print("=" * 60)
            print(f"Commit message: {analysis['commit_message']}")
            print("\nChanges:")
            for bullet in analysis["changelog"]:
                print(f"  - {bullet.lstrip('- ')}")
            print("\nNote: No CHANGELOG.md found, no version tag will be created")
            print("=" * 60)

            # Ask for confirmation if required
            if config.REQUIRE_CONFIRM:
                if not prompt_yes_no("\nProceed with commit (no tag)?", default_yes=True):
                    log_message("\n⚠ Skipped by user", to_console=True)
                    log_message("  Changes are staged but not committed", to_console=True)
                    return True

            git_commit(module_path, analysis["commit_message"], log_func=log_message)
            log_message("\n✓ Commit completed successfully (no tag)!", to_console=True)
            return True

        # CHANGELOG.md exists - update and create tag
        new_version = update_changelog_with_suggestions(module_path, analysis, log_func=log_message)

        # Show summary and ask for confirmation (always to console)
        print("\n" + "=" * 60)
        print(f"READY TO COMMIT: {module_path.name}")
        print("=" * 60)
        print(f"Version:        {new_version} ({analysis['version_bump']} bump)")
        print(f"Commit message: {analysis['commit_message']}")
        print(f"Git tag:        {new_version} (will be created)")
        print("\nChangelog entries:")
        for bullet in analysis["changelog"]:
            print(f"  - {bullet.lstrip('- ')}")
        print("=" * 60)

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


async def process_module_with_retry(module_path: Path) -> tuple[bool, str]:
    """Process a single module with retry on failure.

    Args:
        module_path: Path to the module

    Returns:
        Tuple of (success: bool, status: str)
        status can be: 'success', 'skipped'
    """
    attempt = 1

    while True:
        if attempt > 1:
            print(f"\n=== Retrying {module_path} (attempt {attempt}) ===\n")

        success = await process_single_module(module_path)

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
    """Main async workflow.

    Returns:
        Exit code (0 for success, 1 for error)
    """
    parser = argparse.ArgumentParser(
        description="Update Go module dependencies, CHANGELOG, and create git tags"
    )
    parser.add_argument(
        "modules",
        nargs="*",
        default=["."],
        help="Path(s) to Go module(s) or parent directories (default: current directory)",
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

    # Step 1: Discover Go modules to update
    print("=== Step 1: Discover Go Modules ===\n")

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
    modules = []
    for module_path in module_paths:
        # Check if this is a single module or parent directory
        if (module_path / "go.mod").exists():
            modules.append(module_path)
        else:
            # Search recursively to find all nested modules
            discovered = discover_go_modules(module_path, recursive=True)
            modules.extend(discovered)

    if not modules:
        print("✗ No Go modules found in provided path(s)")
        play_completion_sound()
        return 1

    # Remove duplicates while preserving order
    seen = set()
    unique_modules = []
    for mod in modules:
        if mod not in seen:
            seen.add(mod)
            unique_modules.append(mod)
    modules = unique_modules

    if len(modules) == 1:
        print(f"Single module mode: {modules[0]}\n")
    else:
        print(f"Multi-module mode: found {len(modules)} modules\n")
        print(f"Found {len(modules)} Go module(s):\n")
        for i, mod in enumerate(modules, 1):
            print(f"  {i}. {mod}")
        print()

    # Find unique git repos for the modules we're processing
    module_repos = set()
    for module in modules:
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

    # Step 3: Check for uncommitted changes in module directories
    print("=== Step 3: Check for Uncommitted Changes ===\n")

    dirty_modules = []

    for module in modules:
        change_count, files = check_git_status(module)

        if change_count == -1:
            print(f"✗ Failed to check status: {module.name}")
            play_completion_sound()
            return 1

        if change_count > 0:
            dirty_modules.append((module, change_count, files))

    if dirty_modules:
        print("⚠ Uncommitted changes detected in module(s):\n")
        for module, count, files in dirty_modules:
            print(f"  - {module.name}: {count} file(s)")

            # Show condensed file list if 20 or fewer lines
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
    if len(modules) == 1:
        # Single module mode
        print(f"=== Updating Go Module: {modules[0]} ===\n")
        success, status = await process_module_with_retry(modules[0])
        play_completion_sound()
        return 0 if success else 1

    else:
        # Multi-module mode - each module gets its own Claude session
        print(f"=== Processing {len(modules)} Go Modules ===\n")

        results = []
        for i, mod in enumerate(modules, 1):
            print(f"\n{'#' * 70}")
            print(f"[{i}/{len(modules)}] Processing {mod.name}")
            print("#" * 70)

            success, status = await process_module_with_retry(mod)
            results.append((mod, success, status))

        # Summary
        print("\n" + "=" * 70)
        if len(module_paths) == 1:
            print(f"SUMMARY: {module_paths[0]}")
        else:
            print(f"SUMMARY: {len(module_paths)} input path(s), {len(modules)} module(s)")
        print("=" * 70)

        successful = [mod for mod, _, status in results if status == "success"]
        skipped = [mod for mod, _, status in results if status == "skipped"]

        print(f"\n✓ Successful: {len(successful)}/{len(modules)}")
        for mod in successful:
            print(f"  - {mod}")

        if skipped:
            print(f"\n⚠ Skipped: {len(skipped)}/{len(modules)}")
            for mod in skipped:
                print(f"  - {mod}")

        print("\n" + "=" * 70)

        # Exit with success (skipped modules are not errors)
        play_completion_sound()
        return 0


def main() -> int:
    """Main entry point.

    Returns:
        Exit code (0 for success, 1 for error)
    """
    return asyncio.run(main_async())
