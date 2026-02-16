"""CLI orchestration and workflow."""

import argparse
import asyncio
import traceback
from datetime import datetime
from pathlib import Path

from . import config
from .changelog import (
    add_to_unreleased,
    extract_current_version,
    get_unreleased_entries,
    promote_unreleased_to_version,
    update_changelog_with_suggestions,
)
from .claude_analyzer import (
    analyze_changes_with_claude,
    analyze_unreleased_for_release,
    verify_claude_auth,
)
from .docker_updater import update_dockerfile_images
from .file_utils import condense_file_list
from .git_operations import (
    check_git_status,
    ensure_changelog_tag,
    ensure_gitignore_entry,
    find_git_repo,
    git_commit,
    git_push,
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


async def process_single_go_module(module_path: Path, update_deps: bool = True) -> tuple[bool, str]:
    """Process a single Go module.

    Creates a new Claude session for analyzing changes to ensure clean, isolated analysis.

    Args:
        module_path: Path to the module
        update_deps: Whether to update dependencies (default: True)

    Returns:
        Tuple of (success: bool, status: str)
        status can be: 'updated', 'up-to-date', 'skipped', 'failed'
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
            return (False, "failed")

        # Phase 1a: Update runtime versions (golang, alpine)
        version_updates = update_versions(module_path, log_func=log_message)

        # Phase 1b: Apply standard excludes and replaces
        log_message("\n=== Phase 1b: Apply Standard Excludes/Replaces ===", to_console=True)
        excludes_updates = apply_gomod_excludes_and_replaces(module_path, log_func=log_message)

        # Phase 1c: Update dependencies (optional)
        dep_updates = False
        if update_deps:
            dep_updates = update_go_dependencies(module_path, log_func=log_message)
        else:
            log_message("\n=== Phase 1c: Skip Dependency Updates ===", to_console=True)
            log_message("  → Updating Go version only (no dependency changes)", to_console=True)

        updates_made = version_updates or excludes_updates or dep_updates

        # Phase 1d: Check if git shows any changes (from this run or previous runs)
        change_count, files = check_git_status(module_path)

        if change_count == 0 and not updates_made:
            log_message("\n✓ No updates needed - module is already up to date", to_console=True)
            return (True, "up-to-date")

        if change_count == 0:
            log_message("\n✓ No changes detected after dependency update", to_console=True)
            return (True, "up-to-date")

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
            return (True, "up-to-date")

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
                    return (True, "skipped")

            git_commit(module_path, analysis["commit_message"], log_func=log_message)
            ensure_changelog_tag(module_path, log_func=log_message)
            log_message("\n✓ Commit completed successfully!", to_console=True)
            return (True, "updated")

        # Phase 4: Update CHANGELOG with Claude's suggestions
        changelog_path = module_path / "CHANGELOG.md"

        # Handle --no-tag mode (add to Unreleased, no version/tag)
        if config.NO_TAG:
            if not changelog_path.exists():
                log_message(
                    "\n→ No CHANGELOG.md found, committing without changes", to_console=True
                )
                print_commit_summary(
                    module_path.name,
                    analysis,
                    note="No CHANGELOG.md found (--no-tag mode)",
                )
            else:
                add_to_unreleased(module_path, analysis, log_func=log_message)
                print_commit_summary(
                    module_path.name,
                    analysis,
                    note="Changes added to ## Unreleased (--no-tag mode)",
                )

            # Ask for confirmation if required
            if config.REQUIRE_CONFIRM:
                if not prompt_yes_no("\nProceed with commit (no tag)?", default_yes=True):
                    log_message("\n⚠ Skipped by user", to_console=True)
                    log_message("  Changes are staged but not committed", to_console=True)
                    return (True, "skipped")

            git_commit(module_path, analysis["commit_message"], log_func=log_message)
            log_message("\n✓ Commit completed successfully!", to_console=True)
            return (True, "updated")

        # Normal mode: create version and tag
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
                    return (True, "skipped")

            git_commit(module_path, analysis["commit_message"], log_func=log_message)
            log_message("\n✓ Commit completed successfully!", to_console=True)
            return (True, "updated")

        # CHANGELOG.md exists - update and create tag
        new_version = update_changelog_with_suggestions(module_path, analysis, log_func=log_message)

        # Show summary and ask for confirmation (always to console)
        print_commit_summary(module_path.name, analysis, new_version=new_version)

        # Ask for confirmation if required
        if config.REQUIRE_CONFIRM:
            if not prompt_yes_no("\nProceed with commit and tag?", default_yes=True):
                log_message("\n⚠ Skipped by user", to_console=True)
                log_message("  Changes are staged but not committed", to_console=True)
                return (True, "skipped")

        git_commit(module_path, analysis["commit_message"], log_func=log_message)
        git_tag_from_changelog(module_path, log_func=log_message)
        log_message("\n✓ Update completed successfully!", to_console=True)
        return (True, "updated")

    except Exception as e:
        log_message(f"\n✗ Error processing {module_path}: {e}", to_console=True)
        if config.VERBOSE_MODE:
            traceback.print_exc()
        return (False, "failed")
    finally:
        # Close logging and cleanup old logs
        close_module_logging()
        cleanup_old_logs(module_path)


async def process_single_python_module(module_path: Path) -> tuple[bool, str]:
    """Process a single Python module.

    Creates a new Claude session for analyzing changes to ensure clean, isolated analysis.

    Args:
        module_path: Path to the module

    Returns:
        Tuple of (success: bool, status: str)
        status can be: 'updated', 'up-to-date', 'skipped', 'failed'
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
            return (False, "failed")

        # Phase 1a: Update Python versions
        version_updates = update_python_versions(module_path, log_func=log_message)

        # Phase 1b: Update dependencies
        dep_updates = update_python_dependencies(module_path, log_func=log_message)

        updates_made = version_updates or dep_updates

        # Check if git shows any changes
        change_count, files = check_git_status(module_path)

        if change_count == 0 and not updates_made:
            log_message("\n✓ No updates needed - module is already up to date", to_console=True)
            return (True, "up-to-date")

        if change_count == 0:
            log_message("\n✓ No changes detected after dependency update", to_console=True)
            return (True, "up-to-date")

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
            return (True, "up-to-date")

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
                    return (True, "skipped")

            git_commit(module_path, analysis["commit_message"], log_func=log_message)
            ensure_changelog_tag(module_path, log_func=log_message)
            log_message("\n✓ Commit completed successfully!", to_console=True)
            return (True, "updated")

        # Phase 4: Update CHANGELOG with Claude's suggestions
        changelog_path = module_path / "CHANGELOG.md"

        # Handle --no-tag mode (add to Unreleased, no version/tag)
        if config.NO_TAG:
            if not changelog_path.exists():
                log_message(
                    "\n→ No CHANGELOG.md found, committing without changes", to_console=True
                )
                print_commit_summary(
                    module_path.name,
                    analysis,
                    note="No CHANGELOG.md found (--no-tag mode)",
                )
            else:
                add_to_unreleased(module_path, analysis, log_func=log_message)
                print_commit_summary(
                    module_path.name,
                    analysis,
                    note="Changes added to ## Unreleased (--no-tag mode)",
                )

            # Ask for confirmation if required
            if config.REQUIRE_CONFIRM:
                if not prompt_yes_no("\nProceed with commit (no tag)?", default_yes=True):
                    log_message("\n⚠ Skipped by user", to_console=True)
                    log_message("  Changes are staged but not committed", to_console=True)
                    return (True, "skipped")

            git_commit(module_path, analysis["commit_message"], log_func=log_message)
            log_message("\n✓ Commit completed successfully!", to_console=True)
            return (True, "updated")

        # Normal mode: create version and tag
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
                    return (True, "skipped")

            git_commit(module_path, analysis["commit_message"], log_func=log_message)
            log_message("\n✓ Commit completed successfully!", to_console=True)
            return (True, "updated")

        # CHANGELOG.md exists - update and create tag
        new_version = update_changelog_with_suggestions(module_path, analysis, log_func=log_message)

        print_commit_summary(module_path.name, analysis, new_version=new_version)

        if config.REQUIRE_CONFIRM:
            if not prompt_yes_no("\nProceed with commit and tag?", default_yes=True):
                log_message("\n⚠ Skipped by user", to_console=True)
                log_message("  Changes are staged but not committed", to_console=True)
                return (True, "skipped")

        git_commit(module_path, analysis["commit_message"], log_func=log_message)
        git_tag_from_changelog(module_path, log_func=log_message)
        log_message("\n✓ Update completed successfully!", to_console=True)
        return (True, "updated")

    except Exception as e:
        log_message(f"\n✗ Error processing {module_path}: {e}", to_console=True)
        if config.VERBOSE_MODE:
            traceback.print_exc()
        return (False, "failed")
    finally:
        close_module_logging()
        cleanup_old_logs(module_path)


async def process_module_with_retry(
    module_path: Path, project_type: str = "go", update_deps: bool = True
) -> tuple[bool, str]:
    """Process a single module with retry on failure.

    Args:
        module_path: Path to the module
        project_type: Type of project ("go", "python", or "docker")
        update_deps: Whether to update dependencies for Go modules (default: True)

    Returns:
        Tuple of (success: bool, status: str)
        status can be: 'updated', 'up-to-date', 'skipped', 'failed'
    """
    attempt = 1

    while True:
        if attempt > 1:
            print(f"\n=== Retrying {module_path} (attempt {attempt}) ===\n")

        if project_type == "python":
            success, status = await process_single_python_module(module_path)
        elif project_type == "docker":
            # Docker projects: update Dockerfile images and commit
            log_message(f"\n{'=' * 70}", to_console=True)
            log_message(f"Docker Project: {module_path.name}", to_console=True)
            log_message("=" * 70, to_console=True)

            updated, updates = update_dockerfile_images(module_path, log_func=log_message)

            if updated:
                # Check if there are actually uncommitted changes
                change_count, _ = check_git_status(module_path)

                if change_count > 0:
                    # Generate commit message from updates
                    if len(updates) == 1:
                        commit_msg = f"Update Dockerfile: {updates[0]}"
                    else:
                        commit_msg = "Update Dockerfile images\n\n" + "\n".join(
                            f"- {u}" for u in updates
                        )

                    # Commit changes
                    log_message("\n=== Committing Changes ===", to_console=True)
                    git_commit(module_path, commit_msg, log_func=log_message)
                    log_message("\n✓ Dockerfile updated and committed", to_console=True)
                    success, status = True, "updated"
                else:
                    log_message(
                        "\n✓ Dockerfile updated (already matches committed version)",
                        to_console=True,
                    )
                    success, status = True, "up-to-date"
            else:
                log_message("\n✓ Dockerfile already up to date", to_console=True)
                success, status = True, "up-to-date"
        else:
            success, status = await process_single_go_module(module_path, update_deps=update_deps)

        if success:
            return True, status

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
    parser.add_argument(
        "--skip-git-update",
        action="store_true",
        help="Skip git branch checkout and pull (useful for worktree conflicts)",
    )
    parser.add_argument(
        "--no-tag",
        action="store_true",
        help="Add changes to ## Unreleased instead of creating version/tag (useful for PRs)",
    )

    args = parser.parse_args()

    # Set global state
    config.VERBOSE_MODE = args.verbose
    config.MODEL = args.model
    config.REQUIRE_CONFIRM = args.require_commit_confirm
    config.NO_TAG = args.no_tag
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
    docker_projects: list[Path] = []
    legacy_projects: list[Path] = []

    for module_path in module_paths:
        # Check if this is a single module
        if (module_path / "go.mod").exists():
            go_modules.append(module_path)
        elif (module_path / "pyproject.toml").exists() and (module_path / "uv.lock").exists():
            python_modules.append(module_path)
        elif (module_path / "Dockerfile").exists():
            # Standalone Dockerfile (not in Go/Python project)
            docker_projects.append(module_path)
        else:
            # Search recursively
            discovered = discover_all_modules(module_path, recursive=True)
            go_modules.extend(discovered["go"])
            python_modules.extend(discovered["python"])
            docker_projects.extend(discovered["docker"])
            legacy_projects.extend(discovered["legacy"])

    # Remove duplicates while preserving order
    go_modules = list(dict.fromkeys(go_modules))
    python_modules = list(dict.fromkeys(python_modules))
    docker_projects = list(dict.fromkeys(docker_projects))
    legacy_projects = list(dict.fromkeys(legacy_projects))

    # Warn about legacy projects
    if legacy_projects:
        print("⚠ Legacy Python projects detected (skipped):\n")
        for proj in legacy_projects:
            print(f"  - {proj}")
        print('  → Run "uv init" to migrate to modern Python packaging\n')

    total_modules = len(go_modules) + len(python_modules) + len(docker_projects)

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

    if docker_projects:
        print(f"Docker projects: {len(docker_projects)}")
        for mod in docker_projects:
            print(f"  - {mod}")

    print()

    # Combine all modules with their types
    all_modules: list[tuple[Path, str]] = []
    all_modules.extend((mod, "go") for mod in go_modules)
    all_modules.extend((mod, "python") for mod in python_modules)
    all_modules.extend((mod, "docker") for mod in docker_projects)

    # Find unique git repos for all modules
    module_repos = set()
    for module, _ in all_modules:
        module_repo = find_git_repo(module)
        if module_repo:
            module_repos.add(module_repo)

    # Step 2: Update git repositories
    if args.skip_git_update:
        print("=== Step 2: Update Git Repositories ===\n")
        print("⚠ Skipping git update (--skip-git-update flag set)\n")
    else:
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
        if project_type == "go":
            lang = "Go"
        elif project_type == "python":
            lang = "Python"
        else:
            lang = "Docker"
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
        # Find common base path for all modules
        common_path = None
        if all_modules:
            module_paths_list = [mod for mod, _ in all_modules]
            if len(module_paths_list) == 1:
                common_path = module_paths_list[0].parent
            else:
                # Find common parent directory
                common_path = module_paths_list[0]
                for mod_path in module_paths_list[1:]:
                    # Find common ancestor
                    while common_path not in mod_path.parents and common_path != mod_path:
                        common_path = common_path.parent
                        if common_path == common_path.parent:  # Reached root
                            break

        print("\n" + "=" * 70)
        if common_path:
            print(f"SUMMARY: {total_modules} module(s) in {common_path}")
        else:
            print(f"SUMMARY: {total_modules} module(s)")
        print("=" * 70)

        updated = [mod for mod, _, status, _ in results if status == "updated"]
        up_to_date = [mod for mod, _, status, _ in results if status == "up-to-date"]
        skipped = [mod for mod, _, status, _ in results if status == "skipped"]
        failed = [mod for mod, _, status, _ in results if status == "failed"]

        if updated:
            print(f"\n✓ Updated: {len(updated)}")
            for mod in updated:
                print(f"  - {mod.name}")

        if up_to_date:
            print(f"\n✓ Already up to date: {len(up_to_date)}")
            for mod in up_to_date:
                print(f"  - {mod.name}")

        if skipped:
            print(f"\n⚠ Skipped: {len(skipped)}")
            for mod in skipped:
                print(f"  - {mod.name}")

        if failed:
            print(f"\n✗ Failed: {len(failed)}")
            for mod in failed:
                print(f"  - {mod.name}")

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
    """Go-only entry point (includes dependency updates)."""
    return asyncio.run(main_go_async())


async def main_go_only_async() -> int:
    """Go version-only async workflow (no dependency updates)."""
    parser = argparse.ArgumentParser(description="Update Go versions only (no dependency updates)")
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

    # Process each module (version updates only)
    for i, mod in enumerate(modules, 1):
        if len(modules) > 1:
            print(f"\n[{i}/{len(modules)}] {mod.name}")
        success, _ = await process_module_with_retry(mod, project_type="go", update_deps=False)
        if not success:
            return 1

    play_completion_sound()
    return 0


def main_go_only() -> int:
    """Go version-only entry point (no dependency updates)."""
    return asyncio.run(main_go_only_async())


async def main_go_with_deps_async() -> int:
    """Go with dependencies async workflow (explicit name for clarity)."""
    parser = argparse.ArgumentParser(description="Update Go versions and dependencies")
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

    # Process each module (with dependencies)
    for i, mod in enumerate(modules, 1):
        if len(modules) > 1:
            print(f"\n[{i}/{len(modules)}] {mod.name}")
        success, _ = await process_module_with_retry(mod, project_type="go", update_deps=True)
        if not success:
            return 1

    play_completion_sound()
    return 0


def main_go_with_deps() -> int:
    """Go with dependencies entry point."""
    return asyncio.run(main_go_with_deps_async())


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
                    updated, _ = update_dockerfile_images(df.parent, log_func=log_message)
                    if updated:
                        any_updates = True
        else:
            print(f"\n→ {path}")
            updated, _ = update_dockerfile_images(path, log_func=log_message)
            if updated:
                any_updates = True

    if any_updates:
        print("\n✓ Dockerfile(s) updated - review and commit manually")
    else:
        print("\n✓ All Dockerfiles are up to date")

    return 0


def main_docker() -> int:
    """Docker-only entry point."""
    return asyncio.run(main_docker_async())


async def process_release_module(module_path: Path) -> tuple[bool, str]:
    """Process a single module for release-only workflow.

    Scans CHANGELOG.md for unreleased entries, uses Claude to determine
    version bump, promotes unreleased to versioned section, commits, tags, and pushes.

    Args:
        module_path: Path to the module

    Returns:
        Tuple of (success: bool, status: str)
        status can be: 'released', 'nothing-to-release', 'skipped', 'failed'
    """
    from .changelog import bump_version

    log_file = None
    try:
        log_file = setup_module_logging(module_path)

        log_message(f"\n{'=' * 70}", to_console=True)
        log_message(f"Release: {module_path.name}", to_console=True)
        log_message("=" * 70, to_console=True)
        if log_file and not config.VERBOSE_MODE:
            print(f"  Log: {log_file}")

        # Find git repo
        git_repo = find_git_repo(module_path)
        if not git_repo:
            log_message("✗ No git repository found", to_console=True)
            return (False, "failed")

        # Check for CHANGELOG.md
        changelog_path = module_path / "CHANGELOG.md"
        if not changelog_path.exists():
            log_message("Nothing to release (no CHANGELOG.md)", to_console=True)
            return (True, "nothing-to-release")

        # Get unreleased entries
        entries = get_unreleased_entries(changelog_path)
        if entries is None:
            log_message("Nothing to release", to_console=True)
            return (True, "nothing-to-release")

        log_message(f"\n→ Found {len(entries)} unreleased entries:", to_console=True)
        for entry in entries:
            log_message(f"  {entry}", to_console=True)

        # Analyze with Claude
        analysis = await analyze_unreleased_for_release(
            entries, module_path.name, log_func=log_message
        )

        # Calculate new version
        major, minor, patch = extract_current_version(changelog_path)
        new_version = bump_version(major, minor, patch, analysis["version_bump"])
        old_version = f"v{major}.{minor}.{patch}"

        log_message(f"\n  Current version: {old_version}", to_console=True)
        log_message(f"  Version bump: {analysis['version_bump']}", to_console=True)
        log_message(f"  New version: {new_version}", to_console=True)

        # Show summary and ask for confirmation
        print("\n" + "=" * 60)
        print(f"READY TO RELEASE: {module_path.name}")
        print("=" * 60)
        print(f"Version:        {old_version} → {new_version} ({analysis['version_bump']} bump)")
        print(f"Commit message: Release {new_version}")
        print(f"Git tag:        {new_version}")
        print("\nUnreleased entries:")
        for entry in entries:
            print(f"  {entry}")
        print("=" * 60)

        if config.REQUIRE_CONFIRM:
            if not prompt_yes_no("\nProceed with release?", default_yes=True):
                log_message("\n⚠ Skipped by user", to_console=True)
                return (True, "skipped")

        # Promote unreleased to version
        promote_unreleased_to_version(changelog_path, new_version)
        log_message(f"\n✓ CHANGELOG updated: ## Unreleased → ## {new_version}", to_console=True)

        # Commit
        commit_message = f"Release {new_version}"
        git_commit(module_path, commit_message, log_func=log_message)

        # Tag
        git_tag_from_changelog(module_path, log_func=log_message)

        # Push
        git_push(module_path, log_func=log_message)

        log_message(f"\n✓ Released {new_version} successfully!", to_console=True)
        return (True, "released")

    except Exception as e:
        log_message(f"\n✗ Error processing {module_path}: {e}", to_console=True)
        if config.VERBOSE_MODE:
            traceback.print_exc()
        return (False, "failed")
    finally:
        close_module_logging()
        cleanup_old_logs(module_path)


async def process_release_with_retry(module_path: Path) -> tuple[bool, str]:
    """Process a release module with retry on failure.

    Args:
        module_path: Path to the module

    Returns:
        Tuple of (success: bool, status: str)
    """
    attempt = 1

    while True:
        if attempt > 1:
            print(f"\n=== Retrying {module_path} (attempt {attempt}) ===\n")

        success, status = await process_release_module(module_path)

        if success:
            return True, status

        play_error_sound()
        print(f"\n✗ Release failed for {module_path}")
        print("  → Fix the issues and retry, or skip this module")

        choice = prompt_skip_or_retry()

        if choice == "skip":
            print(f"⚠ Skipping {module_path}\n")
            return False, "skipped"

        attempt += 1


async def main_release_async() -> int:
    """Release-only async workflow.

    Scans CHANGELOG.md for unreleased entries, determines version bump,
    promotes unreleased to versioned section, commits, tags, and pushes.

    Returns:
        Exit code (0 for success, 1 for error)
    """
    parser = argparse.ArgumentParser(
        description="Release unreleased CHANGELOG entries (version bump, commit, tag, push)"
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
        help="Show full command output",
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
        help="Require user confirmation before releasing",
    )

    args = parser.parse_args()

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

    # Resolve module paths
    print("=== Step 1: Discover Modules ===\n")

    module_paths: list[Path] = []
    for path_str in args.modules:
        path = Path(path_str).resolve()
        if not path.exists():
            print(f"✗ Module path does not exist: {path}")
            play_completion_sound()
            return 1

        # Check if this path has a CHANGELOG.md directly
        if (path / "CHANGELOG.md").exists():
            module_paths.append(path)
        else:
            # Discover all modules recursively
            discovered = discover_all_modules(path, recursive=True)
            for mod_list in discovered.values():
                for mod in mod_list:
                    if (mod / "CHANGELOG.md").exists():
                        module_paths.append(mod)

    # Remove duplicates
    module_paths = list(dict.fromkeys(module_paths))

    if not module_paths:
        print("✗ No modules with CHANGELOG.md found")
        play_completion_sound()
        return 1

    print(f"Found {len(module_paths)} module(s) with CHANGELOG.md\n")
    for mod in module_paths:
        print(f"  - {mod}")
    print()

    # Process each module
    results = []
    for i, mod in enumerate(module_paths, 1):
        if len(module_paths) > 1:
            print(f"\n[{i}/{len(module_paths)}] {mod.name}")

        success, status = await process_release_with_retry(mod)
        results.append((mod, success, status))

    # Summary
    if len(module_paths) > 1:
        print("\n" + "=" * 70)
        print(f"SUMMARY: {len(module_paths)} module(s)")
        print("=" * 70)

        released = [mod for mod, _, status in results if status == "released"]
        nothing = [mod for mod, _, status in results if status == "nothing-to-release"]
        skipped = [mod for mod, _, status in results if status == "skipped"]
        failed = [mod for mod, _, status in results if status == "failed"]

        if released:
            print(f"\n✓ Released: {len(released)}")
            for mod in released:
                print(f"  - {mod.name}")
        if nothing:
            print(f"\n✓ Nothing to release: {len(nothing)}")
            for mod in nothing:
                print(f"  - {mod.name}")
        if skipped:
            print(f"\n⚠ Skipped: {len(skipped)}")
            for mod in skipped:
                print(f"  - {mod.name}")
        if failed:
            print(f"\n✗ Failed: {len(failed)}")
            for mod in failed:
                print(f"  - {mod.name}")

        print("\n" + "=" * 70)

    play_completion_sound()
    return 0


def main_release() -> int:
    """Release-only entry point."""
    return asyncio.run(main_release_async())
