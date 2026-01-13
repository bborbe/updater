"""Logging setup, management, and cleanup."""

import subprocess
from pathlib import Path
from typing import Callable, Optional

from . import config


def setup_module_logging(module_path: Path) -> Optional[Path]:
    """Setup logging for a module. Returns log file path.

    Args:
        module_path: Path to the module

    Returns:
        Path to log file, or None if in verbose mode
    """
    if config.VERBOSE_MODE:
        return None

    # Create .update-logs directory
    log_dir = Path(module_path) / config.LOG_DIR_NAME
    log_dir.mkdir(exist_ok=True)

    # Create log file with timestamp
    log_file = log_dir / f"{config.RUN_TIMESTAMP}.log"
    config.LOG_FILE_HANDLE = open(log_file, "w")

    # Write header
    config.LOG_FILE_HANDLE.write(f"Update Log - {config.RUN_TIMESTAMP}\n")
    config.LOG_FILE_HANDLE.write(f"Module: {module_path}\n")
    config.LOG_FILE_HANDLE.write("=" * 70 + "\n\n")
    config.LOG_FILE_HANDLE.flush()

    return log_file


def close_module_logging() -> None:
    """Close the current log file."""
    if config.LOG_FILE_HANDLE:
        config.LOG_FILE_HANDLE.close()
        config.LOG_FILE_HANDLE = None


def cleanup_old_logs(module_path: Path, keep_count: Optional[int] = None) -> None:
    """Keep only the most recent N log files per module.

    Args:
        module_path: Path to the module
        keep_count: Number of logs to keep (default: from config)
    """
    if keep_count is None:
        keep_count = config.LOG_RETENTION_COUNT

    log_dir = Path(module_path) / config.LOG_DIR_NAME

    if not log_dir.exists():
        return

    # Get all log files sorted by modification time (newest first)
    log_files = sorted(
        log_dir.glob("*.log"), key=lambda f: f.stat().st_mtime, reverse=True
    )

    # Remove old logs (keep only keep_count most recent)
    for old_log in log_files[keep_count:]:
        old_log.unlink()


def log_message(message: str, to_console: bool = True) -> None:
    """Write message to log file and optionally to console.

    Args:
        message: Message to log
        to_console: Whether to also print to console
    """
    if config.LOG_FILE_HANDLE:
        config.LOG_FILE_HANDLE.write(message + "\n")
        config.LOG_FILE_HANDLE.flush()

    if to_console or config.VERBOSE_MODE:
        print(message)


def run_command(
    cmd: str,
    cwd: Optional[Path] = None,
    capture_output: bool = False,
    quiet: bool = False,
    log_func: Callable = log_message,
) -> subprocess.CompletedProcess:
    """Execute shell command and return result.

    Args:
        cmd: Command to execute
        cwd: Working directory
        capture_output: Capture stdout/stderr (deprecated, always True now)
        quiet: If True and not in verbose mode, only log to file
        log_func: Logging function to use

    Returns:
        CompletedProcess result

    Raises:
        RuntimeError: If command fails
    """
    log_func(f"→ Running: {cmd}", to_console=not quiet)

    result = subprocess.run(
        cmd,
        shell=True,
        cwd=cwd,
        capture_output=True,  # Always capture for logging
        text=True,
    )

    # Log output
    if result.stdout:
        log_func(result.stdout, to_console=config.VERBOSE_MODE and not quiet)
    if result.stderr:
        log_func(result.stderr, to_console=config.VERBOSE_MODE and not quiet)

    if result.returncode != 0:
        log_func(
            f"✗ Command failed with exit code {result.returncode}", to_console=True
        )
        if result.stdout:
            log_func(f"  stdout: {result.stdout}", to_console=True)
        if result.stderr:
            log_func(f"  stderr: {result.stderr}", to_console=True)
        raise RuntimeError(f"Command failed: {cmd} (exit code {result.returncode})")

    return result
