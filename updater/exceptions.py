"""Custom exceptions for the updater."""


class UpdateError(Exception):
    """Base exception for update-related errors."""
    pass


class GitError(UpdateError):
    """Git operation failed."""
    pass


class ClaudeError(UpdateError):
    """Claude API or analysis failed."""
    pass


class ChangelogError(UpdateError):
    """CHANGELOG parsing or update failed."""
    pass


class DependencyUpdateError(UpdateError):
    """Dependency update failed."""
    pass
