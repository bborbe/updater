"""Tests for the infra-tier chain state machine."""

import re
import subprocess
from unittest.mock import Mock, patch

import pytest

from updater.chain import (
    PR_MERGE_INTERVAL_SECONDS,
    ChainAbort,
    ChainState,
    ChainStep,
    InfraChain,
    _docker_available,
    _run_probe,
    wait_for_manifest,
    wait_for_pr_merge,
)


def _completed(returncode: int, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess:
    """Build a CompletedProcess with the given result for use as a probe result."""
    return subprocess.CompletedProcess(
        args=["probe"], returncode=returncode, stdout=stdout, stderr=stderr
    )


def _capture_messages() -> tuple[list[str], Mock]:
    """Return a message list and a log side-effect that fills it."""
    messages: list[str] = []

    def _log(message: str, *args, **kwargs) -> None:
        messages.append(message)

    return messages, _log


class _FakeClock:
    """Monotonic clock whose sleep advances time and records calls."""

    def __init__(self) -> None:
        self.t = 0.0
        self.sleeps: list[float] = []

    def now(self) -> float:
        return self.t

    def sleep(self, delay: float) -> None:
        self.sleeps.append(delay)
        self.t += delay


class _JumpClock:
    """Monotonic clock whose first sleep jumps past the manifest timeout."""

    def __init__(self) -> None:
        self.t = 0.0

    def now(self) -> float:
        return self.t

    def sleep(self, delay: float) -> None:
        self.t += 1800.0


def test_plan_order():
    """Test plan() returns the five steps in the fixed runbook order."""
    assert InfraChain(go_version="1.28.0", dry_run=True).plan() == [
        "claude-yolo",
        "manifest-verify",
        "dark-factory",
        "bundlewrap",
        "trading",
    ]


async def test_validate_go_version_rejects():
    """Test an invalid go_version returns 1 before any state transition."""
    rc = await InfraChain(go_version="1.28", dry_run=True).run()

    assert rc == 1


def test_chain_steps_and_states():
    """Test the enum values match the spec's fixed step and state order."""
    assert [s.value for s in ChainStep] == [
        "claude-yolo",
        "manifest-verify",
        "dark-factory",
        "bundlewrap",
        "trading",
    ]
    assert [s.value for s in ChainState] == [
        "start",
        "claude-yolo",
        "waiting-pr-merge",
        "waiting-publish",
        "manifest-gate",
        "dark-factory",
        "parallel(bundlewrap, trading)",
        "done",
    ]


async def test_run_dry_run_prints_plan_no_side_effects():
    """Test a dry run prints the five-step plan and invokes no handler."""
    messages, log_side_effect = _capture_messages()
    with (
        patch("updater.chain.ClaudeYoloHandler") as mock_claude,
        patch("updater.chain.DarkFactoryHandler") as mock_dark,
        patch("updater.chain.BundleWrapHandler") as mock_bw,
        patch("updater.chain.TradingHandler") as mock_trading,
        patch("updater.chain.log_message", side_effect=log_side_effect),
    ):
        rc = await InfraChain(go_version="1.28.0", dry_run=True).run()

    assert rc == 0
    step_lines = [m for m in messages if m.startswith("Step ")]
    assert len(step_lines) == 5
    plan = " ".join(step_lines)
    positions = [
        plan.index(name)
        for name in ["claude-yolo", "manifest-verify", "dark-factory", "bundlewrap", "trading"]
    ]
    assert positions == sorted(positions)
    assert any("(dry-run — no handler invoked, no side effects)" in m for m in messages)
    mock_claude.assert_not_called()
    mock_dark.assert_not_called()
    mock_bw.assert_not_called()
    mock_trading.assert_not_called()


async def test_run_real_missing_checkout_aborts(tmp_path):
    """Test a real run without every checkout path aborts before any handler."""
    messages, log_side_effect = _capture_messages()
    with (
        patch("updater.chain.ClaudeYoloHandler"),
        patch("updater.chain.DarkFactoryHandler"),
        patch("updater.chain.BundleWrapHandler"),
        patch("updater.chain.TradingHandler"),
        patch("updater.chain.log_message", side_effect=log_side_effect),
    ):
        chain = InfraChain(
            go_version="1.28.0",
            dry_run=False,
            claude_yolo_checkout=tmp_path,
            dark_factory_checkout=tmp_path,
            bundlewrap_checkout=None,
            trading_checkout=tmp_path,
        )
        rc = await chain.run()

    assert rc == 1
    assert any("bundlewrap" in m for m in messages)


async def test_run_real_claude_yolo_failure_aborts(tmp_path):
    """Test a claude-yolo handler failure aborts the chain at that step."""
    messages, log_side_effect = _capture_messages()
    with (
        patch("updater.chain.ClaudeYoloHandler") as mock_claude,
        patch("updater.chain.DarkFactoryHandler") as mock_dark,
        patch("updater.chain.BundleWrapHandler") as mock_bw,
        patch("updater.chain.TradingHandler") as mock_trading,
        patch("updater.chain.wait_for_pr_merge"),
        patch("updater.chain.wait_for_manifest"),
        patch("updater.chain._docker_available"),
        patch("updater.chain.resolve_latest_claude_yolo_tag"),
        patch("updater.chain.log_message", side_effect=log_side_effect),
    ):
        mock_claude.return_value.run.return_value = 1
        rc = await InfraChain(
            go_version="1.28.0",
            dry_run=False,
            claude_yolo_checkout=tmp_path,
            dark_factory_checkout=tmp_path,
            bundlewrap_checkout=tmp_path,
            trading_checkout=tmp_path,
        ).run()

    assert rc == 1
    assert any("claude-yolo" in m and "aborted" in m for m in messages)
    mock_dark.assert_not_called()
    mock_bw.assert_not_called()
    mock_trading.assert_not_called()


async def test_run_real_tag_resolution_failure_aborts(tmp_path):
    """Test a gh tag-resolution failure aborts naming the manifest-verify step."""
    messages, log_side_effect = _capture_messages()
    with (
        patch("updater.chain.ClaudeYoloHandler") as mock_claude,
        patch("updater.chain.DarkFactoryHandler"),
        patch("updater.chain.BundleWrapHandler"),
        patch("updater.chain.TradingHandler"),
        patch("updater.chain.wait_for_pr_merge"),
        patch("updater.chain.wait_for_manifest"),
        patch("updater.chain._docker_available"),
        patch(
            "updater.chain.resolve_latest_claude_yolo_tag",
            side_effect=RuntimeError("gh: not authenticated"),
        ),
        patch("updater.chain.log_message", side_effect=log_side_effect),
    ):
        mock_claude.return_value.run.return_value = 0
        rc = await InfraChain(
            go_version="1.28.0",
            dry_run=False,
            claude_yolo_checkout=tmp_path,
            dark_factory_checkout=tmp_path,
            bundlewrap_checkout=tmp_path,
            trading_checkout=tmp_path,
        ).run()

    assert rc == 1
    assert any("manifest-verify" in m and "aborted" in m for m in messages)


async def test_run_real_dark_factory_failure_aborts(tmp_path):
    """Test a dark-factory handler failure aborts the chain at that step."""
    messages, log_side_effect = _capture_messages()
    with (
        patch("updater.chain.ClaudeYoloHandler") as mock_claude,
        patch("updater.chain.DarkFactoryHandler") as mock_dark,
        patch("updater.chain.BundleWrapHandler") as mock_bw,
        patch("updater.chain.TradingHandler") as mock_trading,
        patch("updater.chain.wait_for_pr_merge"),
        patch("updater.chain.wait_for_manifest"),
        patch("updater.chain._docker_available", return_value=True),
        patch("updater.chain.resolve_latest_claude_yolo_tag", return_value="v0.16.0"),
        patch("updater.chain.log_message", side_effect=log_side_effect),
    ):
        mock_claude.return_value.run.return_value = 0
        mock_dark.return_value.run.return_value = 1
        rc = await InfraChain(
            go_version="1.28.0",
            dry_run=False,
            claude_yolo_checkout=tmp_path,
            dark_factory_checkout=tmp_path,
            bundlewrap_checkout=tmp_path,
            trading_checkout=tmp_path,
        ).run()

    assert rc == 1
    assert any("dark-factory" in m and "aborted" in m for m in messages)
    mock_bw.assert_not_called()
    mock_trading.assert_not_called()


async def test_run_real_parallel_one_fails(tmp_path):
    """Test a bundlewrap failure in the parallel tail aborts naming bundlewrap."""
    messages, log_side_effect = _capture_messages()
    with (
        patch("updater.chain.ClaudeYoloHandler") as mock_claude,
        patch("updater.chain.DarkFactoryHandler") as mock_dark,
        patch("updater.chain.BundleWrapHandler") as mock_bw,
        patch("updater.chain.TradingHandler") as mock_trading,
        patch("updater.chain.wait_for_pr_merge"),
        patch("updater.chain.wait_for_manifest"),
        patch("updater.chain._docker_available", return_value=True),
        patch("updater.chain.resolve_latest_claude_yolo_tag", return_value="v0.16.0"),
        patch("updater.chain.log_message", side_effect=log_side_effect),
    ):
        mock_claude.return_value.run.return_value = 0
        mock_dark.return_value.run.return_value = 0
        mock_bw.return_value.run.return_value = 1
        mock_trading.return_value.run.return_value = 0
        rc = await InfraChain(
            go_version="1.28.0",
            dry_run=False,
            claude_yolo_checkout=tmp_path,
            dark_factory_checkout=tmp_path,
            bundlewrap_checkout=tmp_path,
            trading_checkout=tmp_path,
        ).run()

    assert rc == 1
    assert any("bundlewrap" in m and "aborted" in m for m in messages)
    # The other parallel branch still ran — a failure never cancels it.
    mock_trading.return_value.run.assert_called_once()


async def test_run_real_parallel_unexpected_exception_aborts(tmp_path):
    """Test an unexpected exception in the parallel tail aborts naming trading."""
    messages, log_side_effect = _capture_messages()
    with (
        patch("updater.chain.ClaudeYoloHandler") as mock_claude,
        patch("updater.chain.DarkFactoryHandler") as mock_dark,
        patch("updater.chain.BundleWrapHandler") as mock_bw,
        patch("updater.chain.TradingHandler") as mock_trading,
        patch("updater.chain.wait_for_pr_merge"),
        patch("updater.chain.wait_for_manifest"),
        patch("updater.chain._docker_available", return_value=True),
        patch("updater.chain.resolve_latest_claude_yolo_tag", return_value="v0.16.0"),
        patch("updater.chain.log_message", side_effect=log_side_effect),
    ):
        mock_claude.return_value.run.return_value = 0
        mock_dark.return_value.run.return_value = 0
        mock_bw.return_value.run.return_value = 0
        mock_trading.return_value.run.side_effect = ValueError("boom")
        rc = await InfraChain(
            go_version="1.28.0",
            dry_run=False,
            claude_yolo_checkout=tmp_path,
            dark_factory_checkout=tmp_path,
            bundlewrap_checkout=tmp_path,
            trading_checkout=tmp_path,
        ).run()

    assert rc == 1
    assert any("trading" in m and "aborted" in m for m in messages)


async def test_run_real_full_sequence_order_and_tag(tmp_path):
    """Test a full successful run transitions states in order and passes the tag."""
    messages, log_side_effect = _capture_messages()
    order: list[str] = []

    def _recorded(name: str):
        def _run(*args, **kwargs) -> int:
            order.append(name)
            return 0

        return _run

    with (
        patch("updater.chain.ClaudeYoloHandler") as mock_claude,
        patch("updater.chain.DarkFactoryHandler") as mock_dark,
        patch("updater.chain.BundleWrapHandler") as mock_bw,
        patch("updater.chain.TradingHandler") as mock_trading,
        patch("updater.chain.wait_for_pr_merge"),
        patch("updater.chain.wait_for_manifest"),
        patch("updater.chain._docker_available", return_value=True),
        patch("updater.chain.resolve_latest_claude_yolo_tag", return_value="v0.16.0"),
        patch("updater.chain.log_message", side_effect=log_side_effect),
    ):
        mock_claude.return_value.run.side_effect = _recorded("claude-yolo")
        mock_dark.return_value.run.side_effect = _recorded("dark-factory")
        mock_bw.return_value.run.side_effect = _recorded("bundlewrap")
        mock_trading.return_value.run.side_effect = _recorded("trading")
        rc = await InfraChain(
            go_version="1.28.0",
            dry_run=False,
            claude_yolo_checkout=tmp_path,
            dark_factory_checkout=tmp_path,
            bundlewrap_checkout=tmp_path,
            trading_checkout=tmp_path,
        ).run()

    assert rc == 0
    state_values = [m.split("→ ")[1] for m in messages if m.startswith("[chain] state → ")]
    assert state_values == [
        "start",
        "claude-yolo",
        "waiting-pr-merge",
        "waiting-publish",
        "manifest-gate",
        "dark-factory",
        "parallel(bundlewrap, trading)",
        "done",
    ]
    mock_dark.return_value.run.assert_called_once_with(
        tmp_path, dry_run=False, claude_yolo_tag="v0.16.0"
    )
    assert order[0] == "claude-yolo"
    assert order[1] == "dark-factory"
    assert set(order[2:]) == {"bundlewrap", "trading"}


async def test_run_real_docker_unavailable_aborts(tmp_path):
    """Test a missing docker CLI aborts at the manifest gate."""
    messages, log_side_effect = _capture_messages()
    with (
        patch("updater.chain.ClaudeYoloHandler") as mock_claude,
        patch("updater.chain.DarkFactoryHandler") as mock_dark,
        patch("updater.chain.BundleWrapHandler") as mock_bw,
        patch("updater.chain.TradingHandler") as mock_trading,
        patch("updater.chain.wait_for_pr_merge"),
        patch("updater.chain.wait_for_manifest"),
        patch("updater.chain._docker_available", return_value=False),
        patch("updater.chain.resolve_latest_claude_yolo_tag", return_value="v0.16.0"),
        patch("updater.chain.log_message", side_effect=log_side_effect),
    ):
        mock_claude.return_value.run.return_value = 0
        rc = await InfraChain(
            go_version="1.28.0",
            dry_run=False,
            claude_yolo_checkout=tmp_path,
            dark_factory_checkout=tmp_path,
            bundlewrap_checkout=tmp_path,
            trading_checkout=tmp_path,
        ).run()

    assert rc == 1
    assert any("manifest-verify" in m and "docker" in m for m in messages)
    mock_dark.assert_not_called()
    mock_bw.assert_not_called()
    mock_trading.assert_not_called()


def test_wait_for_pr_merge_blocks_until_merged(tmp_path):
    """Test the PR-merge poll blocks on an open PR then proceeds once merged."""
    messages, log_side_effect = _capture_messages()
    sleeps: list[float] = []
    probe_results = [
        _completed(0, stdout='[{"url": "https://github.com/bborbe/claude-yolo/pull/7"}]'),
        _completed(0, stdout="[]"),
    ]
    with (
        patch("updater.chain._run_probe", side_effect=probe_results),
        patch("updater.chain.log_message", side_effect=log_side_effect),
    ):
        wait_for_pr_merge(tmp_path, sleep=lambda d: sleeps.append(d), log_func=log_side_effect)

    assert any("waiting for claude-yolo PR merge" in m and "pull/7" in m for m in messages)
    assert any("claude-yolo PR merged — proceeding" in m for m in messages)
    assert sleeps == [PR_MERGE_INTERVAL_SECONDS]


def test_wait_for_pr_merge_rate_limit_backs_off(tmp_path):
    """Test a 403 rate limit backs off instead of aborting."""
    messages, log_side_effect = _capture_messages()
    sleeps: list[float] = []
    probe_results = [
        _completed(1, stderr="API rate limit exceeded (403)"),
        _completed(0, stdout="[]"),
    ]
    with (
        patch("updater.chain._run_probe", side_effect=probe_results),
        patch("updater.chain.random.uniform", return_value=0.0),
        patch("updater.chain.log_message", side_effect=log_side_effect),
    ):
        wait_for_pr_merge(tmp_path, sleep=lambda d: sleeps.append(d), log_func=log_side_effect)

    assert any("rate limit" in m for m in messages)
    assert sleeps == [PR_MERGE_INTERVAL_SECONDS]
    assert any("claude-yolo PR merged — proceeding" in m for m in messages)


def test_wait_for_pr_merge_persistent_failure_aborts(tmp_path):
    """Test a persistent non-rate-limit gh failure aborts naming claude-yolo."""
    probe = _completed(1, stderr="gh: not authenticated")
    with (
        patch("updater.chain._run_probe", return_value=probe),
        patch("updater.chain.log_message"),
    ):
        with pytest.raises(ChainAbort) as exc_info:
            wait_for_pr_merge(tmp_path, sleep=lambda d: None)

    assert "claude-yolo" in str(exc_info.value)


def test_wait_for_pr_merge_malformed_json_aborts(tmp_path):
    """Test malformed gh JSON aborts naming claude-yolo."""
    probe = _completed(0, stdout="not json")
    with (
        patch("updater.chain._run_probe", return_value=probe),
        patch("updater.chain.log_message"),
    ):
        with pytest.raises(ChainAbort) as exc_info:
            wait_for_pr_merge(tmp_path, sleep=lambda d: None)

    assert "claude-yolo" in str(exc_info.value)


def test_wait_for_manifest_retries_then_present(tmp_path):
    """Test the manifest gate retries with strictly increasing elapsed, then proceeds."""
    messages, log_side_effect = _capture_messages()
    clock = _FakeClock()
    image = "docker.io/bborbe/claude-yolo:v0.16.0"
    probe_results = [
        _completed(1),
        _completed(1),
        _completed(0),
    ]
    with (
        patch("updater.chain._run_probe", side_effect=probe_results),
        patch("updater.chain.log_message", side_effect=log_side_effect),
    ):
        wait_for_manifest(
            tmp_path, image, now=clock.now, sleep=clock.sleep, log_func=log_side_effect
        )

    unknown_lines = [m for m in messages if "manifest unknown" in m]
    assert len(unknown_lines) >= 2
    elapsed = [int(re.search(r"elapsed (\d+)s", line).group(1)) for line in unknown_lines]
    assert all(b > a for a, b in zip(elapsed, elapsed[1:], strict=False))
    assert any("manifest present" in m for m in messages)
    assert clock.sleeps == [30.0, 30.0]


def test_wait_for_manifest_timeout_aborts(tmp_path):
    """Test the manifest gate aborts naming manifest-verify once the timeout elapses."""
    image = "docker.io/bborbe/claude-yolo:v0.16.0"
    clock = _JumpClock()
    probe = _completed(1)
    with (
        patch("updater.chain._run_probe", return_value=probe),
        patch("updater.chain.log_message"),
    ):
        with pytest.raises(ChainAbort) as exc_info:
            wait_for_manifest(tmp_path, image, now=clock.now, sleep=clock.sleep)

    assert "manifest-verify" in str(exc_info.value)
    assert image in str(exc_info.value)


def test_wait_for_manifest_rate_limit_backs_off(tmp_path):
    """Test a 429 in the manifest gate backs off instead of aborting."""
    messages, log_side_effect = _capture_messages()
    clock = _FakeClock()
    probe_results = [
        _completed(1, stderr="too many requests (429)"),
        _completed(0),
    ]
    with (
        patch("updater.chain._run_probe", side_effect=probe_results),
        patch("updater.chain.random.uniform", return_value=0.0),
        patch("updater.chain.log_message", side_effect=log_side_effect),
    ):
        wait_for_manifest(
            tmp_path,
            "docker.io/bborbe/claude-yolo:v0.16.0",
            now=clock.now,
            sleep=clock.sleep,
            log_func=log_side_effect,
        )

    assert any("rate limit" in m for m in messages)
    assert clock.sleeps == [30.0]
    assert any("manifest present" in m for m in messages)


async def test_wait_for_manifest_image_boundary(tmp_path):
    """Test the manifest gate inspects exactly docker.io/bborbe/claude-yolo:<tag>."""
    with (
        patch("updater.chain.ClaudeYoloHandler") as mock_claude,
        patch("updater.chain.DarkFactoryHandler") as mock_dark,
        patch("updater.chain.BundleWrapHandler") as mock_bw,
        patch("updater.chain.TradingHandler") as mock_trading,
        patch("updater.chain.wait_for_pr_merge"),
        patch("updater.chain.wait_for_manifest") as mock_manifest,
        patch("updater.chain._docker_available", return_value=True),
        patch("updater.chain.resolve_latest_claude_yolo_tag", return_value="v0.16.0"),
    ):
        mock_claude.return_value.run.return_value = 0
        mock_dark.return_value.run.return_value = 0
        mock_bw.return_value.run.return_value = 0
        mock_trading.return_value.run.return_value = 0
        rc = await InfraChain(
            go_version="1.28.0",
            dry_run=False,
            claude_yolo_checkout=tmp_path,
            dark_factory_checkout=tmp_path,
            bundlewrap_checkout=tmp_path,
            trading_checkout=tmp_path,
        ).run()

    assert rc == 0
    mock_manifest.assert_called_once()
    args, _ = mock_manifest.call_args
    assert args[1] == "docker.io/bborbe/claude-yolo:v0.16.0"


def test_docker_available_true_and_false():
    """Test docker detection maps docker version success/failure to True/False."""
    with patch("updater.chain.run_command", return_value=Mock()):
        assert _docker_available() is True
    with patch("updater.chain.run_command", side_effect=RuntimeError("exit 127")):
        assert _docker_available() is False


def test_run_probe_returns_result_without_raising(tmp_path):
    """Test _run_probe returns the CompletedProcess regardless of exit code."""
    mock_result = _completed(1, stdout="some error")
    with (
        patch("updater.chain.subprocess.run", return_value=mock_result) as mock_run,
        patch("updater.chain.log_message"),
    ):
        result = _run_probe("gh pr list", cwd=tmp_path, step=ChainStep.CLAUDE_YOLO)

    assert result is mock_result
    assert mock_run.call_args.kwargs["shell"] is True
    assert mock_run.call_args.kwargs["timeout"] == 300


def test_run_probe_timeout_aborts(tmp_path):
    """Test a hung probe aborts naming its step instead of hanging the chain."""
    with (
        patch(
            "updater.chain.subprocess.run",
            side_effect=subprocess.TimeoutExpired("gh pr list", 300),
        ),
        patch("updater.chain.log_message"),
    ):
        with pytest.raises(ChainAbort) as exc_info:
            _run_probe("gh pr list", cwd=tmp_path, step=ChainStep.CLAUDE_YOLO)

    assert "claude-yolo" in str(exc_info.value)
