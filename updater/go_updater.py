"""Go dependency updater."""

from pathlib import Path
from typing import Callable

from . import config
from .log_manager import log_message, run_command


def update_go_dependencies(module_path: Path, log_func: Callable = log_message) -> bool:
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
        log_func(f"\n→ Iteration {iteration}/{max_iterations}", to_console=config.VERBOSE_MODE)

        # Check for available updates
        result = run_command(
            "go list -mod=mod -m -u -f '{{if not (or .Main .Indirect)}}{{.Path}}{{end}}' all",
            cwd=module_path,
            capture_output=True,
            quiet=True,
            log_func=log_func
        )

        outdated_modules = [line for line in result.stdout.strip().split('\n') if line]

        if not outdated_modules:
            log_func("✓ All dependencies are up to date", to_console=config.VERBOSE_MODE)
            break

        log_func(f"  Found {len(outdated_modules)} modules to update", to_console=config.VERBOSE_MODE)

        # Update modules that have updates available
        updates_made = False
        for module in outdated_modules:
            # Check if update is available
            check_result = run_command(
                f"go list -mod=mod -m -u {module}",
                cwd=module_path,
                capture_output=True,
                quiet=True,
                log_func=log_func
            )

            if '[' in check_result.stdout:  # Has update available
                log_func(f"  → Updating {module}", to_console=config.VERBOSE_MODE)
                run_command(f"go get {module}@latest", cwd=module_path, quiet=True, log_func=log_func)
                updates_made = True
                any_updates_made = True

        if not updates_made:
            log_func("✓ No more updates available", to_console=config.VERBOSE_MODE)
            break

    if not any_updates_made:
        log_func("\n✓ No dependency updates needed", to_console=True)
        return False

    # Run go mod tidy and vendor
    log_func("\n→ Running go mod tidy", to_console=config.VERBOSE_MODE)
    run_command("go mod tidy", cwd=module_path, quiet=True, log_func=log_func)

    log_func("→ Running go mod vendor", to_console=config.VERBOSE_MODE)
    run_command("go mod vendor", cwd=module_path, quiet=True, log_func=log_func)

    log_func("\n✓ Go dependencies updated successfully", to_console=True)
    return True


def run_precommit(module_path: Path, log_func: Callable = log_message) -> None:
    """Run make precommit.

    Args:
        module_path: Path to Go module
        log_func: Logging function to use
    """
    log_func("\n=== Phase 2: Run Precommit ===", to_console=True)

    log_func("→ Running make precommit", to_console=config.VERBOSE_MODE)
    run_command("make precommit", cwd=module_path, quiet=True, log_func=log_func)

    log_func("✓ Precommit completed successfully", to_console=True)
