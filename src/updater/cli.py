"""CLI orchestration and workflow."""

import argparse
import asyncio
import traceback
from datetime import datetime
from pathlib import Path

from . import config
from .claude_analyzer import verify_claude_auth
from .docker_updater import update_dockerfile_images
from .file_utils import condense_file_list
from .git_operations import (
    check_git_status,
    ensure_gitignore_entry,
    find_git_repo,
    update_git_branch,
)
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
from .sound import play_completion_sound, play_error_sound


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
    Delegates to a composable pipeline of steps.

    Args:
        module_path: Path to the module
        update_deps: Whether to update dependencies (default: True)

    Returns:
        Tuple of (success: bool, status: str)
        status can be: 'updated', 'up-to-date', 'skipped', 'failed'
    """
    from .pipeline import (
        ChangelogStep,
        CheckChangesStep,
        GitCommitStep,
        GitConfirmStep,
        GoDepSkipStep,
        GoDepUpdateStep,
        GoExcludesStep,
        GoVersionUpdateStep,
        Pipeline,
        PrecommitStep,
        StepStatus,
    )

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

        # Build pipeline
        dep_step = GoDepUpdateStep() if update_deps else GoDepSkipStep()
        pipeline = Pipeline(
            [
                GoVersionUpdateStep(),
                GoExcludesStep(),
                dep_step,
                CheckChangesStep(phase="update"),
                PrecommitStep(project_type="go"),
                CheckChangesStep(phase="precommit"),
                ChangelogStep(),
                GitConfirmStep(),
                GitCommitStep(),
            ]
        )

        result = await pipeline.run(module_path)

        if result.status == StepStatus.UP_TO_DATE:
            return (True, "up-to-date")
        if result.status == StepStatus.SKIP:
            return (True, "skipped")
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
    Delegates to a composable pipeline of steps.

    Args:
        module_path: Path to the module

    Returns:
        Tuple of (success: bool, status: str)
        status can be: 'updated', 'up-to-date', 'skipped', 'failed'
    """
    from .pipeline import (
        ChangelogStep,
        CheckChangesStep,
        GitCommitStep,
        GitConfirmStep,
        Pipeline,
        PrecommitStep,
        PythonDepUpdateStep,
        PythonVersionUpdateStep,
        StepStatus,
    )

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

        # Build pipeline
        pipeline = Pipeline(
            [
                PythonVersionUpdateStep(),
                PythonDepUpdateStep(),
                CheckChangesStep(phase="update"),
                PrecommitStep(project_type="python"),
                CheckChangesStep(phase="precommit"),
                ChangelogStep(),
                GitConfirmStep(),
                GitCommitStep(),
            ]
        )

        result = await pipeline.run(module_path)

        if result.status == StepStatus.UP_TO_DATE:
            return (True, "up-to-date")
        if result.status == StepStatus.SKIP:
            return (True, "skipped")
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
            from .pipeline import DockerCommitStep, DockerUpdateStep, Pipeline, StepStatus

            log_message(f"\n{'=' * 70}", to_console=True)
            log_message(f"Docker Project: {module_path.name}", to_console=True)
            log_message("=" * 70, to_console=True)

            pipeline = Pipeline([DockerUpdateStep(), DockerCommitStep()])
            result = await pipeline.run(module_path)

            if result.status == StepStatus.UP_TO_DATE:
                log_message("\n✓ Dockerfile already up to date", to_console=True)
                success, status = True, "up-to-date"
            else:
                success, status = True, "updated"
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
    Delegates to a composable pipeline of steps.

    Args:
        module_path: Path to the module

    Returns:
        Tuple of (success: bool, status: str)
        status can be: 'released', 'nothing-to-release', 'skipped', 'failed'
    """
    from .pipeline import (
        GitCommitStep,
        GitPushStep,
        Pipeline,
        ReleaseStep,
        StepStatus,
    )

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

        # Build pipeline: Release → Commit → Push
        pipeline = Pipeline(
            [
                ReleaseStep(),
                GitCommitStep(),
                GitPushStep(),
            ]
        )

        context: dict = {}
        result = await pipeline.run(module_path, context)

        if result.status == StepStatus.UP_TO_DATE:
            return (True, "nothing-to-release")
        if result.status == StepStatus.SKIP:
            return (True, "skipped")

        new_version = context.get("new_version", "unknown")
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
