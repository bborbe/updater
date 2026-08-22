"""Shared machinery for the infra-tier special-case target handlers.

The four infra-tier files the generic updater cannot touch (claude-yolo's
Dockerfile, dark-factory's pkg/const.go, BundleWrap's golang items, and the
trading monorepo's Makefile.folder) each have a unique file + constant + repo.
This module provides the shared clean-check → read constant → patch → diff →
branch → commit → push → PR flow so each handler (in ``claude_yolo_handler.py``
and its siblings) only needs to supply its target constants, validation, and
delegation.
"""

import re
from pathlib import Path

from .changelog import add_to_unreleased
from .git_operations import (
    check_git_status,
    create_pull_request,
    find_existing_pull_request,
    git_checkout_new_branch,
    git_commit,
    git_push,
)
from .log_manager import log_message, run_command

GO_VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")
CLAUDE_YOLO_TAG_RE = re.compile(r"^v\d+\.\d+\.\d+$")


class InfraTargetError(Exception):
    """Raised when an infra-tier handler cannot proceed."""


def validate_go_version(value: str) -> bool:
    """Return whether value is a well-formed X.Y.Z Go version.

    Args:
        value: Candidate Go version string

    Returns:
        True if value matches X.Y.Z (e.g. "1.28.0"), False otherwise
    """
    return bool(GO_VERSION_RE.match(value))


def validate_claude_yolo_tag(value: str) -> bool:
    """Return whether value is a well-formed vX.Y.Z claude-yolo release tag.

    Args:
        value: Candidate release tag string

    Returns:
        True if value matches vX.Y.Z (e.g. "v0.16.0"), False otherwise
    """
    return bool(CLAUDE_YOLO_TAG_RE.match(value))


def require_clean_worktree(checkout: Path) -> None:
    """Raise InfraTargetError unless checkout is a clean git repository.

    Args:
        checkout: Path to the target checkout

    Raises:
        InfraTargetError: If checkout is not a git repository or has
            uncommitted changes
    """
    count, _ = check_git_status(checkout)
    if count == -1:
        raise InfraTargetError(f"not a git repository: {checkout}")
    if count > 0:
        raise InfraTargetError(f"uncommitted changes in {checkout}; stash or commit and re-run")


def read_current_value(checkout: Path, target_file: str, pattern: re.Pattern[str]) -> str | None:
    """Return the currently matched value in target_file, or None.

    Args:
        checkout: Path to the target checkout
        target_file: Name of the file holding the constant
        pattern: Regex whose group 1 captures the constant's value

    Returns:
        The captured value, or None if the file is missing or the pattern
        does not match
    """
    file_path = checkout / target_file
    if not file_path.exists():
        return None

    match = pattern.search(file_path.read_text())
    return match.group(1) if match else None


def require_current_value(checkout: Path, target_file: str, pattern: re.Pattern[str]) -> str:
    """Return the currently matched value, raising if file or pattern is missing.

    Args:
        checkout: Path to the target checkout
        target_file: Name of the file holding the constant
        pattern: Regex whose group 1 captures the constant's value

    Returns:
        The captured value

    Raises:
        InfraTargetError: If the target file is missing or the pattern does
            not match any line in it
    """
    file_path = checkout / target_file
    if not file_path.exists():
        raise InfraTargetError(f"target file not found: {target_file}")

    match = pattern.search(file_path.read_text())
    if not match:
        raise InfraTargetError(f"pattern not found: {pattern.pattern} in {target_file}")
    return match.group(1)


def patch_file(checkout: Path, target_file: str, pattern: re.Pattern[str], new_value: str) -> bool:
    """Replace the matched constant's value with new_value in target_file.

    Preserves the constant's surrounding text (e.g. ``ARG GO_VERSION=1.27.0``
    → ``ARG GO_VERSION=1.28.0``).

    Args:
        checkout: Path to the target checkout
        target_file: Name of the file holding the constant
        pattern: Regex whose group 1 captures the value to replace
        new_value: Replacement value

    Returns:
        True if the file content changed, False otherwise
    """
    file_path = checkout / target_file
    content = file_path.read_text()
    new_content = re.sub(pattern, lambda m: m.group(0).replace(m.group(1), new_value, 1), content)
    if new_content != content:
        file_path.write_text(new_content)
        return True
    return False


def process_infra_target(
    checkout: Path,
    *,
    repo: str,
    target_file: str,
    pattern: re.Pattern[str],
    new_value: str,
    branch_name: str,
    title: str,
    body: str,
    changelog_bullet: str,
    dry_run: bool,
) -> int:
    """Patch an infra-tier target constant and optionally open a PR.

    The flow is: clean-worktree check → read current value → idempotency check
    → (real run) existing-PR lookup → (real run) feature branch → patch →
    (real run) changelog bullet → print diff → (real run) commit, push, PR.

    Args:
        checkout: Path to the target checkout
        repo: GitHub repository in owner/name form
        target_file: Name of the file holding the constant
        pattern: Regex whose group 1 captures the value to replace
        new_value: Replacement value
        branch_name: Feature branch name
        title: PR title / commit message
        body: PR body
        changelog_bullet: ## Unreleased bullet for the real run
        dry_run: If True, patch the working tree and show the diff only

    Returns:
        Exit code: 0 on success or no-op, 1 on any error
    """
    try:
        require_clean_worktree(checkout)
    except InfraTargetError as e:
        log_message(f"✗ {e}", to_console=True)
        return 1

    try:
        current = require_current_value(checkout, target_file, pattern)
    except InfraTargetError as e:
        log_message(f"✗ {e}", to_console=True)
        return 1

    if current == new_value:
        log_message(f"{target_file} already up to date ({new_value})", to_console=True)
        return 0

    try:
        if not dry_run:
            existing = find_existing_pull_request(checkout, repo)
            if existing:
                log_message(f"existing updater PR: {existing}", to_console=True)
                return 0
            git_checkout_new_branch(checkout, branch_name)

        patch_file(checkout, target_file, pattern, new_value)
        log_message(f"Patched {target_file}: {current} → {new_value}", to_console=True)

        if not dry_run:
            add_to_unreleased(checkout, {"changelog": [changelog_bullet]}, log_func=log_message)

        result = run_command(
            "git diff --name-only",
            cwd=checkout,
            capture_output=True,
            quiet=True,
            log_func=log_message,
        )
        log_message(f"Changed files:\n{result.stdout.strip()}", to_console=True)

        if dry_run:
            log_message("(dry-run — no branch or PR opened)", to_console=True)
            return 0

        git_commit(checkout, title, log_func=log_message)
        git_push(checkout, log_func=log_message)
        pr_url = create_pull_request(checkout, repo, branch_name, title, body, log_func=log_message)
        log_message(f"PR opened: {pr_url}", to_console=True)
        return 0
    except (InfraTargetError, RuntimeError) as e:
        log_message(f"✗ {e}", to_console=True)
        return 1
