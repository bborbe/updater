"""Tests for the pipeline framework."""

from unittest.mock import AsyncMock, patch

from updater.pipeline import (
    CheckChangesStep,
    DockerCommitStep,
    GitConfirmStep,
    Pipeline,
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
        patch("updater.pipeline.log_message"),
        patch("updater.pipeline.config") as mock_config,
        patch(
            "updater.pipeline.analyze_unreleased_for_release",
            new_callable=AsyncMock,
            return_value={"version_bump": "minor"},
        ),
        patch("builtins.print"),
    ):
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
