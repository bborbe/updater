"""Composable pipeline architecture for module updates.

Each step is an independent unit that can be chained together to form
update workflows. Commands are recipes — specific combinations of steps.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from . import config
from .changelog import (
    add_to_unreleased,
    bump_version,
    extract_current_version,
    get_unreleased_entries,
    promote_unreleased_to_version,
    update_changelog_with_suggestions,
)
from .claude_analyzer import analyze_changes_with_claude, analyze_unreleased_for_release
from .docker_updater import update_dockerfile_images
from .file_utils import condense_file_list
from .git_operations import (
    check_git_status,
    ensure_changelog_tag,
    git_commit,
    git_push,
    git_tag_from_changelog,
)
from .go_updater import run_precommit as run_go_precommit
from .go_updater import update_go_dependencies
from .gomod_excludes import apply_gomod_excludes_and_replaces
from .log_manager import log_message
from .prompts import prompt_yes_no
from .python_updater import run_precommit as run_python_precommit
from .python_updater import update_python_dependencies
from .python_version_updater import update_python_versions
from .version_updater import update_versions


class StepStatus(Enum):
    """Result status of a pipeline step."""

    SUCCESS = "success"
    SKIP = "skip"
    FAIL = "fail"
    UP_TO_DATE = "up-to-date"


@dataclass
class StepResult:
    """Result of executing a pipeline step."""

    status: StepStatus
    metadata: dict[str, Any] = field(default_factory=dict)


class Step(ABC):
    """Abstract base class for pipeline steps."""

    @property
    def name(self) -> str:
        """Human-readable step name."""
        return self.__class__.__name__

    @abstractmethod
    async def run(self, module_path: Path, context: dict[str, Any]) -> StepResult:
        """Execute this step.

        Args:
            module_path: Path to the module being processed.
            context: Shared mutable context dict passed through the pipeline.
                     Steps can read/write to share state.

        Returns:
            StepResult indicating success, skip, or failure.
        """
        ...


# ---------------------------------------------------------------------------
# Updater steps (modify files only, no git)
# ---------------------------------------------------------------------------


class GoVersionUpdateStep(Step):
    """Update Go/Alpine versions in go.mod, Dockerfile, CI configs."""

    async def run(self, module_path: Path, context: dict[str, Any]) -> StepResult:
        updates = update_versions(module_path, log_func=log_message)
        context.setdefault("updates_made", False)
        context["updates_made"] = context["updates_made"] or updates
        return StepResult(StepStatus.SUCCESS, {"changes": updates})


class GoExcludesStep(Step):
    """Apply standard go.mod excludes and replaces."""

    async def run(self, module_path: Path, context: dict[str, Any]) -> StepResult:
        log_message("\n=== Phase 1b: Apply Standard Excludes/Replaces ===", to_console=True)
        updates = apply_gomod_excludes_and_replaces(module_path, log_func=log_message)
        context.setdefault("updates_made", False)
        context["updates_made"] = context["updates_made"] or updates
        return StepResult(StepStatus.SUCCESS, {"changes": updates})


class GoDepUpdateStep(Step):
    """Update Go dependencies via go get -u."""

    async def run(self, module_path: Path, context: dict[str, Any]) -> StepResult:
        updates = update_go_dependencies(module_path, log_func=log_message)
        context.setdefault("updates_made", False)
        context["updates_made"] = context["updates_made"] or updates
        return StepResult(StepStatus.SUCCESS, {"changes": updates})


class GoDepSkipStep(Step):
    """Placeholder that logs skipping dependency updates."""

    async def run(self, module_path: Path, context: dict[str, Any]) -> StepResult:
        log_message("\n=== Phase 1c: Skip Dependency Updates ===", to_console=True)
        log_message("  → Updating Go version only (no dependency changes)", to_console=True)
        return StepResult(StepStatus.SKIP)


class PythonVersionUpdateStep(Step):
    """Update Python version in .python-version, pyproject.toml, Dockerfile."""

    async def run(self, module_path: Path, context: dict[str, Any]) -> StepResult:
        updates = update_python_versions(module_path, log_func=log_message)
        context.setdefault("updates_made", False)
        context["updates_made"] = context["updates_made"] or updates
        return StepResult(StepStatus.SUCCESS, {"changes": updates})


class PythonDepUpdateStep(Step):
    """Update Python dependencies via uv sync --upgrade."""

    async def run(self, module_path: Path, context: dict[str, Any]) -> StepResult:
        updates = update_python_dependencies(module_path, log_func=log_message)
        context.setdefault("updates_made", False)
        context["updates_made"] = context["updates_made"] or updates
        return StepResult(StepStatus.SUCCESS, {"changes": updates})


class DockerUpdateStep(Step):
    """Update Dockerfile base image versions."""

    async def run(self, module_path: Path, context: dict[str, Any]) -> StepResult:
        updated, updates = update_dockerfile_images(module_path, log_func=log_message)
        context["docker_updates"] = updates
        context.setdefault("updates_made", False)
        context["updates_made"] = context["updates_made"] or updated
        return StepResult(
            StepStatus.SUCCESS if updated else StepStatus.UP_TO_DATE,
            {"changes": updated, "updates": updates},
        )


# ---------------------------------------------------------------------------
# Check changes step (shared by Go and Python flows)
# ---------------------------------------------------------------------------


class CheckChangesStep(Step):
    """Check git status for changes. Sets context['change_count'] and context['files'].

    If no changes found, signals pipeline to return up-to-date.
    """

    def __init__(self, *, phase: str = "update") -> None:
        self._phase = phase

    async def run(self, module_path: Path, context: dict[str, Any]) -> StepResult:
        change_count, files = check_git_status(module_path)
        context["change_count"] = change_count
        context["files"] = files
        updates_made = context.get("updates_made", False)

        if change_count == 0 and not updates_made:
            log_message("\n✓ No updates needed - module is already up to date", to_console=True)
            return StepResult(StepStatus.UP_TO_DATE)

        if change_count == 0:
            if self._phase == "precommit":
                log_message(
                    "\n✓ No changes remain after precommit (auto-formatted/fixed)",
                    to_console=True,
                )
            else:
                log_message("\n✓ No changes detected after dependency update", to_console=True)
            return StepResult(StepStatus.UP_TO_DATE)

        if self._phase == "precommit":
            log_message(f"→ {change_count} file(s) changed after precommit", to_console=True)
        elif updates_made:
            log_message(
                f"\n→ {change_count} file(s) changed after dependency update",
                to_console=True,
            )
        else:
            log_message(
                f"\n→ Processing {change_count} uncommitted file(s) from previous run",
                to_console=True,
            )

        # Show condensed file list if 20 or fewer lines
        condensed_files = condense_file_list(files)
        if len(condensed_files) <= 20:
            for f in condensed_files:
                log_message(f"  {f}", to_console=True)

        return StepResult(StepStatus.SUCCESS)


# ---------------------------------------------------------------------------
# Precommit step
# ---------------------------------------------------------------------------


class PrecommitStep(Step):
    """Run precommit checks (make precommit or equivalent)."""

    def __init__(self, project_type: str = "go") -> None:
        self._project_type = project_type

    async def run(self, module_path: Path, context: dict[str, Any]) -> StepResult:
        if self._project_type == "python":
            run_python_precommit(module_path, log_func=log_message)
        else:
            run_go_precommit(module_path, log_func=log_message)
        return StepResult(StepStatus.SUCCESS)


# ---------------------------------------------------------------------------
# Changelog step
# ---------------------------------------------------------------------------


class ChangelogStep(Step):
    """Analyze changes with Claude and update CHANGELOG.md.

    Handles versioned mode (create version tag) and unreleased mode (--no-tag).
    Also handles version_bump=="none" and missing CHANGELOG.md cases.
    """

    async def run(self, module_path: Path, context: dict[str, Any]) -> StepResult:
        from .cli import print_commit_summary

        # Analyze changes with Claude
        analysis = await analyze_changes_with_claude(module_path, log_func=log_message)
        context["analysis"] = analysis

        changelog_path = module_path / "CHANGELOG.md"

        # Case 1: No version bump needed
        if analysis["version_bump"] == "none":
            log_message(
                "\n→ No version bump needed (infrastructure changes only)",
                to_console=True,
            )
            print_commit_summary(
                module_path.name,
                analysis,
                note="No version bump or tag (infrastructure changes only)",
            )
            context["no_tag"] = True
            context["ensure_changelog_tag"] = True
            return StepResult(StepStatus.SUCCESS)

        # Case 2: --no-tag mode
        if config.NO_TAG:
            if not changelog_path.exists():
                log_message(
                    "\n→ No CHANGELOG.md found, committing without changes",
                    to_console=True,
                )
                print_commit_summary(
                    module_path.name,
                    analysis,
                    note="No CHANGELOG.md found (--no-tag mode)",
                )
            else:
                add_to_unreleased(module_path, analysis, log_func=log_message)
                print_commit_summary(
                    module_path.name,
                    analysis,
                    note="Changes added to ## Unreleased (--no-tag mode)",
                )
            context["no_tag"] = True
            return StepResult(StepStatus.SUCCESS)

        # Case 3: No CHANGELOG.md
        if not changelog_path.exists():
            log_message("\n→ No CHANGELOG.md found, committing without tag", to_console=True)
            print_commit_summary(
                module_path.name,
                analysis,
                note="No CHANGELOG.md found, no version tag will be created",
            )
            context["no_tag"] = True
            return StepResult(StepStatus.SUCCESS)

        # Case 4: Normal — update changelog and create version
        new_version = update_changelog_with_suggestions(module_path, analysis, log_func=log_message)
        context["new_version"] = new_version
        print_commit_summary(module_path.name, analysis, new_version=new_version)
        return StepResult(StepStatus.SUCCESS)


# ---------------------------------------------------------------------------
# Git steps
# ---------------------------------------------------------------------------


class GitConfirmStep(Step):
    """Prompt user for confirmation if --require-commit-confirm is set."""

    async def run(self, module_path: Path, context: dict[str, Any]) -> StepResult:
        if not config.REQUIRE_CONFIRM:
            return StepResult(StepStatus.SUCCESS)

        has_tag = not context.get("no_tag", False) and "new_version" in context
        prompt_msg = (
            "\nProceed with commit and tag?" if has_tag else "\nProceed with commit (no tag)?"
        )

        if not prompt_yes_no(prompt_msg, default_yes=True):
            log_message("\n⚠ Skipped by user", to_console=True)
            log_message("  Changes are staged but not committed", to_console=True)
            return StepResult(StepStatus.SKIP)

        return StepResult(StepStatus.SUCCESS)


class GitCommitStep(Step):
    """Commit changes and optionally tag."""

    async def run(self, module_path: Path, context: dict[str, Any]) -> StepResult:
        tag_only = context.get("tag_only", False)

        if not tag_only:
            # Normal flow: commit changes
            analysis = context.get("analysis", {})
            commit_message = context.get("commit_message", analysis.get("commit_message", "Update"))
            git_commit(module_path, commit_message, log_func=log_message)

        no_tag = context.get("no_tag", False)

        if context.get("ensure_changelog_tag"):
            ensure_changelog_tag(module_path, log_func=log_message)

        if not no_tag and "new_version" in context:
            git_tag_from_changelog(module_path, log_func=log_message)
            if tag_only:
                log_message("\n✓ Missing tag created successfully!", to_console=True)
            else:
                log_message("\n✓ Update completed successfully!", to_console=True)
        else:
            log_message("\n✓ Commit completed successfully!", to_console=True)

        return StepResult(StepStatus.SUCCESS)


class GitPushStep(Step):
    """Push commits and tags to remote."""

    async def run(self, module_path: Path, context: dict[str, Any]) -> StepResult:
        git_push(module_path, log_func=log_message)
        return StepResult(StepStatus.SUCCESS)


# ---------------------------------------------------------------------------
# Release step
# ---------------------------------------------------------------------------


class ReleaseStep(Step):
    """Promote ## Unreleased to versioned section with tag.

    If no ## Unreleased section exists but there are commits since the last tag,
    generates changelog entries from commit messages using Claude.
    """

    def _add_unreleased_section(self, changelog_path: Path, entries: list[str]) -> None:
        """Add ## Unreleased section with entries to changelog."""
        with open(changelog_path) as f:
            content = f.read()

        # Find first version section
        lines = content.split("\n")
        insert_idx = 0
        for i, line in enumerate(lines):
            if line.startswith("## v"):
                insert_idx = i
                break

        # Build new section
        entries_text = "\n".join(entries)
        new_section = f"## Unreleased\n\n{entries_text}\n"

        lines.insert(insert_idx, new_section)

        with open(changelog_path, "w") as f:
            f.write("\n".join(lines))

    def _get_latest_changelog_version(self, changelog_path: Path) -> str | None:
        """Get the latest version from CHANGELOG.md (first ## vX.Y.Z section)."""
        import re

        with open(changelog_path) as f:
            content = f.read()

        # Find first version section (skip ## Unreleased if present)
        match = re.search(r"##\s+(v\d+\.\d+\.\d+)", content)
        return match.group(1) if match else None

    async def run(self, module_path: Path, context: dict[str, Any]) -> StepResult:
        from .claude_analyzer import generate_changelog_from_commits
        from .git_operations import get_commits_since_tag, get_latest_tag

        changelog_path = module_path / "CHANGELOG.md"
        if not changelog_path.exists():
            log_message("Nothing to release (no CHANGELOG.md)", to_console=True)
            return StepResult(StepStatus.UP_TO_DATE)

        # Check for commits since last tag
        latest_tag = get_latest_tag(module_path)
        commits = get_commits_since_tag(module_path, latest_tag)

        if not commits:
            log_message("Nothing to release (no commits since last tag)", to_console=True)
            return StepResult(StepStatus.UP_TO_DATE)

        log_message(
            f"\n→ Found {len(commits)} commits since {latest_tag or 'beginning'}:",
            to_console=True,
        )
        for c in commits[:5]:  # Show first 5
            log_message(f"  {c['hash']} {c['subject']}", to_console=True)
        if len(commits) > 5:
            log_message(f"  ... and {len(commits) - 5} more", to_console=True)

        # Check if ## Unreleased exists
        entries = get_unreleased_entries(changelog_path)

        if entries is None:
            # No ## Unreleased section - check if latest CHANGELOG version is missing a tag
            changelog_version = self._get_latest_changelog_version(changelog_path)

            if changelog_version and changelog_version != latest_tag:
                # CHANGELOG has a version that's not tagged - just tag it
                log_message(
                    f"\n→ CHANGELOG has {changelog_version} but tag doesn't exist",
                    to_console=True,
                )
                log_message("→ Creating missing tag...", to_console=True)

                context["new_version"] = changelog_version
                context["commit_message"] = f"Release {changelog_version}"
                context["tag_only"] = True  # Signal that we only need to tag, no commit
                return StepResult(StepStatus.SUCCESS)

            # No version mismatch - generate from commits
            log_message("\n⚠ No ## Unreleased section found", to_console=True)
            log_message("→ Generating changelog entries from commits...", to_console=True)

            generated_entries = await generate_changelog_from_commits(
                commits, module_path.name, log_func=log_message
            )

            if not generated_entries:
                log_message("⚠ Could not generate changelog entries", to_console=True)
                return StepResult(StepStatus.SKIP)

            # Add ## Unreleased section with generated entries
            entries = [f"- {e}" for e in generated_entries]
            self._add_unreleased_section(changelog_path, entries)
            log_message(f"✓ Added ## Unreleased with {len(entries)} entries", to_console=True)

        log_message(f"\n→ Found {len(entries)} unreleased entries:", to_console=True)
        for entry in entries:
            log_message(f"  {entry}", to_console=True)

        # Analyze with Claude
        analysis = await analyze_unreleased_for_release(
            entries, module_path.name, log_func=log_message
        )

        # Calculate new version
        major, minor, patch = extract_current_version(changelog_path)
        new_version = bump_version(major, minor, patch, analysis["version_bump"])
        old_version = f"v{major}.{minor}.{patch}"

        log_message(f"\n  Current version: {old_version}", to_console=True)
        log_message(f"  Version bump: {analysis['version_bump']}", to_console=True)
        log_message(f"  New version: {new_version}", to_console=True)

        # Show summary
        print("\n" + "=" * 60)
        print(f"READY TO RELEASE: {module_path.name}")
        print("=" * 60)
        print(f"Version:        {old_version} → {new_version} ({analysis['version_bump']} bump)")
        print(f"Commit message: Release {new_version}")
        print(f"Git tag:        {new_version}")
        print("\nUnreleased entries:")
        for entry in entries:
            print(f"  {entry}")
        print("=" * 60)

        if config.REQUIRE_CONFIRM:
            if not prompt_yes_no("\nProceed with release?", default_yes=True):
                log_message("\n⚠ Skipped by user", to_console=True)
                return StepResult(StepStatus.SKIP)

        # Promote unreleased to version
        promote_unreleased_to_version(changelog_path, new_version)
        log_message(f"\n✓ CHANGELOG updated: ## Unreleased → ## {new_version}", to_console=True)

        context["new_version"] = new_version
        context["commit_message"] = f"Release {new_version}"
        return StepResult(StepStatus.SUCCESS)


# ---------------------------------------------------------------------------
# Docker commit step (simpler than full changelog flow)
# ---------------------------------------------------------------------------


class DockerCommitStep(Step):
    """Commit Docker image updates."""

    async def run(self, module_path: Path, context: dict[str, Any]) -> StepResult:
        updates = context.get("docker_updates", [])
        if not updates:
            return StepResult(StepStatus.UP_TO_DATE)

        change_count, _ = check_git_status(module_path)
        if change_count == 0:
            log_message(
                "\n✓ Dockerfile updated (already matches committed version)",
                to_console=True,
            )
            return StepResult(StepStatus.UP_TO_DATE)

        if len(updates) == 1:
            commit_msg = f"Update Dockerfile: {updates[0]}"
        else:
            commit_msg = "Update Dockerfile images\n\n" + "\n".join(f"- {u}" for u in updates)

        log_message("\n=== Committing Changes ===", to_console=True)
        git_commit(module_path, commit_msg, log_func=log_message)
        log_message("\n✓ Dockerfile updated and committed", to_console=True)
        return StepResult(StepStatus.SUCCESS)


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------


class Pipeline:
    """Execute a sequence of steps, handling early exit on UP_TO_DATE or SKIP."""

    def __init__(self, steps: list[Step]) -> None:
        self.steps = steps

    async def run(self, module_path: Path, context: dict[str, Any] | None = None) -> StepResult:
        """Run all steps in sequence.

        Returns early if a step returns UP_TO_DATE or SKIP.
        Raises on FAIL.

        Args:
            module_path: Path to the module.
            context: Optional shared context dict.

        Returns:
            The final StepResult.
        """
        if context is None:
            context = {}

        last_result = StepResult(StepStatus.SUCCESS)
        for step in self.steps:
            result = await step.run(module_path, context)
            last_result = result

            if result.status == StepStatus.UP_TO_DATE:
                return result
            if result.status == StepStatus.SKIP:
                # SKIP from GoDepSkipStep is fine, continue
                if isinstance(step, GoDepSkipStep):
                    continue
                # SKIP from GitConfirmStep means user declined
                if isinstance(step, GitConfirmStep):
                    return result
                continue
            if result.status == StepStatus.FAIL:
                return result

        return last_result
