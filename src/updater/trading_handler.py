"""Infra-tier handler for the bborbe/trading monorepo's Makefile.folder Go version."""

import re
import tempfile
from pathlib import Path

from .changelog import add_to_unreleased
from .git_operations import (
    create_pull_request,
    find_existing_pull_request,
    git_commit,
    git_push,
)
from .infra_tier import (
    InfraTargetError,
    patch_file,
    process_infra_target,
    read_current_value,
    require_clean_worktree,
    validate_go_version,
)
from .log_manager import log_message, run_command

TRADING_REPO = "bborbe/trading"
TRADING_FILE = "Makefile.folder"
TRADING_PATTERN = re.compile(r"^go (\d+\.\d+\.\d+)$")


class TradingHandler:
    """Bump the Go version in bborbe/trading Makefile.folder and open a PR."""

    def run(self, checkout: Path, *, dry_run: bool, go_version: str) -> int:
        """Bump the go X.Y.Z constant in Makefile.folder and open a PR.

        A dry run patches Makefile.folder in the primary checkout and shows the
        diff (no worktree, no make ensurecommit). A real run follows the trading
        monorepo's canonical pattern: feature worktree from master, bump the
        constant, run make ensurecommit (which propagates the version to every
        per-module Makefile/config), commit, push, and open the PR. The
        temporary worktree is always removed afterwards.

        Args:
            checkout: Path to the bborbe/trading checkout
            dry_run: If True, patch the working tree and show the diff only
            go_version: Target Go version to set in Makefile.folder (X.Y.Z)

        Returns:
            Exit code: 0 on success or no-op, 1 on any error
        """
        if not validate_go_version(go_version):
            log_message(f"✗ Invalid Go version: {go_version!r} (expected X.Y.Z)", to_console=True)
            return 1

        branch = f"updater/trading-go-{go_version}"
        title = f"chore: bump Go version to {go_version}"
        body = f"Bump the Go version constant in Makefile.folder to {go_version} and run make ensurecommit."
        changelog_bullet = f"chore: bump Go version to {go_version}"

        if dry_run:
            return process_infra_target(
                checkout,
                repo=TRADING_REPO,
                target_file=TRADING_FILE,
                pattern=TRADING_PATTERN,
                new_value=go_version,
                branch_name=branch,
                title=title,
                body=body,
                changelog_bullet=changelog_bullet,
                dry_run=True,
            )

        try:
            require_clean_worktree(checkout)

            current = read_current_value(checkout, TRADING_FILE, TRADING_PATTERN)
            if current is None:
                log_message(
                    f"pattern not found: {TRADING_PATTERN.pattern} in {TRADING_FILE}",
                    to_console=True,
                )
                return 1
            if current == go_version:
                log_message(f"{TRADING_FILE} already up to date ({go_version})", to_console=True)
                return 0

            existing = find_existing_pull_request(checkout, TRADING_REPO)
            if existing:
                log_message(f"existing updater PR: {existing}", to_console=True)
                return 0

            worktree = Path(tempfile.mkdtemp(prefix=f"{checkout.name}-trading-wt-"))
            run_command(
                f"git worktree add -b {branch} {worktree} master",
                cwd=checkout,
                quiet=True,
                log_func=log_message,
            )
            try:
                patch_file(worktree, TRADING_FILE, TRADING_PATTERN, go_version)
                run_command("make ensurecommit", cwd=worktree, quiet=True, log_func=log_message)
                add_to_unreleased(worktree, {"changelog": [changelog_bullet]}, log_func=log_message)
                git_commit(worktree, title, log_func=log_message)
                git_push(worktree, log_func=log_message)
                pr_url = create_pull_request(
                    worktree, TRADING_REPO, branch, title, body, log_func=log_message
                )
                log_message(f"PR opened: {pr_url}", to_console=True)
                return 0
            finally:
                run_command(
                    f"git worktree remove --force {worktree}",
                    cwd=checkout,
                    quiet=True,
                    log_func=log_message,
                )
        except (InfraTargetError, RuntimeError) as e:
            log_message(f"✗ {e}", to_console=True)
            return 1
