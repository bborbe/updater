"""Tests for CommitUncommittedStep."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from updater.pipeline import CommitUncommittedStep, StepStatus


def _make_run_result(stdout: str) -> MagicMock:
    result = MagicMock()
    result.stdout = stdout
    return result


@pytest.mark.asyncio
async def test_clean_working_tree_returns_up_to_date(tmp_path: Path) -> None:
    """Clean working tree: step returns UP_TO_DATE without calling git add/commit."""
    git_add_called = []
    git_commit_called = []

    def fake_run_command(cmd: str, **kwargs):
        if "status" in cmd:
            return _make_run_result("")
        if "add" in cmd:
            git_add_called.append(cmd)
        if "commit" in cmd:
            git_commit_called.append(cmd)
        return _make_run_result("")

    with patch("updater.pipeline.run_command", side_effect=fake_run_command):
        with patch("updater.pipeline.log_message"):
            step = CommitUncommittedStep()
            result = await step.run(tmp_path, {})

    assert result.status == StepStatus.UP_TO_DATE
    assert git_add_called == []
    assert git_commit_called == []


@pytest.mark.asyncio
async def test_dirty_working_tree_commits_changes(tmp_path: Path) -> None:
    """Dirty working tree: step calls git add and git commit, returns SUCCESS."""
    calls = []

    def fake_run_command(cmd: str, **kwargs):
        calls.append(cmd)
        if "status" in cmd:
            return _make_run_result(" M Dockerfile\n")
        return _make_run_result("")

    with patch("updater.pipeline.run_command", side_effect=fake_run_command):
        with patch("updater.pipeline.log_message"):
            step = CommitUncommittedStep()
            result = await step.run(tmp_path, {})

    assert result.status == StepStatus.SUCCESS
    assert any("add" in c for c in calls)
    assert any("commit" in c for c in calls)


@pytest.mark.asyncio
async def test_untracked_file_triggers_commit(tmp_path: Path) -> None:
    """Untracked file in working tree: step commits it and returns SUCCESS."""
    calls = []

    def fake_run_command(cmd: str, **kwargs):
        calls.append(cmd)
        if "status" in cmd:
            return _make_run_result("?? newfile.txt\n")
        return _make_run_result("")

    with patch("updater.pipeline.run_command", side_effect=fake_run_command):
        with patch("updater.pipeline.log_message"):
            step = CommitUncommittedStep()
            result = await step.run(tmp_path, {})

    assert result.status == StepStatus.SUCCESS
    assert any("add" in c for c in calls)
    assert any("commit" in c for c in calls)
