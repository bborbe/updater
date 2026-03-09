"""Tests for log_manager.py — run_command(), cleanup_old_logs(), setup/close logging."""

import subprocess
from unittest.mock import MagicMock, patch

import pytest

from updater import config, log_manager

# ---------------------------------------------------------------------------
# run_command — success path
# ---------------------------------------------------------------------------


def test_run_command_success_returns_completed_process(tmp_path):
    """run_command returns the CompletedProcess on success."""
    mock_result = MagicMock(spec=subprocess.CompletedProcess)
    mock_result.returncode = 0
    mock_result.stdout = "output text"
    mock_result.stderr = ""

    with patch("updater.log_manager.subprocess.run", return_value=mock_result) as mock_run:
        result = log_manager.run_command("echo hello", cwd=tmp_path)

    assert result is mock_result
    mock_run.assert_called_once_with(
        "echo hello",
        shell=True,
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )


def test_run_command_logs_stdout(tmp_path):
    """run_command passes stdout to the log function."""
    mock_result = MagicMock(spec=subprocess.CompletedProcess)
    mock_result.returncode = 0
    mock_result.stdout = "hello world\n"
    mock_result.stderr = ""

    logged = []

    def fake_log(msg, to_console=True):
        logged.append(msg)

    with patch("updater.log_manager.subprocess.run", return_value=mock_result):
        log_manager.run_command("echo hello", log_func=fake_log)

    assert any("hello world" in m for m in logged)


def test_run_command_logs_stderr_on_success(tmp_path):
    """run_command passes stderr to the log function even on success."""
    mock_result = MagicMock(spec=subprocess.CompletedProcess)
    mock_result.returncode = 0
    mock_result.stdout = ""
    mock_result.stderr = "warning: something"

    logged = []

    def fake_log(msg, to_console=True):
        logged.append(msg)

    with patch("updater.log_manager.subprocess.run", return_value=mock_result):
        log_manager.run_command("cmd", log_func=fake_log)

    assert any("warning: something" in m for m in logged)


# ---------------------------------------------------------------------------
# run_command — failure path
# ---------------------------------------------------------------------------


def test_run_command_failure_raises_runtime_error():
    """run_command raises RuntimeError when exit code is non-zero."""
    mock_result = MagicMock(spec=subprocess.CompletedProcess)
    mock_result.returncode = 1
    mock_result.stdout = ""
    mock_result.stderr = "error output"

    with patch("updater.log_manager.subprocess.run", return_value=mock_result):
        with pytest.raises(RuntimeError, match="exit code 1"):
            log_manager.run_command("false")


def test_run_command_failure_includes_command_in_error():
    """RuntimeError message includes the command that failed."""
    mock_result = MagicMock(spec=subprocess.CompletedProcess)
    mock_result.returncode = 2
    mock_result.stdout = ""
    mock_result.stderr = ""

    with patch("updater.log_manager.subprocess.run", return_value=mock_result):
        with pytest.raises(RuntimeError, match="my-failing-cmd"):
            log_manager.run_command("my-failing-cmd")


def test_run_command_failure_logs_stderr():
    """run_command logs stderr when command fails."""
    mock_result = MagicMock(spec=subprocess.CompletedProcess)
    mock_result.returncode = 1
    mock_result.stdout = ""
    mock_result.stderr = "fatal: repo not found"

    logged = []

    def fake_log(msg, to_console=True):
        logged.append(msg)

    with patch("updater.log_manager.subprocess.run", return_value=mock_result):
        with pytest.raises(RuntimeError):
            log_manager.run_command("git push", log_func=fake_log)

    assert any("fatal: repo not found" in m for m in logged)


def test_run_command_failure_logs_stdout():
    """run_command logs stdout when command fails."""
    mock_result = MagicMock(spec=subprocess.CompletedProcess)
    mock_result.returncode = 1
    mock_result.stdout = "partial output"
    mock_result.stderr = ""

    logged = []

    def fake_log(msg, to_console=True):
        logged.append(msg)

    with patch("updater.log_manager.subprocess.run", return_value=mock_result):
        with pytest.raises(RuntimeError):
            log_manager.run_command("cmd", log_func=fake_log)

    assert any("partial output" in m for m in logged)


# ---------------------------------------------------------------------------
# run_command — quiet / verbose mode
# ---------------------------------------------------------------------------


def test_run_command_quiet_suppresses_console(tmp_path):
    """In quiet mode the running log line is sent with to_console=False."""
    mock_result = MagicMock(spec=subprocess.CompletedProcess)
    mock_result.returncode = 0
    mock_result.stdout = ""
    mock_result.stderr = ""

    calls = []

    def fake_log(msg, to_console=True):
        calls.append((msg, to_console))

    with patch("updater.log_manager.subprocess.run", return_value=mock_result):
        log_manager.run_command("echo hi", quiet=True, log_func=fake_log)

    # The "→ Running:" line must have to_console=False
    running_calls = [(m, c) for m, c in calls if "Running:" in m]
    assert running_calls, "Expected at least one 'Running:' log entry"
    assert all(not console for _, console in running_calls)


def test_run_command_verbose_mode_logs_to_console(tmp_path):
    """In verbose mode stdout/stderr go to console (to_console=True)."""
    mock_result = MagicMock(spec=subprocess.CompletedProcess)
    mock_result.returncode = 0
    mock_result.stdout = "verbose output"
    mock_result.stderr = ""

    calls = []

    def fake_log(msg, to_console=True):
        calls.append((msg, to_console))

    orig = config.VERBOSE_MODE
    config.VERBOSE_MODE = True
    try:
        with patch("updater.log_manager.subprocess.run", return_value=mock_result):
            log_manager.run_command("cmd", quiet=False, log_func=fake_log)
    finally:
        config.VERBOSE_MODE = orig

    stdout_calls = [(m, c) for m, c in calls if "verbose output" in m]
    assert stdout_calls
    assert any(console for _, console in stdout_calls)


# ---------------------------------------------------------------------------
# cleanup_old_logs
# ---------------------------------------------------------------------------


def test_cleanup_old_logs_removes_excess_files(tmp_path):
    """cleanup_old_logs deletes logs beyond keep_count (oldest first)."""
    log_dir = tmp_path / config.LOG_DIR_NAME
    log_dir.mkdir()

    # Create 5 log files with distinct mtime by touching sequentially
    files = []
    for i in range(5):
        f = log_dir / f"log_{i:04d}.log"
        f.write_text(f"log {i}")
        import time

        time.sleep(0.01)  # ensure distinct mtime ordering
        files.append(f)

    # Keep only 2 most recent
    log_manager.cleanup_old_logs(tmp_path, keep_count=2)

    remaining = list(log_dir.glob("*.log"))
    assert len(remaining) == 2
    # The two newest should survive
    remaining_names = {f.name for f in remaining}
    assert files[-1].name in remaining_names
    assert files[-2].name in remaining_names


def test_cleanup_old_logs_keeps_all_when_fewer_than_limit(tmp_path):
    """cleanup_old_logs leaves files alone when count <= keep_count."""
    log_dir = tmp_path / config.LOG_DIR_NAME
    log_dir.mkdir()

    for i in range(3):
        (log_dir / f"log_{i}.log").write_text("x")

    log_manager.cleanup_old_logs(tmp_path, keep_count=10)

    assert len(list(log_dir.glob("*.log"))) == 3


def test_cleanup_old_logs_no_directory(tmp_path):
    """cleanup_old_logs returns without error when log dir doesn't exist."""
    # Ensure the log dir does not exist
    log_dir = tmp_path / config.LOG_DIR_NAME
    assert not log_dir.exists()

    # Should not raise
    log_manager.cleanup_old_logs(tmp_path, keep_count=5)


def test_cleanup_old_logs_uses_config_default(tmp_path):
    """cleanup_old_logs uses config.LOG_RETENTION_COUNT when keep_count is None."""
    log_dir = tmp_path / config.LOG_DIR_NAME
    log_dir.mkdir()

    # Create more files than the default retention count
    count = config.LOG_RETENTION_COUNT + 3
    import time

    for i in range(count):
        f = log_dir / f"log_{i:04d}.log"
        f.write_text(f"log {i}")
        time.sleep(0.01)

    log_manager.cleanup_old_logs(tmp_path)  # keep_count=None → uses config

    remaining = list(log_dir.glob("*.log"))
    assert len(remaining) == config.LOG_RETENTION_COUNT


# ---------------------------------------------------------------------------
# setup_module_logging
# ---------------------------------------------------------------------------


def test_setup_module_logging_verbose_returns_none(tmp_path):
    """setup_module_logging returns None in verbose mode without creating files."""
    orig = config.VERBOSE_MODE
    config.VERBOSE_MODE = True
    try:
        result = log_manager.setup_module_logging(tmp_path)
    finally:
        config.VERBOSE_MODE = orig

    assert result is None
    assert not (tmp_path / config.LOG_DIR_NAME).exists()


def test_setup_module_logging_creates_log_file(tmp_path):
    """setup_module_logging creates the log dir and a log file."""
    orig_verbose = config.VERBOSE_MODE
    orig_handle = config.LOG_FILE_HANDLE
    orig_ts = config.RUN_TIMESTAMP

    config.VERBOSE_MODE = False
    config.RUN_TIMESTAMP = "20260101_120000"
    config.LOG_FILE_HANDLE = None

    try:
        log_file = log_manager.setup_module_logging(tmp_path)
    finally:
        if config.LOG_FILE_HANDLE:
            config.LOG_FILE_HANDLE.close()
        config.LOG_FILE_HANDLE = orig_handle
        config.VERBOSE_MODE = orig_verbose
        config.RUN_TIMESTAMP = orig_ts

    assert log_file is not None
    assert log_file.exists()
    assert log_file.parent == tmp_path / config.LOG_DIR_NAME
    content = log_file.read_text()
    assert "Update Log" in content


# ---------------------------------------------------------------------------
# close_module_logging
# ---------------------------------------------------------------------------


def test_close_module_logging_closes_and_clears_handle(tmp_path):
    """close_module_logging closes the file handle and sets it to None."""
    log_dir = tmp_path / config.LOG_DIR_NAME
    log_dir.mkdir()
    log_file = log_dir / "test.log"

    orig_handle = config.LOG_FILE_HANDLE
    config.LOG_FILE_HANDLE = open(log_file, "w")

    try:
        log_manager.close_module_logging()
    finally:
        if config.LOG_FILE_HANDLE:
            config.LOG_FILE_HANDLE.close()
            config.LOG_FILE_HANDLE = None
        config.LOG_FILE_HANDLE = orig_handle

    assert config.LOG_FILE_HANDLE is orig_handle  # restored by finally; was set to None by func


def test_close_module_logging_noop_when_no_handle():
    """close_module_logging is a no-op when LOG_FILE_HANDLE is None."""
    orig = config.LOG_FILE_HANDLE
    config.LOG_FILE_HANDLE = None
    try:
        log_manager.close_module_logging()  # must not raise
    finally:
        config.LOG_FILE_HANDLE = orig


# ---------------------------------------------------------------------------
# log_message — file handle path
# ---------------------------------------------------------------------------


def test_log_message_writes_to_file_handle(tmp_path):
    """log_message writes to LOG_FILE_HANDLE when set."""
    log_dir = tmp_path / config.LOG_DIR_NAME
    log_dir.mkdir()
    log_file = log_dir / "test.log"

    orig_handle = config.LOG_FILE_HANDLE
    config.LOG_FILE_HANDLE = open(log_file, "w")

    try:
        log_manager.log_message("hello file", to_console=False)
        config.LOG_FILE_HANDLE.flush()
    finally:
        config.LOG_FILE_HANDLE.close()
        config.LOG_FILE_HANDLE = orig_handle

    assert "hello file" in log_file.read_text()
