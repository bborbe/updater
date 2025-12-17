"""CLI orchestration and workflow."""

import argparse
import asyncio
import sys
import traceback
from datetime import datetime
from pathlib import Path

from . import config
from .changelog import update_changelog_with_suggestions
from .claude_analyzer import analyze_changes_with_claude
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
from .log_manager import (
    cleanup_old_logs,
    close_module_logging,
    log_message,
    setup_module_logging,
)
from .module_discovery import discover_go_modules
from .prompts import prompt_skip_or_retry, prompt_yes_no


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
        log_message('=' * 70, to_console=True)
        if log_file and not config.VERBOSE_MODE:
            print(f"  Log: {log_file}")

        # Ensure .update-logs/ is in .gitignore
        ensure_gitignore_entry(module_path, log_func=log_message)

        # Find git repo first
        git_repo = find_git_repo(module_path)
        if not git_repo:
            log_message("✗ No git repository found", to_console=True)
            return False

        # Phase 1: Update dependencies
        updates_made = update_go_dependencies(module_path, log_func=log_message)

        # Phase 1b: Check if git shows any changes (from this run or previous runs)
        change_count, files = check_git_status(git_repo)

        if change_count == 0 and not updates_made:
            log_message("\n✓ No updates needed - module is already up to date", to_console=True)
            return True

        if change_count == 0:
            log_message("\n✓ No changes detected after dependency update", to_console=True)
            return True

        if updates_made:
            log_message(f"\n→ {change_count} file(s) changed after dependency update", to_console=True)
        else:
            log_message(f"\n→ Processing {change_count} uncommitted file(s) from previous run", to_console=True)

        # Show condensed file list if 20 or fewer lines
        condensed_files = condense_file_list(files)
        if len(condensed_files) <= 20:
            for f in condensed_files:
                log_message(f"  {f}", to_console=True)

        # Phase 2: Run precommit (validate and auto-format)
        run_precommit(module_path, log_func=log_message)

        # Phase 2b: Check if changes remain after precommit
        change_count, files = check_git_status(git_repo)
        if change_count == 0:
            log_message("\n✓ No changes remain after precommit (auto-formatted/fixed)", to_console=True)
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
        if analysis['version_bump'] == 'none':
            # No version bump needed - just commit without CHANGELOG/tag
            log_message("\n→ No version bump needed (infrastructure changes only)", to_console=True)

            print("\n" + "=" * 60)
            print(f"READY TO COMMIT: {module_path.name}")
            print("=" * 60)
            print(f"Commit message: {analysis['commit_message']}")
            print("\nChanges:")
            for bullet in analysis['changelog']:
                print(f"  - {bullet.lstrip('- ')}")
            print("\nNote: No version bump or tag (infrastructure changes only)")
            print("=" * 60)

            # Ask for confirmation
            if not prompt_yes_no("\nProceed with commit (no tag)?", default_yes=True):
                log_message("\n⚠ Skipped by user", to_console=True)
                log_message("  Changes are staged but not committed", to_console=True)
                return True

            git_commit(module_path, analysis['commit_message'], log_func=log_message)
            log_message("\n✓ Commit completed successfully (no tag)!", to_console=True)
            return True

        # Phase 4: Update CHANGELOG with Claude's suggestions
        new_version = update_changelog_with_suggestions(module_path, analysis, log_func=log_message)

        # Show summary and ask for confirmation (always to console)
        print("\n" + "=" * 60)
        print(f"READY TO COMMIT: {module_path.name}")
        print("=" * 60)
        print(f"Version:        {new_version} ({analysis['version_bump']} bump)")
        print(f"Commit message: {analysis['commit_message']}")
        print(f"Git tag:        {new_version} (will be created)")
        print("\nChangelog entries:")
        for bullet in analysis['changelog']:
            print(f"  - {bullet.lstrip('- ')}")
        print("=" * 60)

        # Ask for confirmation
        if not prompt_yes_no("\nProceed with commit and tag?", default_yes=True):
            log_message("\n⚠ Skipped by user", to_console=True)
            log_message("  Changes are staged but not committed", to_console=True)
            return True

        git_commit(module_path, analysis['commit_message'], log_func=log_message)
        git_tag_from_changelog(module_path, log_func=log_message)
        log_message("\n✓ Update completed successfully!", to_console=True)
        return True

    except Exception as e:
        log_message(f"\n✗ Error processing {module_path.name}: {e}", to_console=True)
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
            print(f"\n=== Retrying {module_path.name} (attempt {attempt}) ===\n")

        success = await process_single_module(module_path)

        if success:
            return True, 'success'

        # Failed - prompt for skip or retry
        print(f"\n✗ Module {module_path.name} failed")
        print("  → Fix the issues and retry, or skip this module")

        choice = prompt_skip_or_retry()

        if choice == 'skip':
            print(f"⚠ Skipping {module_path.name}\n")
            return False, 'skipped'

        # Retry - increment attempt counter
        attempt += 1


async def main_async() -> int:
    """Main async workflow.

    Returns:
        Exit code (0 for success, 1 for error)
    """
    parser = argparse.ArgumentParser(
        description='Update Go module dependencies, CHANGELOG, and create git tags'
    )
    parser.add_argument(
        'module',
        help='Path to Go module (e.g., lib/alert) or parent directory (e.g., lib)'
    )
    parser.add_argument(
        '--verbose',
        action='store_true',
        help='Show full command output (default: quiet with logs in .update-logs/)'
    )
    parser.add_argument(
        '--model',
        choices=['sonnet', 'opus', 'haiku'],
        default='sonnet',
        help='Claude model to use (default: sonnet)'
    )

    args = parser.parse_args()

    # Set global state
    config.VERBOSE_MODE = args.verbose
    config.MODEL = args.model
    config.RUN_TIMESTAMP = datetime.now().strftime("%Y-%m-%d-%H%M%S")

    # Resolve module path
    module_path = Path(args.module)

    if not module_path.exists():
        print(f"✗ Module path does not exist: {module_path}")
        return 1

    # Step 1: Discover Go modules to update
    print("=== Step 1: Discover Go Modules ===\n")

    # Check if this is a single module or parent directory
    if (module_path / "go.mod").exists():
        modules = [module_path]
        print(f"Single module mode: {module_path}\n")
    else:
        # Try non-recursive first (direct children only)
        modules = discover_go_modules(module_path, recursive=False)

        # If no direct children, try recursive search (monorepo mode)
        if not modules:
            modules = discover_go_modules(module_path, recursive=True)
            if modules:
                print(f"Monorepo mode: searching recursively\n")

        if not modules:
            print(f"✗ No Go modules found in: {module_path}")
            return 1

        print(f"Found {len(modules)} Go module(s):\n")
        for i, mod in enumerate(modules, 1):
            # Show relative path for better clarity in monorepo mode
            try:
                rel_path = mod.relative_to(module_path)
                print(f"  {i}. {rel_path}")
            except ValueError:
                print(f"  {i}. {mod.name}")
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
        return 1

    # Step 3: Check for uncommitted changes
    print("=== Step 3: Check for Uncommitted Changes ===\n")

    dirty_repos = []

    for repo in sorted(module_repos):
        change_count, files = check_git_status(repo)

        if change_count == -1:
            print(f"✗ Failed to check status: {repo}")
            return 1

        if change_count > 0:
            dirty_repos.append((repo, change_count, files))

    if dirty_repos:
        print("⚠ Uncommitted changes detected:\n")
        for repo, count, files in dirty_repos:
            print(f"  - {repo.name}: {count} file(s)")

            # Show condensed file list if 20 or fewer lines
            condensed_files = condense_file_list(files)
            if len(condensed_files) <= 20:
                for f in condensed_files:
                    print(f"      {f}")
            print()

        if not prompt_yes_no("Continue anyway?", default_yes=True):
            print("\n✗ Aborted by user")
            return 1
        print()
    else:
        print("✓ No uncommitted changes\n")

    print("=" * 70 + "\n")

    # Process modules
    if len(modules) == 1:
        # Single module mode
        print(f"=== Updating Go Module: {modules[0]} ===\n")
        success, status = await process_module_with_retry(modules[0])
        return 0 if success else 1

    else:
        # Multi-module mode - each module gets its own Claude session
        print(f"=== Processing {len(modules)} Go Modules ===\n")

        results = []
        for i, mod in enumerate(modules, 1):
            print(f"\n{'#' * 70}")
            print(f"[{i}/{len(modules)}] Processing {mod.name}")
            print('#' * 70)

            success, status = await process_module_with_retry(mod)
            results.append((mod.name, success, status))

        # Summary
        print("\n" + "=" * 70)
        print("SUMMARY")
        print("=" * 70)

        successful = [name for name, _, status in results if status == 'success']
        skipped = [name for name, _, status in results if status == 'skipped']

        print(f"\n✓ Successful: {len(successful)}/{len(modules)}")
        for name in successful:
            print(f"  - {name}")

        if skipped:
            print(f"\n⚠ Skipped: {len(skipped)}/{len(modules)}")
            for name in skipped:
                print(f"  - {name}")

        print("\n" + "=" * 70)

        # Exit with success (skipped modules are not errors)
        return 0


def main() -> int:
    """Main entry point.

    Returns:
        Exit code (0 for success, 1 for error)
    """
    return asyncio.run(main_async())
