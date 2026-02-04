"""Python dependency updater."""

from collections.abc import Callable
from pathlib import Path

from . import config
from .log_manager import log_message, run_command


def update_python_dependencies(
    module_path: Path, log_func: Callable[..., None] = log_message
) -> bool:
    """Update Python dependencies using uv sync --upgrade.

    Args:
        module_path: Path to Python module
        log_func: Logging function to use

    Returns:
        True if updates were made (uv.lock changed), False otherwise
    """
    pyproject = module_path / "pyproject.toml"
    if not pyproject.exists():
        log_func("✗ No pyproject.toml found", to_console=True)
        return False

    log_func("\n=== Phase 1b: Update Python Dependencies ===", to_console=True)

    # Read uv.lock before update to detect changes
    lockfile = module_path / "uv.lock"
    original_content = ""
    if lockfile.exists():
        original_content = lockfile.read_text()

    # Run uv sync --upgrade
    log_func("→ Running uv sync --upgrade", to_console=config.VERBOSE_MODE)
    run_command(
        "uv sync --upgrade",
        cwd=module_path,
        quiet=True,
        log_func=log_func,
    )

    # Check if lockfile changed
    new_content = ""
    if lockfile.exists():
        new_content = lockfile.read_text()

    if new_content != original_content:
        log_func("\n✓ Python dependencies updated", to_console=True)
        return True

    log_func("\n✓ Python dependencies are up to date", to_console=True)
    return False


def run_precommit(module_path: Path, log_func: Callable[..., None] = log_message) -> None:
    """Run make precommit.

    Args:
        module_path: Path to Python module
        log_func: Logging function to use
    """
    log_func("\n=== Phase 2: Run Precommit ===", to_console=True)

    log_func("→ Running make precommit", to_console=config.VERBOSE_MODE)
    run_command("make precommit", cwd=module_path, quiet=True, log_func=log_func)

    log_func("✓ Precommit completed successfully", to_console=True)
