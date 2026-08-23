"""Integration tests for the infra-tier chain's managed (in-process) run.

These tests drive the real ``InfraChain.run()`` control flow end-to-end with
the four handlers stubbed and a fake clock, proving the state sequence, the
manifest gate's retry/abort semantics, the parallel tail, and the dry-run plan
output. Unlike ``test_chain.py`` (per-helper unit tests), here the real
``wait_for_pr_merge`` / ``wait_for_manifest`` pollers execute against a patched
``_run_probe`` and injected fake ``now``/``sleep`` — no real gh, docker, git,
or wall-clock sleeping.
"""

import ast
import re
import subprocess
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from updater.chain import (
    MANIFEST_TIMEOUT_SECONDS,
    ChainStep,
    InfraChain,
    wait_for_pr_merge,
)

# The exact shell commands the chain builds from validated constants and the
# gh-resolved tag (the shell-command boundary asserted in test 1 and test 7).
GH_PR_LIST_CMD = (
    "gh pr list --repo bborbe/claude-yolo --search 'head:updater' --state open --json url"
)
MANIFEST_IMAGE = "docker.io/bborbe/claude-yolo:v0.16.0"


def _probe(returncode: int, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess:
    """Build a CompletedProcess with the given result for use as a probe result.

    Args:
        returncode: Exit code the probe reports
        stdout: Captured stdout
        stderr: Captured stderr

    Returns:
        A CompletedProcess with the given result
    """
    return subprocess.CompletedProcess(
        args=("probe",), returncode=returncode, stdout=stdout, stderr=stderr
    )


class _FakeClock:
    """A monotonic clock whose time advances exactly with the injected sleeps."""

    def __init__(self) -> None:
        self.t = 0.0

    def now(self) -> float:
        """Return the current fake time in seconds."""
        return self.t

    def advance(self, seconds: float) -> None:
        """Advance the fake time by ``seconds``."""
        self.t += seconds


def _make_fake_sleep(clock: _FakeClock) -> Callable[[float], None]:
    """Return a sleep function that advances ``clock`` by the requested delay."""

    def _sleep(seconds: float) -> None:
        clock.advance(seconds)

    return _sleep


def _make_jump_sleep(clock: _FakeClock, jump: float) -> Callable[[float], None]:
    """Return a sleep that advances ``clock`` by a fixed jump, ignoring the delay."""

    def _sleep(_seconds: float) -> None:
        clock.advance(jump)

    return _sleep


def _make_probe_dispatcher(
    pr_results: list[subprocess.CompletedProcess],
    manifest_results: list[subprocess.CompletedProcess],
) -> tuple[Callable[..., subprocess.CompletedProcess], dict[str, list[str]]]:
    """Build a ``_run_probe`` side-effect that dispatches gh vs docker probes.

    Args:
        pr_results: Results to return for each ``gh pr list`` call, in order.
        manifest_results: Results to return for each ``docker manifest inspect``
            call, in order; once exhausted, every further call fails with
            returncode 1 (the manifest is never present).

    Returns:
        (side_effect, calls): ``side_effect`` is safe to patch over
        ``updater.chain._run_probe``; ``calls`` maps ``"gh"``/``"docker"`` to
        the exact command strings observed, for the shell-command boundary
        assertions.
    """
    calls: dict[str, list[str]] = {"gh": [], "docker": []}

    def _side_effect(
        cmd: str, *, cwd: Path, step: ChainStep, log_func: Callable[..., None]
    ) -> subprocess.CompletedProcess:
        del cwd, step, log_func
        if cmd.startswith("gh pr list"):
            calls["gh"].append(cmd)
            return pr_results.pop(0)
        if cmd.startswith("docker manifest inspect"):
            calls["docker"].append(cmd)
            return manifest_results.pop(0) if manifest_results else _probe(1)
        raise AssertionError(f"unexpected probe command: {cmd!r}")

    return _side_effect, calls


@contextmanager
def _capture_log() -> Iterator[list[str]]:
    """Capture every ``updater.chain.log_message`` call into a list.

    Yields:
        The list of logged messages, in order.
    """
    lines: list[str] = []

    def _log(message: str, to_console: bool = True) -> None:
        del to_console
        lines.append(message)

    with patch("updater.chain.log_message", side_effect=_log):
        yield lines


@contextmanager
def _stub_handlers(
    exit_codes: dict[str, int] | None = None,
) -> Iterator[list[tuple[str, tuple, dict]]]:
    """Patch the four handler classes and record every invocation.

    Args:
        exit_codes: Mapping of handler name (claude-yolo, dark-factory,
            bundlewrap, trading) to the exit code its run() should return.
            Missing names default to 0.

    Yields:
        ``invocations`` — a list of ``(name, args, kwargs)`` tuples in call
        order, so tests can assert ordering and that the parallel tail ran.
    """
    exit_codes = exit_codes or {}
    invocations: list[tuple[str, tuple, dict]] = []

    def _make_run(name: str) -> Callable[..., int]:
        def _run(*args, **kwargs) -> int:
            invocations.append((name, args, kwargs))
            return exit_codes.get(name, 0)

        return _run

    with (
        patch("updater.chain.ClaudeYoloHandler") as mock_claude,
        patch("updater.chain.DarkFactoryHandler") as mock_dark,
        patch("updater.chain.BundleWrapHandler") as mock_bw,
        patch("updater.chain.TradingHandler") as mock_trading,
    ):
        mock_claude.return_value.run.side_effect = _make_run("claude-yolo")
        mock_dark.return_value.run.side_effect = _make_run("dark-factory")
        mock_bw.return_value.run.side_effect = _make_run("bundlewrap")
        mock_trading.return_value.run.side_effect = _make_run("trading")
        yield invocations


def _find_line(lines: list[str], needle: str) -> str:
    """Return the first log line containing ``needle``; fail loudly if absent.

    Args:
        lines: Captured log lines
        needle: Substring to search for

    Returns:
        The first matching line

    Raises:
        AssertionError: If no line contains ``needle``
    """
    for line in lines:
        if needle in line:
            return line
    raise AssertionError(f"no log line contains {needle!r}; got:\n" + "\n".join(lines))


async def test_full_chain_happy_path_state_sequence(tmp_path):
    """Test a full successful run logs states in order, retries the gate, and
    uses exactly the shell commands built from constants + the gh-resolved tag."""
    open_pr = _probe(0, stdout='[{"url": "https://github.com/bborbe/claude-yolo/pull/7"}]')
    probe_side_effect, probe_calls = _make_probe_dispatcher(
        pr_results=[open_pr, _probe(0, stdout="[]")],
        manifest_results=[_probe(1), _probe(1), _probe(0)],
    )
    clock = _FakeClock()
    with (
        _capture_log() as lines,
        _stub_handlers() as invocations,
        patch("updater.chain._docker_available", return_value=True),
        patch("updater.chain.resolve_latest_claude_yolo_tag", return_value="v0.16.0"),
        patch("updater.chain._run_probe", side_effect=probe_side_effect),
    ):
        chain = InfraChain(
            go_version="1.28.0",
            dry_run=False,
            claude_yolo_checkout=tmp_path,
            dark_factory_checkout=tmp_path,
            bundlewrap_checkout=tmp_path,
            trading_checkout=tmp_path,
            now=clock.now,
            sleep=_make_fake_sleep(clock),
        )
        rc = await chain.run()

    assert rc == 0
    state_values = [m.split("→ ", 1)[1] for m in lines if m.startswith("[chain] state → ")]
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
    assert any("waiting for claude-yolo PR merge:" in m and "pull/7" in m for m in lines)
    unknown_lines = [m for m in lines if "manifest unknown" in m]
    assert len(unknown_lines) >= 2
    elapsed = [int(re.search(r"elapsed (\d+)s", line).group(1)) for line in unknown_lines]
    assert all(b > a for a, b in zip(elapsed, elapsed[1:], strict=False))
    assert any("manifest present" in m for m in lines)

    names = [name for name, _args, _kwargs in invocations]
    assert names[0] == "claude-yolo"
    assert names[1] == "dark-factory"
    assert set(names[2:]) == {"bundlewrap", "trading"}
    claude = next(inv for inv in invocations if inv[0] == "claude-yolo")
    assert claude[2] == {"dry_run": False, "go_version": "1.28.0"}
    dark_factory = next(inv for inv in invocations if inv[0] == "dark-factory")
    assert dark_factory[2] == {"dry_run": False, "claude_yolo_tag": "v0.16.0"}

    assert probe_calls["gh"] == [GH_PR_LIST_CMD, GH_PR_LIST_CMD]
    assert probe_calls["docker"] == [
        f"docker manifest inspect {MANIFEST_IMAGE}",
        f"docker manifest inspect {MANIFEST_IMAGE}",
        f"docker manifest inspect {MANIFEST_IMAGE}",
    ]


async def test_full_chain_abort_on_manifest_timeout(tmp_path):
    """Test the manifest gate aborts the chain after the 30-minute budget."""
    probe_side_effect, _probe_calls = _make_probe_dispatcher(
        pr_results=[_probe(0, stdout="[]")],
        manifest_results=[_probe(1)],
    )
    clock = _FakeClock()
    with (
        _capture_log() as lines,
        _stub_handlers() as invocations,
        patch("updater.chain._docker_available", return_value=True),
        patch("updater.chain.resolve_latest_claude_yolo_tag", return_value="v0.16.0"),
        patch("updater.chain._run_probe", side_effect=probe_side_effect),
    ):
        chain = InfraChain(
            go_version="1.28.0",
            dry_run=False,
            claude_yolo_checkout=tmp_path,
            dark_factory_checkout=tmp_path,
            bundlewrap_checkout=tmp_path,
            trading_checkout=tmp_path,
            now=clock.now,
            sleep=_make_jump_sleep(clock, MANIFEST_TIMEOUT_SECONDS),
        )
        rc = await chain.run()

    assert rc == 1
    abort = _find_line(lines, "Chain aborted at step manifest-verify")
    assert MANIFEST_IMAGE in abort
    assert "1800s" in abort
    names = [name for name, _args, _kwargs in invocations]
    assert names == ["claude-yolo"]


async def test_full_chain_abort_on_handler_failure_names_step(tmp_path):
    """Test a dark-factory handler failure aborts naming the step."""
    probe_side_effect, _probe_calls = _make_probe_dispatcher(
        pr_results=[_probe(0, stdout="[]")],
        manifest_results=[_probe(0)],
    )
    clock = _FakeClock()
    with (
        _capture_log() as lines,
        _stub_handlers({"dark-factory": 1}) as invocations,
        patch("updater.chain._docker_available", return_value=True),
        patch("updater.chain.resolve_latest_claude_yolo_tag", return_value="v0.16.0"),
        patch("updater.chain._run_probe", side_effect=probe_side_effect),
    ):
        chain = InfraChain(
            go_version="1.28.0",
            dry_run=False,
            claude_yolo_checkout=tmp_path,
            dark_factory_checkout=tmp_path,
            bundlewrap_checkout=tmp_path,
            trading_checkout=tmp_path,
            now=clock.now,
            sleep=_make_fake_sleep(clock),
        )
        rc = await chain.run()

    assert rc == 1
    _find_line(lines, "Chain aborted at step dark-factory")
    names = [name for name, _args, _kwargs in invocations]
    assert names == ["claude-yolo", "dark-factory"]


async def test_full_chain_parallel_tail_one_fails_other_runs(tmp_path):
    """Test a bundlewrap failure aborts naming bundlewrap while trading still runs."""
    probe_side_effect, _probe_calls = _make_probe_dispatcher(
        pr_results=[_probe(0, stdout="[]")],
        manifest_results=[_probe(0)],
    )
    clock = _FakeClock()
    with (
        _capture_log() as lines,
        _stub_handlers({"bundlewrap": 1}) as invocations,
        patch("updater.chain._docker_available", return_value=True),
        patch("updater.chain.resolve_latest_claude_yolo_tag", return_value="v0.16.0"),
        patch("updater.chain._run_probe", side_effect=probe_side_effect),
    ):
        chain = InfraChain(
            go_version="1.28.0",
            dry_run=False,
            claude_yolo_checkout=tmp_path,
            dark_factory_checkout=tmp_path,
            bundlewrap_checkout=tmp_path,
            trading_checkout=tmp_path,
            now=clock.now,
            sleep=_make_fake_sleep(clock),
        )
        rc = await chain.run()

    assert rc == 1
    _find_line(lines, "Chain aborted at step bundlewrap")
    names = [name for name, _args, _kwargs in invocations]
    # The successful trading branch still ran (its PR is opened and left) —
    # the chain never rolls back a successful parallel branch.
    assert "trading" in names
    assert "bundlewrap" in names


async def test_full_chain_docker_unavailable_aborts(tmp_path):
    """Test a missing docker CLI aborts the chain at the manifest gate."""
    probe_side_effect, _probe_calls = _make_probe_dispatcher(
        pr_results=[_probe(0, stdout="[]")],
        manifest_results=[_probe(0)],
    )
    clock = _FakeClock()
    with (
        _capture_log() as lines,
        _stub_handlers() as invocations,
        patch("updater.chain._docker_available", return_value=False),
        patch("updater.chain.resolve_latest_claude_yolo_tag", return_value="v0.16.0"),
        patch("updater.chain._run_probe", side_effect=probe_side_effect),
    ):
        chain = InfraChain(
            go_version="1.28.0",
            dry_run=False,
            claude_yolo_checkout=tmp_path,
            dark_factory_checkout=tmp_path,
            bundlewrap_checkout=tmp_path,
            trading_checkout=tmp_path,
            now=clock.now,
            sleep=_make_fake_sleep(clock),
        )
        rc = await chain.run()

    assert rc == 1
    abort = _find_line(lines, "Chain aborted at step manifest-verify")
    assert "docker" in abort
    names = [name for name, _args, _kwargs in invocations]
    assert names == ["claude-yolo"]


async def test_full_chain_dry_run_exact_output():
    """Test the dry-run plan output is exactly the ordered five steps + final line."""
    with (
        _capture_log() as lines,
        _stub_handlers() as invocations,
        patch("updater.chain.resolve_latest_claude_yolo_tag") as mock_resolve,
        patch("updater.chain._run_probe") as mock_probe,
    ):
        rc = await InfraChain(go_version="1.28.0", dry_run=True).run()

    assert rc == 0
    plan_lines = [m for m in lines if m.startswith("Step ") or m.startswith("(dry-run")]
    assert plan_lines == [
        "Step 1: claude-yolo — bump ARG GO_VERSION in bborbe/claude-yolo Dockerfile (opens PR)",
        "Step 2: manifest-verify — docker manifest inspect "
        "docker.io/bborbe/claude-yolo:<tag> (retry every 30s up to 30 min)",
        "Step 3: dark-factory — bump DefaultContainerImage in bborbe/dark-factory pkg/const.go",
        "Step 4: bundlewrap — bump default_golang_version in BundleWrap "
        "bundles/golang/items.py (parallel with trading)",
        "Step 5: trading — bump Go version across bborbe/trading monorepo "
        "(parallel with bundlewrap)",
        "(dry-run — no handler invoked, no side effects)",
    ]
    assert invocations == []
    mock_resolve.assert_not_called()
    mock_probe.assert_not_called()


def test_chain_shell_command_boundaries(tmp_path):
    """Test gh stdout is parsed as JSON data, never interpolated into a command."""
    malicious = (
        '[{"url": "https://github.com/bborbe/claude-yolo/pull/7$(touch /tmp/pwned);rm -rf ~"}]'
    )
    calls: list[str] = []
    lines: list[str] = []

    def _log(message: str, to_console: bool = True) -> None:
        del to_console
        lines.append(message)

    def _guarded_probe(
        cmd: str, *, cwd: Path, step: ChainStep, log_func: Callable[..., None]
    ) -> subprocess.CompletedProcess:
        del cwd, step, log_func
        calls.append(cmd)
        # The URL lives only in the probe response; a command fragment must
        # never be derived from it.
        assert "touch" not in cmd and "rm" not in cmd
        return _probe(0, stdout=malicious) if len(calls) == 1 else _probe(0, stdout="[]")

    with patch("updater.chain._run_probe", side_effect=_guarded_probe):
        wait_for_pr_merge(tmp_path, sleep=lambda d: None, log_func=_log)

    # The response was json.loads-ed and the URL logged as data.
    assert any("waiting for claude-yolo PR merge:" in m and "$(touch" in m for m in lines)
    assert calls == [GH_PR_LIST_CMD, GH_PR_LIST_CMD]


def test_chain_consumes_handler_classes_not_reimplementations():
    """Test chain.py imports the four handler classes rather than reimplementing them."""
    chain_src = Path(__file__).resolve().parents[1] / "src" / "updater" / "chain.py"
    tree = ast.parse(chain_src.read_text())

    handler_modules = {
        "ClaudeYoloHandler": "claude_yolo_handler",
        "DarkFactoryHandler": "dark_factory_handler",
        "BundleWrapHandler": "bundlewrap_handler",
        "TradingHandler": "trading_handler",
    }
    imported: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            for alias in node.names:
                if alias.name in handler_modules:
                    imported[alias.name] = node.module.lstrip(".")

    assert imported == handler_modules
    class_names = {node.name for node in ast.walk(tree) if isinstance(node, ast.ClassDef)}
    assert not (set(handler_modules) & class_names)


def test_handler_dry_run_contracts_intact():
    """Test all four handler modules still expose the keyword-only dry_run contract."""
    src_dir = Path(__file__).resolve().parents[1] / "src" / "updater"
    handler_classes = {
        "claude_yolo_handler": "ClaudeYoloHandler",
        "dark_factory_handler": "DarkFactoryHandler",
        "bundlewrap_handler": "BundleWrapHandler",
        "trading_handler": "TradingHandler",
    }
    for module_name, class_name in handler_classes.items():
        source = (src_dir / f"{module_name}.py").read_text()
        tree = ast.parse(source)
        run_defs = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == "run"
        ]
        assert run_defs, f"{module_name}.py no longer defines a run method"
        run = run_defs[0]
        kwonly = [arg.arg for arg in run.args.kwonlyargs]
        assert class_name in source
        assert "dry_run" in kwonly, f"{module_name}.py run() lost its keyword-only dry_run"
        assert "*, dry_run:" in source
