"""Tests for the pipeline framework."""

from unittest.mock import AsyncMock, patch

from updater.pipeline import (
    CheckChangesStep,
    DockerCommitStep,
    DockerUpdateStep,
    GitCommitStep,
    GitConfirmStep,
    GitPushStep,
    GitSyncStep,
    GoDepSkipStep,
    Pipeline,
    PrecommitStep,
    PythonDepUpdateStep,
    PythonVersionUpdateStep,
    ReleaseStep,
    Step,
    StepResult,
    StepStatus,
)

# ---------------------------------------------------------------------------
# StepResult / StepStatus basics
# ---------------------------------------------------------------------------


def test_step_result_default_metadata():
    """Test StepResult defaults to empty metadata dict."""
    result = StepResult(StepStatus.SUCCESS)
    assert result.status == StepStatus.SUCCESS
    assert result.metadata == {}


def test_step_result_with_metadata():
    """Test StepResult stores metadata."""
    result = StepResult(StepStatus.FAIL, {"error": "something broke"})
    assert result.status == StepStatus.FAIL
    assert result.metadata["error"] == "something broke"


def test_step_status_values():
    """Test StepStatus enum values."""
    assert StepStatus.SUCCESS.value == "success"
    assert StepStatus.SKIP.value == "skip"
    assert StepStatus.FAIL.value == "fail"
    assert StepStatus.UP_TO_DATE.value == "up-to-date"


# ---------------------------------------------------------------------------
# Pipeline.run()
# ---------------------------------------------------------------------------


class _SuccessStep(Step):
    async def run(self, module_path, context):
        context["ran_success"] = True
        return StepResult(StepStatus.SUCCESS)


class _UpToDateStep(Step):
    async def run(self, module_path, context):
        return StepResult(StepStatus.UP_TO_DATE)


class _FailStep(Step):
    async def run(self, module_path, context):
        return StepResult(StepStatus.FAIL)


async def test_pipeline_chains_steps(tmp_path):
    """Test Pipeline runs all steps in sequence and shares context."""
    ctx = {}
    pipeline = Pipeline([_SuccessStep(), _SuccessStep()])
    result = await pipeline.run(tmp_path, ctx)

    assert result.status == StepStatus.SUCCESS
    assert ctx["ran_success"] is True


async def test_pipeline_returns_early_on_up_to_date(tmp_path):
    """Test Pipeline stops on UP_TO_DATE."""
    second = _SuccessStep()
    pipeline = Pipeline([_UpToDateStep(), second])
    ctx = {}
    result = await pipeline.run(tmp_path, ctx)

    assert result.status == StepStatus.UP_TO_DATE
    assert "ran_success" not in ctx  # second step never ran


async def test_pipeline_returns_early_on_fail(tmp_path):
    """Test Pipeline stops on FAIL."""
    ctx = {}
    pipeline = Pipeline([_FailStep(), _SuccessStep()])
    result = await pipeline.run(tmp_path, ctx)

    assert result.status == StepStatus.FAIL
    assert "ran_success" not in ctx


async def test_pipeline_creates_context_if_none(tmp_path):
    """Test Pipeline creates empty context when None provided."""
    pipeline = Pipeline([_SuccessStep()])
    result = await pipeline.run(tmp_path)
    assert result.status == StepStatus.SUCCESS


async def test_pipeline_git_confirm_skip_returns_early(tmp_path):
    """Test Pipeline returns early when GitConfirmStep returns SKIP."""
    with patch("updater.pipeline.config") as mock_config:
        mock_config.NO_GIT = False
        mock_config.REQUIRE_CONFIRM = True

        with patch("updater.pipeline.prompt_yes_no", return_value=False):
            pipeline = Pipeline([GitConfirmStep(), _SuccessStep()])
            ctx = {}
            result = await pipeline.run(tmp_path, ctx)

            assert result.status == StepStatus.SKIP
            assert "ran_success" not in ctx


# ---------------------------------------------------------------------------
# CheckChangesStep
# ---------------------------------------------------------------------------


async def test_check_changes_step_no_changes(tmp_path):
    """Test CheckChangesStep returns UP_TO_DATE when no changes."""
    with patch("updater.pipeline.check_git_status", return_value=(0, [])):
        with patch("updater.pipeline.log_message"):
            step = CheckChangesStep()
            ctx = {}
            result = await step.run(tmp_path, ctx)

            assert result.status == StepStatus.UP_TO_DATE


async def test_check_changes_step_with_changes(tmp_path):
    """Test CheckChangesStep returns SUCCESS when changes exist."""
    with patch("updater.pipeline.check_git_status", return_value=(2, ["go.mod", "go.sum"])):
        with patch("updater.pipeline.log_message"):
            with patch("updater.pipeline.condense_file_list", return_value=["go.mod", "go.sum"]):
                step = CheckChangesStep()
                ctx = {"updates_made": True}
                result = await step.run(tmp_path, ctx)

                assert result.status == StepStatus.SUCCESS
                assert ctx["change_count"] == 2
                assert ctx["files"] == ["go.mod", "go.sum"]


async def test_check_changes_step_precommit_phase_no_changes(tmp_path):
    """Test CheckChangesStep in precommit phase with no changes."""
    with patch("updater.pipeline.check_git_status", return_value=(0, [])):
        with patch("updater.pipeline.log_message"):
            step = CheckChangesStep(phase="precommit")
            ctx = {"updates_made": True}
            result = await step.run(tmp_path, ctx)

            assert result.status == StepStatus.UP_TO_DATE


# ---------------------------------------------------------------------------
# ReleaseStep
# ---------------------------------------------------------------------------


async def test_release_step_no_changelog(tmp_path):
    """Test ReleaseStep returns UP_TO_DATE when no CHANGELOG.md."""
    with patch("updater.pipeline.log_message"):
        step = ReleaseStep()
        ctx = {}
        result = await step.run(tmp_path, ctx)

        assert result.status == StepStatus.UP_TO_DATE


async def test_release_step_no_unreleased_entries(tmp_path):
    """Test ReleaseStep returns UP_TO_DATE when no unreleased entries."""
    (tmp_path / "CHANGELOG.md").write_text("# Changelog\n\n## v1.0.0\n\n- Init\n")

    with patch("updater.pipeline.log_message"):
        step = ReleaseStep()
        ctx = {}
        result = await step.run(tmp_path, ctx)

        assert result.status == StepStatus.UP_TO_DATE


async def test_release_step_with_unreleased_entries(tmp_path):
    """Test ReleaseStep promotes unreleased entries to new version."""
    (tmp_path / "CHANGELOG.md").write_text(
        "# Changelog\n\n## Unreleased\n\n- New feature\n\n## v1.0.0\n\n- Init\n"
    )

    with (
        patch("updater.git_operations.get_latest_tag", return_value="v1.0.0"),
        patch(
            "updater.git_operations.get_commits_since_tag",
            return_value=[{"hash": "abc123", "subject": "New feature", "body": ""}],
        ),
        patch("updater.pipeline.log_message"),
        patch("updater.pipeline.config") as mock_config,
        patch(
            "updater.pipeline.analyze_unreleased_for_release",
            new_callable=AsyncMock,
            return_value={"version_bump": "minor"},
        ),
        patch("builtins.print"),
    ):
        mock_config.NO_GIT = False
        mock_config.REQUIRE_CONFIRM = False

        step = ReleaseStep()
        ctx = {}
        result = await step.run(tmp_path, ctx)

        assert result.status == StepStatus.SUCCESS
        assert ctx["new_version"] == "v1.1.0"
        assert ctx["commit_message"] == "Release v1.1.0"

        # Verify CHANGELOG was updated
        content = (tmp_path / "CHANGELOG.md").read_text()
        assert "## v1.1.0" in content
        assert "## Unreleased" not in content


# ---------------------------------------------------------------------------
# DockerCommitStep
# ---------------------------------------------------------------------------


async def test_docker_commit_step_no_updates(tmp_path):
    """Test DockerCommitStep returns UP_TO_DATE when no updates."""
    step = DockerCommitStep()
    ctx = {"docker_updates": []}
    result = await step.run(tmp_path, ctx)

    assert result.status == StepStatus.UP_TO_DATE


async def test_docker_commit_step_no_git_changes(tmp_path):
    """Test DockerCommitStep returns UP_TO_DATE when git has no changes."""
    with (
        patch("updater.pipeline.check_git_status", return_value=(0, [])),
        patch("updater.pipeline.log_message"),
    ):
        step = DockerCommitStep()
        ctx = {"docker_updates": ["nginx:1.25→1.26"]}
        result = await step.run(tmp_path, ctx)

        assert result.status == StepStatus.UP_TO_DATE


async def test_docker_commit_step_with_changes(tmp_path):
    """Test DockerCommitStep commits when there are changes."""
    with (
        patch("updater.pipeline.check_git_status", return_value=(1, ["Dockerfile"])),
        patch("updater.pipeline.git_commit") as mock_commit,
        patch("updater.pipeline.log_message"),
    ):
        step = DockerCommitStep()
        ctx = {"docker_updates": ["nginx:1.25→1.26"]}
        result = await step.run(tmp_path, ctx)

        assert result.status == StepStatus.SUCCESS
        mock_commit.assert_called_once()
        assert "nginx:1.25→1.26" in mock_commit.call_args[0][1]


# ---------------------------------------------------------------------------
# ReleaseStep - missing tag detection
# ---------------------------------------------------------------------------


async def test_release_step_detects_missing_tag(tmp_path):
    """Test ReleaseStep detects when CHANGELOG version has no corresponding tag."""
    # Create CHANGELOG with v0.5.2 but no ## Unreleased
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text("""# Changelog

## v0.5.2
- Some feature

## v0.5.1
- Previous feature
""")

    with (
        patch("updater.git_operations.get_latest_tag", return_value="v0.5.1"),
        patch(
            "updater.git_operations.get_commits_since_tag",
            return_value=[{"hash": "abc123", "subject": "Add feature", "body": ""}],
        ),
        patch("updater.changelog.get_unreleased_entries", return_value=None),
        patch("updater.pipeline.log_message"),
    ):
        step = ReleaseStep()
        ctx = {}
        result = await step.run(tmp_path, ctx)

        assert result.status == StepStatus.SUCCESS
        assert ctx["new_version"] == "v0.5.2"
        assert ctx["tag_only"] is True
        assert ctx["commit_message"] == "Release v0.5.2"


# ---------------------------------------------------------------------------
# PrecommitStep - check-command override
# ---------------------------------------------------------------------------


async def test_custom_check_command_is_used(tmp_path):
    """Test PrecommitStep uses custom command when CHECK_COMMAND is set."""
    with (
        patch("updater.pipeline.config") as mock_config,
        patch("updater.pipeline.run_command") as mock_run_command,
        patch("updater.pipeline.log_message"),
    ):
        mock_config.CHECK_COMMAND = "make ensure test"

        step = PrecommitStep(project_type="go")
        ctx = {}
        result = await step.run(tmp_path, ctx)

        assert result.status == StepStatus.SUCCESS
        mock_run_command.assert_called_once()
        call_args = mock_run_command.call_args
        assert call_args[0][0] == "make ensure test"
        assert call_args[1]["cwd"] == tmp_path
        assert call_args[1]["quiet"] is True


async def test_default_precommit_runs_when_no_override(tmp_path):
    """Test PrecommitStep runs default precommit when CHECK_COMMAND is empty."""
    with (
        patch("updater.pipeline.config") as mock_config,
        patch("updater.pipeline.run_command") as mock_run_command,
        patch("updater.pipeline.run_go_precommit") as mock_go_precommit,
        patch("updater.pipeline.log_message"),
    ):
        mock_config.CHECK_COMMAND = ""

        step = PrecommitStep(project_type="go")
        ctx = {}
        result = await step.run(tmp_path, ctx)

        assert result.status == StepStatus.SUCCESS
        mock_run_command.assert_not_called()
        mock_go_precommit.assert_called_once()
        assert mock_go_precommit.call_args[0][0] == tmp_path


# ---------------------------------------------------------------------------
# GitSyncStep
# ---------------------------------------------------------------------------


async def test_git_sync_step_success(tmp_path):
    """Test GitSyncStep returns SUCCESS when update_git_branch returns True."""
    with (
        patch("updater.pipeline.update_git_branch", return_value=True) as mock_sync,
        patch("updater.pipeline.log_message"),
    ):
        step = GitSyncStep()
        ctx = {}
        result = await step.run(tmp_path, ctx)

        assert result.status == StepStatus.SUCCESS
        mock_sync.assert_called_once_with(tmp_path, log_func=mock_sync.call_args[1]["log_func"])


async def test_git_sync_step_failure(tmp_path):
    """Test GitSyncStep returns FAIL when update_git_branch returns False."""
    with (
        patch("updater.pipeline.update_git_branch", return_value=False),
        patch("updater.pipeline.log_message"),
    ):
        step = GitSyncStep()
        ctx = {}
        result = await step.run(tmp_path, ctx)

        assert result.status == StepStatus.FAIL
        assert result.metadata["error"] == "git sync failed"


async def test_check_command_failure_raises(tmp_path):
    """Test PrecommitStep raises when custom command fails."""
    with (
        patch("updater.pipeline.config") as mock_config,
        patch("updater.pipeline.run_command", side_effect=Exception("Command failed")),
        patch("updater.pipeline.log_message"),
    ):
        mock_config.CHECK_COMMAND = "make failing-check"

        step = PrecommitStep(project_type="go")
        ctx = {}

        import pytest

        with pytest.raises(Exception, match="Command failed"):
            await step.run(tmp_path, ctx)


# ---------------------------------------------------------------------------
# GoDepSkipStep
# ---------------------------------------------------------------------------


async def test_go_dep_skip_step_returns_skip(tmp_path):
    """Test GoDepSkipStep returns SKIP."""
    with patch("updater.pipeline.log_message"):
        step = GoDepSkipStep()
        ctx = {}
        result = await step.run(tmp_path, ctx)

        assert result.status == StepStatus.SKIP


async def test_pipeline_go_dep_skip_continues_to_next_step(tmp_path):
    """Test Pipeline continues to next step when GoDepSkipStep returns SKIP."""
    with patch("updater.pipeline.log_message"):
        pipeline = Pipeline([GoDepSkipStep(), _SuccessStep()])
        ctx = {}
        result = await pipeline.run(tmp_path, ctx)

        # Pipeline should continue and the next step should have run
        assert result.status == StepStatus.SUCCESS
        assert ctx.get("ran_success") is True


# ---------------------------------------------------------------------------
# PrecommitStep - python project type
# ---------------------------------------------------------------------------


async def test_precommit_step_python_type(tmp_path):
    """Test PrecommitStep runs python precommit when project_type is python."""
    with (
        patch("updater.pipeline.config") as mock_config,
        patch("updater.pipeline.run_python_precommit") as mock_python_precommit,
        patch("updater.pipeline.run_go_precommit") as mock_go_precommit,
        patch("updater.pipeline.log_message"),
    ):
        mock_config.CHECK_COMMAND = ""

        step = PrecommitStep(project_type="python")
        ctx = {}
        result = await step.run(tmp_path, ctx)

        assert result.status == StepStatus.SUCCESS
        mock_python_precommit.assert_called_once_with(
            tmp_path, log_func=mock_python_precommit.call_args[1]["log_func"]
        )
        mock_go_precommit.assert_not_called()


# ---------------------------------------------------------------------------
# DockerCommitStep - multiple updates
# ---------------------------------------------------------------------------


async def test_docker_commit_multiple_updates(tmp_path):
    """Test DockerCommitStep uses multi-line commit message for multiple updates."""
    with (
        patch(
            "updater.pipeline.check_git_status", return_value=(2, ["Dockerfile", "Dockerfile.test"])
        ),
        patch("updater.pipeline.git_commit") as mock_commit,
        patch("updater.pipeline.log_message"),
    ):
        step = DockerCommitStep()
        ctx = {"docker_updates": ["nginx:1.25→1.26", "alpine:3.18→3.19"]}
        result = await step.run(tmp_path, ctx)

        assert result.status == StepStatus.SUCCESS
        mock_commit.assert_called_once()
        commit_msg = mock_commit.call_args[0][1]
        assert "Update Dockerfile images" in commit_msg
        assert "nginx:1.25→1.26" in commit_msg
        assert "alpine:3.18→3.19" in commit_msg


# ---------------------------------------------------------------------------
# Pipeline - generic SKIP continue
# ---------------------------------------------------------------------------


class _SkipStep(Step):
    """A step that returns SKIP (not GoDepSkipStep or GitConfirmStep)."""

    async def run(self, module_path, context):
        return StepResult(StepStatus.SKIP)


async def test_pipeline_generic_skip_continues(tmp_path):
    """Test Pipeline continues to next step for generic SKIP steps."""
    pipeline = Pipeline([_SkipStep(), _SuccessStep()])
    ctx = {}
    result = await pipeline.run(tmp_path, ctx)

    # Pipeline should continue and the success step should run
    assert result.status == StepStatus.SUCCESS
    assert ctx.get("ran_success") is True


# ---------------------------------------------------------------------------
# Step.name property
# ---------------------------------------------------------------------------


def test_step_name_property():
    """Test Step.name returns the class name."""
    step = GoDepSkipStep()
    assert step.name == "GoDepSkipStep"


def test_step_name_property_precommit():
    """Test Step.name for PrecommitStep."""
    step = PrecommitStep()
    assert step.name == "PrecommitStep"


# ---------------------------------------------------------------------------
# PythonVersionUpdateStep
# ---------------------------------------------------------------------------


async def test_python_version_update_step(tmp_path):
    """Test PythonVersionUpdateStep calls update_python_versions and sets context."""
    with (
        patch("updater.pipeline.update_python_versions", return_value=True) as mock_update,
        patch("updater.pipeline.log_message"),
    ):
        step = PythonVersionUpdateStep()
        ctx = {}
        result = await step.run(tmp_path, ctx)

        assert result.status == StepStatus.SUCCESS
        assert ctx["updates_made"] is True
        mock_update.assert_called_once_with(tmp_path, log_func=mock_update.call_args[1]["log_func"])


async def test_python_version_update_step_no_changes(tmp_path):
    """Test PythonVersionUpdateStep when no updates needed."""
    with (
        patch("updater.pipeline.update_python_versions", return_value=False),
        patch("updater.pipeline.log_message"),
    ):
        step = PythonVersionUpdateStep()
        ctx = {"updates_made": False}
        result = await step.run(tmp_path, ctx)

        assert result.status == StepStatus.SUCCESS
        assert ctx["updates_made"] is False


# ---------------------------------------------------------------------------
# PythonDepUpdateStep
# ---------------------------------------------------------------------------


async def test_python_dep_update_step(tmp_path):
    """Test PythonDepUpdateStep calls update_python_dependencies and sets context."""
    with (
        patch("updater.pipeline.update_python_dependencies", return_value=True) as mock_update,
        patch("updater.pipeline.log_message"),
    ):
        step = PythonDepUpdateStep()
        ctx = {}
        result = await step.run(tmp_path, ctx)

        assert result.status == StepStatus.SUCCESS
        assert ctx["updates_made"] is True
        mock_update.assert_called_once_with(tmp_path, log_func=mock_update.call_args[1]["log_func"])


# ---------------------------------------------------------------------------
# DockerUpdateStep
# ---------------------------------------------------------------------------


async def test_docker_update_step_with_changes(tmp_path):
    """Test DockerUpdateStep returns SUCCESS and sets context when changes detected."""
    with (
        patch(
            "updater.pipeline.update_dockerfile_images",
            return_value=(True, ["nginx:1.25→1.26"]),
        ) as mock_update,
        patch("updater.pipeline.log_message"),
    ):
        step = DockerUpdateStep()
        ctx = {}
        result = await step.run(tmp_path, ctx)

        assert result.status == StepStatus.SUCCESS
        assert ctx["updates_made"] is True
        assert ctx["docker_updates"] == ["nginx:1.25→1.26"]
        mock_update.assert_called_once()


async def test_docker_update_step_no_changes(tmp_path):
    """Test DockerUpdateStep returns UP_TO_DATE when no changes."""
    with (
        patch("updater.pipeline.update_dockerfile_images", return_value=(False, [])),
        patch("updater.pipeline.log_message"),
    ):
        step = DockerUpdateStep()
        ctx = {}
        result = await step.run(tmp_path, ctx)

        assert result.status == StepStatus.UP_TO_DATE
        assert ctx["updates_made"] is False
        assert ctx["docker_updates"] == []


# ---------------------------------------------------------------------------
# GitPushStep
# ---------------------------------------------------------------------------


async def test_git_push_step(tmp_path):
    """Test GitPushStep calls git_push and returns SUCCESS."""
    with (
        patch("updater.pipeline.git_push") as mock_push,
        patch("updater.pipeline.log_message"),
    ):
        step = GitPushStep()
        ctx = {}
        result = await step.run(tmp_path, ctx)

        assert result.status == StepStatus.SUCCESS
        mock_push.assert_called_once_with(tmp_path, log_func=mock_push.call_args[1]["log_func"])


# ---------------------------------------------------------------------------
# GitCommitStep - tag_only path
# ---------------------------------------------------------------------------


async def test_git_commit_step_tag_only(tmp_path):
    """Test GitCommitStep skips commit and only tags when tag_only is set."""
    with (
        patch("updater.pipeline.git_commit") as mock_commit,
        patch("updater.pipeline.git_tag_from_changelog") as mock_tag,
        patch("updater.pipeline.log_message"),
    ):
        step = GitCommitStep()
        ctx = {"tag_only": True, "new_version": "v1.2.0"}
        result = await step.run(tmp_path, ctx)

        assert result.status == StepStatus.SUCCESS
        mock_commit.assert_not_called()
        mock_tag.assert_called_once()
