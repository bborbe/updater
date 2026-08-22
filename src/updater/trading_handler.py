"""Infra-tier handler for the bborbe/trading monorepo Go version.

Unlike the other infra-tier handlers, trading has no single version constant:
its canonical mechanism (`make updategoversion` → `update-go-version.sh`, see
`~/Documents/workspaces/scripts/update-go-version.sh`) walks every module and
patches go.mod `go`/`toolchain` directives, Dockerfile `FROM golang:` images,
and GitHub workflow `go-version:` pins to the latest Go release. This handler
replicates exactly those sed patterns, driven by an explicit `--go-version`
target instead of a runtime fetch from go.dev.
"""

import re
import tempfile
from pathlib import Path

from .git_operations import (
    create_pull_request,
    find_existing_pull_request,
    git_commit,
    git_push,
)
from .infra_tier import (
    InfraTargetError,
    require_clean_worktree,
    validate_go_version,
)
from .log_manager import log_message, run_command

TRADING_REPO = "bborbe/trading"

# Patterns mirrored from update-go-version.sh. sed anchors `^` per line, so the
# Python regexes need re.MULTILINE to match line starts the same way.
GO_DIRECTIVE_RE = re.compile(r"^go \d+\.\d+(\.\d+)?", re.MULTILINE)
TOOLCHAIN_DIRECTIVE_RE = re.compile(r"^toolchain go\d+\.\d+(\.\d+)?", re.MULTILINE)
DOCKERFILE_FROM_RE = re.compile(r"(FROM golang:)\d+\.\d+(\.\d+)?")
WORKFLOW_GO_VERSION_RE = re.compile(r"go-version: ['\"]\d+\.\d+(\.\d+)?['\"]")


def _iter_files(root: Path, name: str) -> list[Path]:
    """Return all files named ``name`` under root, excluding vendor/ subtrees."""
    return [p for p in root.rglob(name) if "vendor" not in p.parts]


def apply_version_updates(root: Path, go_version: str) -> int:
    """Apply update-go-version.sh's patterns with go_version; return files changed.

    Args:
        root: Repository root to walk
        go_version: Target Go version (X.Y.Z)

    Returns:
        Number of files whose content changed
    """
    changed = 0

    for gomod in _iter_files(root, "go.mod"):
        text = gomod.read_text()
        new_text = GO_DIRECTIVE_RE.sub(lambda m: f"go {go_version}", text)
        new_text = TOOLCHAIN_DIRECTIVE_RE.sub(lambda m: f"toolchain go{go_version}", new_text)
        if new_text != text:
            gomod.write_text(new_text)
            changed += 1

    for dockerfile in _iter_files(root, "Dockerfile"):
        text = dockerfile.read_text()
        new_text = DOCKERFILE_FROM_RE.sub(lambda m: f"{m.group(1)}{go_version}", text)
        if new_text != text:
            dockerfile.write_text(new_text)
            changed += 1

    workflows_dir = root / ".github" / "workflows"
    if workflows_dir.is_dir():
        for workflow in workflows_dir.glob("*.yml"):
            text = workflow.read_text()
            new_text = WORKFLOW_GO_VERSION_RE.sub(lambda m: f"go-version: '{go_version}'", text)
            if new_text != text:
                workflow.write_text(new_text)
                changed += 1

    return changed


def would_change(root: Path, go_version: str) -> bool:
    """Return whether the walk would change any file, without writing.

    Read-only pre-scan so a real run can bail out (already current) before
    creating a feature worktree.

    Args:
        root: Repository root to walk
        go_version: Target Go version (X.Y.Z)

    Returns:
        True if any go.mod/Dockerfile/workflow reference a different version
    """
    for gomod in _iter_files(root, "go.mod"):
        text = gomod.read_text()
        new_text = GO_DIRECTIVE_RE.sub(lambda m: f"go {go_version}", text)
        new_text = TOOLCHAIN_DIRECTIVE_RE.sub(lambda m: f"toolchain go{go_version}", new_text)
        if new_text != text:
            return True

    for dockerfile in _iter_files(root, "Dockerfile"):
        text = dockerfile.read_text()
        new_text = DOCKERFILE_FROM_RE.sub(lambda m: f"{m.group(1)}{go_version}", text)
        if new_text != text:
            return True

    workflows_dir = root / ".github" / "workflows"
    if workflows_dir.is_dir():
        for workflow in workflows_dir.glob("*.yml"):
            text = workflow.read_text()
            new_text = WORKFLOW_GO_VERSION_RE.sub(lambda m: f"go-version: '{go_version}'", text)
            if new_text != text:
                return True

    return False


class TradingHandler:
    """Bump the Go version across the trading monorepo and open a PR."""

    def run(self, checkout: Path, *, dry_run: bool, go_version: str) -> int:
        """Bump every Go version reference in the trading monorepo and open a PR.

        A dry run applies the patch walk to the primary checkout and shows the
        changed-files diff (no worktree, no PR). A real run follows the
        canonical trading pattern: feature worktree from master, apply the
        patch walk, commit, push, and open the PR. The temporary worktree is
        always removed afterwards.

        Args:
            checkout: Path to the bborbe/trading checkout
            dry_run: If True, patch the working tree and show the diff only
            go_version: Target Go version to set everywhere (X.Y.Z)

        Returns:
            Exit code: 0 on success or no-op, 1 on any error
        """
        if not validate_go_version(go_version):
            log_message(f"✗ Invalid Go version: {go_version!r} (expected X.Y.Z)", to_console=True)
            return 1

        branch = f"updater/trading-go-{go_version}"
        title = f"chore: bump Go version to {go_version}"
        body = (
            f"Bump all go.mod `go`/`toolchain` directives, Dockerfile "
            f"`FROM golang:` images, and workflow `go-version:` pins to Go "
            f"{go_version} (replicating update-go-version.sh)."
        )

        try:
            require_clean_worktree(checkout)
        except InfraTargetError as e:
            log_message(f"✗ {e}", to_console=True)
            return 1

        if dry_run:
            self._apply_and_report(checkout, go_version, dry_run=True)
            return 0

        if not would_change(checkout, go_version):
            log_message(f"already up to date ({go_version})", to_console=True)
            return 0

        try:
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
                changed = self._apply_and_report(worktree, go_version, dry_run=False)
                if changed == 0:
                    return 0
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

    def _apply_and_report(self, root: Path, go_version: str, *, dry_run: bool) -> int:
        """Apply the patch walk and report the diff; return files changed."""
        changed = apply_version_updates(root, go_version)
        if changed == 0:
            log_message(f"already up to date ({go_version})", to_console=True)
            return 0
        result = run_command(
            "git diff --name-only",
            cwd=root,
            capture_output=True,
            quiet=True,
            log_func=log_message,
        )
        log_message(
            f"Patched {changed} files to Go {go_version}:\n{result.stdout.strip()}",
            to_console=True,
        )
        if dry_run:
            log_message("(dry-run — no branch or PR opened)", to_console=True)
        return changed
