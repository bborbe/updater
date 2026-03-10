"""Tests for module_config.py."""

from unittest.mock import patch

from updater.module_config import (
    VALID_DISABLE_VALUES,
    ModuleConfig,
    is_disabled,
    load_module_config,
)
from updater.pipeline import (
    GoDepUpdateStep,
    GoVersionUpdateStep,
    Pipeline,
    PythonDepUpdateStep,
    PythonVersionUpdateStep,
    StepResult,
    StepStatus,
)

# ---------------------------------------------------------------------------
# ModuleConfig dataclass
# ---------------------------------------------------------------------------


def test_module_config_default():
    """ModuleConfig defaults to empty disable list."""
    cfg = ModuleConfig()
    assert cfg.disable == []


def test_module_config_with_disable():
    """ModuleConfig stores disable list."""
    cfg = ModuleConfig(disable=["python-version", "llm-analysis"])
    assert "python-version" in cfg.disable
    assert "llm-analysis" in cfg.disable


# ---------------------------------------------------------------------------
# load_module_config — missing / empty file
# ---------------------------------------------------------------------------


def test_load_module_config_missing_file(tmp_path):
    """Returns default config when .updater.yaml is absent."""
    cfg = load_module_config(tmp_path)
    assert cfg.disable == []


def test_load_module_config_empty_file(tmp_path):
    """Returns default config when .updater.yaml is empty."""
    (tmp_path / ".updater.yaml").write_text("")
    cfg = load_module_config(tmp_path)
    assert cfg.disable == []


def test_load_module_config_whitespace_only(tmp_path):
    """Returns default config when .updater.yaml contains only whitespace."""
    (tmp_path / ".updater.yaml").write_text("   \n  \n")
    cfg = load_module_config(tmp_path)
    assert cfg.disable == []


# ---------------------------------------------------------------------------
# load_module_config — valid config
# ---------------------------------------------------------------------------


def test_load_module_config_valid_disable_list(tmp_path):
    """Parses a valid disable list correctly."""
    (tmp_path / ".updater.yaml").write_text("disable:\n  - python-version\n  - llm-analysis\n")
    cfg = load_module_config(tmp_path)
    assert "python-version" in cfg.disable
    assert "llm-analysis" in cfg.disable
    assert len(cfg.disable) == 2


def test_load_module_config_all_valid_values(tmp_path):
    """All VALID_DISABLE_VALUES are accepted."""
    lines = "disable:\n" + "".join(f"  - {v}\n" for v in sorted(VALID_DISABLE_VALUES))
    (tmp_path / ".updater.yaml").write_text(lines)
    cfg = load_module_config(tmp_path)
    assert set(cfg.disable) == VALID_DISABLE_VALUES


def test_load_module_config_no_disable_key(tmp_path):
    """Returns default config when 'disable' key is absent."""
    (tmp_path / ".updater.yaml").write_text("some_other_key: value\n")
    cfg = load_module_config(tmp_path)
    assert cfg.disable == []


# ---------------------------------------------------------------------------
# load_module_config — malformed YAML
# ---------------------------------------------------------------------------


def test_load_module_config_malformed_yaml(tmp_path):
    """Warns and returns defaults for malformed YAML."""
    (tmp_path / ".updater.yaml").write_text("disable: [\nunterminated")
    with patch("updater.module_config.log_message") as mock_log:
        cfg = load_module_config(tmp_path)
    assert cfg.disable == []
    # Should have logged a warning
    assert mock_log.called
    logged_text = " ".join(str(c) for c in mock_log.call_args_list)
    assert "malformed" in logged_text.lower()


# ---------------------------------------------------------------------------
# load_module_config — unknown disable values
# ---------------------------------------------------------------------------


def test_load_module_config_unknown_disable_value(tmp_path):
    """Warns for unknown values but retains known ones."""
    (tmp_path / ".updater.yaml").write_text("disable:\n  - python-version\n  - unknown-phase\n")
    with patch("updater.module_config.log_message") as mock_log:
        cfg = load_module_config(tmp_path)
    assert "python-version" in cfg.disable
    assert "unknown-phase" not in cfg.disable
    logged_text = " ".join(str(c) for c in mock_log.call_args_list)
    assert "unknown-phase" in logged_text


# ---------------------------------------------------------------------------
# load_module_config — scalar disable value
# ---------------------------------------------------------------------------


def test_load_module_config_scalar_disable(tmp_path):
    """Warns and returns defaults when disable is a scalar string."""
    (tmp_path / ".updater.yaml").write_text("disable: python-version\n")
    with patch("updater.module_config.log_message") as mock_log:
        cfg = load_module_config(tmp_path)
    assert cfg.disable == []
    logged_text = " ".join(str(c) for c in mock_log.call_args_list)
    assert "list" in logged_text.lower()


# ---------------------------------------------------------------------------
# load_module_config — file > 64 KB
# ---------------------------------------------------------------------------


def test_load_module_config_file_too_large(tmp_path):
    """Warns and returns defaults when file exceeds 64 KB."""
    config_path = tmp_path / ".updater.yaml"
    config_path.write_text("disable:\n  - python-version\n" + "#" * (64 * 1024 + 1))
    with patch("updater.module_config.log_message") as mock_log:
        cfg = load_module_config(tmp_path)
    assert cfg.disable == []
    logged_text = " ".join(str(c) for c in mock_log.call_args_list)
    assert "64" in logged_text


# ---------------------------------------------------------------------------
# is_disabled helper
# ---------------------------------------------------------------------------


def test_is_disabled_false_when_empty():
    """is_disabled returns False when disable list is empty."""
    cfg = ModuleConfig()
    assert not is_disabled(cfg, "python-version")


def test_is_disabled_true_when_phase_present():
    """is_disabled returns True when phase is in disable list."""
    cfg = ModuleConfig(disable=["python-version", "llm-analysis"])
    assert is_disabled(cfg, "python-version")
    assert is_disabled(cfg, "llm-analysis")


def test_is_disabled_false_when_phase_not_in_list():
    """is_disabled returns False when phase is not in disable list."""
    cfg = ModuleConfig(disable=["python-version"])
    assert not is_disabled(cfg, "golang-version")
    assert not is_disabled(cfg, "go-dependencies")


# ---------------------------------------------------------------------------
# Pipeline integration — disabled steps return SKIP and pipeline continues
# ---------------------------------------------------------------------------


async def test_go_version_step_skipped_when_golang_version_disabled(tmp_path):
    """GoVersionUpdateStep returns SKIP when golang-version is disabled."""
    cfg = ModuleConfig(disable=["golang-version"])
    with patch("updater.pipeline.log_message"):
        step = GoVersionUpdateStep()
        ctx = {"module_config": cfg}
        result = await step.run(tmp_path, ctx)
    assert result.status == StepStatus.SKIP


async def test_go_dep_step_skipped_when_go_dependencies_disabled(tmp_path):
    """GoDepUpdateStep returns SKIP when go-dependencies is disabled."""
    cfg = ModuleConfig(disable=["go-dependencies"])
    with patch("updater.pipeline.log_message"):
        step = GoDepUpdateStep()
        ctx = {"module_config": cfg}
        result = await step.run(tmp_path, ctx)
    assert result.status == StepStatus.SKIP


async def test_python_version_step_skipped_when_python_version_disabled(tmp_path):
    """PythonVersionUpdateStep returns SKIP when python-version is disabled."""
    cfg = ModuleConfig(disable=["python-version"])
    with patch("updater.pipeline.log_message"):
        step = PythonVersionUpdateStep()
        ctx = {"module_config": cfg}
        result = await step.run(tmp_path, ctx)
    assert result.status == StepStatus.SKIP


async def test_python_dep_step_skipped_when_python_version_disabled(tmp_path):
    """PythonDepUpdateStep returns SKIP when python-version is disabled."""
    cfg = ModuleConfig(disable=["python-version"])
    with patch("updater.pipeline.log_message"):
        step = PythonDepUpdateStep()
        ctx = {"module_config": cfg}
        result = await step.run(tmp_path, ctx)
    assert result.status == StepStatus.SKIP


async def test_pipeline_loads_config_and_stores_in_context(tmp_path):
    """Pipeline.run() loads module config and stores it in context."""
    from updater.pipeline import Step

    class TrackStep(Step):
        async def run(self, module_path, context):
            context["saw_module_config"] = "module_config" in context
            return StepResult(StepStatus.SUCCESS)

    with patch("updater.pipeline.log_message"):
        pipeline = Pipeline([TrackStep()])
        ctx = {}
        await pipeline.run(tmp_path, ctx)

    assert ctx.get("saw_module_config") is True
    assert isinstance(ctx.get("module_config"), ModuleConfig)


async def test_pipeline_config_disabled_step_continues(tmp_path):
    """Pipeline continues to subsequent steps when a config-disabled step returns SKIP."""
    (tmp_path / ".updater.yaml").write_text("disable:\n  - golang-version\n")

    ran_next = {}

    from updater.pipeline import Step

    class _TrackStep(Step):
        async def run(self, module_path, context):
            ran_next["ran"] = True
            return StepResult(StepStatus.SUCCESS)

    with patch("updater.pipeline.log_message"):
        pipeline = Pipeline([GoVersionUpdateStep(), _TrackStep()])
        ctx = {}
        result = await pipeline.run(tmp_path, ctx)

    assert ran_next.get("ran") is True
    assert result.status == StepStatus.SUCCESS
