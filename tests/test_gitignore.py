"""Tests for .gitignore management."""

from updater.git_operations import ensure_gitignore_entry


def mock_log_func(message, to_console=True):
    """Mock logging function for tests."""
    pass


def test_ensure_gitignore_entry_creates_new(tmp_path):
    """Test ensure_gitignore_entry creates .gitignore if it doesn't exist."""
    ensure_gitignore_entry(tmp_path, log_func=mock_log_func)

    gitignore_path = tmp_path / ".gitignore"
    assert gitignore_path.exists()

    content = gitignore_path.read_text()
    assert "/.update-logs/" in content
    assert "/.claude/" in content
    assert "/CLAUDE.md" in content
    assert "/.mcp-*" in content


def test_ensure_gitignore_entry_appends_to_existing(tmp_path):
    """Test ensure_gitignore_entry appends to existing .gitignore."""
    gitignore_path = tmp_path / ".gitignore"
    gitignore_path.write_text("*.pyc\n__pycache__/\n")

    ensure_gitignore_entry(tmp_path, log_func=mock_log_func)

    content = gitignore_path.read_text()
    assert "*.pyc" in content
    assert "__pycache__/" in content
    assert "/.update-logs/" in content
    assert "/.claude/" in content
    assert "/CLAUDE.md" in content
    assert "/.mcp-*" in content


def test_ensure_gitignore_entry_idempotent(tmp_path):
    """Test ensure_gitignore_entry doesn't duplicate entries."""
    gitignore_path = tmp_path / ".gitignore"
    gitignore_path.write_text("/.update-logs/\n/.claude/\n/CLAUDE.md\n/.mcp-*\n")

    # Call twice
    ensure_gitignore_entry(tmp_path, log_func=mock_log_func)
    ensure_gitignore_entry(tmp_path, log_func=mock_log_func)

    content = gitignore_path.read_text()
    # Should only have one of each entry
    assert content.count("/.update-logs/") == 1
    assert content.count("/.claude/") == 1
    assert content.count("/CLAUDE.md") == 1
    assert content.count("/.mcp-*") == 1


def test_ensure_gitignore_entry_handles_no_trailing_slash(tmp_path):
    """Test ensure_gitignore_entry recognizes entry without trailing slash."""
    gitignore_path = tmp_path / ".gitignore"
    gitignore_path.write_text("/.update-logs\n")

    # Should not add duplicate
    ensure_gitignore_entry(tmp_path, log_func=mock_log_func)

    content = gitignore_path.read_text()
    lines = content.strip().split("\n")
    # Should have 4 lines (/.update-logs recognized, /.claude, /CLAUDE.md, and /.mcp-* added)
    assert len(lines) == 4


def test_ensure_gitignore_entry_trailing_newline(tmp_path):
    """Test ensure_gitignore_entry adds trailing newline."""
    ensure_gitignore_entry(tmp_path, log_func=mock_log_func)

    gitignore_path = tmp_path / ".gitignore"
    content = gitignore_path.read_text()

    # Should end with newline
    assert content.endswith("\n")


def test_ensure_gitignore_entry_partial_existing(tmp_path):
    """Test ensure_gitignore_entry adds missing entries when some exist."""
    gitignore_path = tmp_path / ".gitignore"
    # Only /.update-logs/ exists
    gitignore_path.write_text("/.update-logs/\n")

    ensure_gitignore_entry(tmp_path, log_func=mock_log_func)

    content = gitignore_path.read_text()
    # Should have all four entries now
    assert "/.update-logs/" in content
    assert "/.claude/" in content
    assert "/CLAUDE.md" in content
    assert "/.mcp-*" in content
    # /.update-logs/ should only appear once
    assert content.count("/.update-logs/") == 1
