"""Orchestration state machine for the infra-tier handler chain.

Chains the four infra-tier handlers (claude-yolo, dark-factory, bundlewrap,
trading) in the runbook order, with a docker.io manifest gate between the
claude-yolo publish and the dark-factory pin, per spec 004.
"""

import asyncio
import json
import random
import re
import subprocess
import time
from collections.abc import Callable
from enum import Enum
from pathlib import Path

from .bundlewrap_handler import BundleWrapHandler
from .claude_yolo_handler import CLAUDE_YOLO_REPO, ClaudeYoloHandler
from .dark_factory_handler import (
    DARK_FACTORY_REPO,
    DarkFactoryHandler,
    resolve_latest_claude_yolo_tag,
)
from .infra_tier import InfraTargetError, validate_go_version
from .log_manager import log_message, run_command
from .trading_handler import TRADING_REPO, TradingHandler

MANIFEST_IMAGE_PREFIX = "docker.io/bborbe/claude-yolo:"
MANIFEST_INTERVAL_SECONDS = 30.0
MANIFEST_TIMEOUT_SECONDS = 30 * 60  # 1800s — runbook's verify-before-proceed budget
PR_MERGE_INTERVAL_SECONDS = 60.0
RATE_LIMIT_RE = re.compile(r"(?:403|429)")


class ChainStep(Enum):
    """The five chain steps, in fixed order (the state machine never reorders)."""

    CLAUDE_YOLO = "claude-yolo"
    MANIFEST_VERIFY = "manifest-verify"
    DARK_FACTORY = "dark-factory"
    BUNDLEWRAP = "bundlewrap"
    TRADING = "trading"


class ChainState(Enum):
    """Observable chain states; every transition is logged with its value."""

    START = "start"
    CLAUDE_YOLO = "claude-yolo"
    WAITING_PR_MERGE = "waiting-pr-merge"
    WAITING_PUBLISH = "waiting-publish"
    MANIFEST_GATE = "manifest-gate"
    DARK_FACTORY = "dark-factory"
    PARALLEL = "parallel(bundlewrap, trading)"
    DONE = "done"


class ChainAbort(Exception):
    """Raised to abort the chain, naming the step that failed."""

    def __init__(self, step: ChainStep, message: str) -> None:
        self.step = step
        super().__init__(f"{step.value}: {message}")


def _run_probe(
    cmd: str,
    cwd: Path,
    step: ChainStep,
    log_func: Callable[..., None] = log_message,
) -> subprocess.CompletedProcess:
    """Run cmd and return the result WITHOUT raising on non-zero exit.

    Deliberate exception to the run_command() convention (see DoD carve-out):
    the chain's polling loops treat a non-zero exit as normal control flow and
    must inspect the output for rate-limit markers.

    Args:
        cmd: Shell command to run
        cwd: Working directory for the command
        step: Chain step that owns this probe (names a timeout abort)
        log_func: Logging function to use

    Returns:
        The CompletedProcess regardless of exit code

    Raises:
        ChainAbort: If the command times out — a hung gh/docker probe must
            escalate, not hang the chain
    """
    log_func(f"→ Running: {cmd}", to_console=False)
    try:
        return subprocess.run(
            cmd,
            shell=True,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=300,
        )
    except subprocess.TimeoutExpired:
        raise ChainAbort(step, f"{cmd} timed out after 300s") from None


def _is_rate_limited(result: subprocess.CompletedProcess) -> bool:
    """Return whether result's output indicates a GitHub/docker.io 403/429 rate limit.

    Args:
        result: CompletedProcess from a probe

    Returns:
        True if the output contains a 403/429 rate-limit marker
    """
    return bool(RATE_LIMIT_RE.search((result.stdout or "") + (result.stderr or "")))


def _backoff_sleep(
    base: float,
    sleep: Callable[[float], None],
    log_func: Callable[..., None] = log_message,
) -> None:
    """Log a rate-limit backoff and sleep base + a jitter term.

    Never aborts — a rate limit is not a step failure per the spec.

    Args:
        base: Base delay in seconds
        sleep: Sleep function (test seam)
        log_func: Logging function to use
    """
    delay = base + random.uniform(0.0, base)
    log_func(f"rate limit; backing off {delay:.0f}s", to_console=True)
    sleep(delay)


def wait_for_pr_merge(
    checkout: Path,
    *,
    interval: float = PR_MERGE_INTERVAL_SECONDS,
    sleep: Callable[[float], None] = time.sleep,
    log_func: Callable[..., None] = log_message,
) -> None:
    """Poll until no open head:updater PR remains for bborbe/claude-yolo.

    Args:
        checkout: Path to the bborbe/claude-yolo checkout (gh working dir)
        interval: Seconds between polls
        sleep: Sleep function (test seam)
        log_func: Logging function to use

    Raises:
        ChainAbort: If gh fails persistently (auth/network) or returns
            malformed JSON
    """
    cmd = f"gh pr list --repo {CLAUDE_YOLO_REPO} --search 'head:updater' --state open --json url"
    while True:
        result = _run_probe(cmd, cwd=checkout, step=ChainStep.CLAUDE_YOLO, log_func=log_func)
        if _is_rate_limited(result):
            _backoff_sleep(interval, sleep, log_func)
            continue
        if result.returncode != 0:
            raise ChainAbort(ChainStep.CLAUDE_YOLO, f"gh pr list failed: {result.stderr.strip()}")
        try:
            urls = json.loads(result.stdout or "[]")
        except ValueError:
            raise ChainAbort(ChainStep.CLAUDE_YOLO, "gh pr list returned malformed JSON") from None
        if not urls:
            log_func("claude-yolo PR merged — proceeding", to_console=True)
            return
        log_func(f"waiting for claude-yolo PR merge: {urls[0]['url']}", to_console=True)
        sleep(interval)


def wait_for_manifest(
    checkout: Path,
    image: str,
    *,
    interval: float = MANIFEST_INTERVAL_SECONDS,
    timeout: float = MANIFEST_TIMEOUT_SECONDS,
    now: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
    log_func: Callable[..., None] = log_message,
) -> None:
    """Block until `docker manifest inspect image` succeeds, aborting after timeout.

    Verify-before-proceed per runbook step 4: retry every interval up to
    timeout seconds, then abort naming the step.

    Args:
        checkout: Path to the target checkout (docker working dir)
        image: Image reference to inspect (e.g. docker.io/bborbe/claude-yolo:v0.16.0)
        interval: Seconds between attempts
        timeout: Total seconds before aborting
        now: Monotonic clock (test seam)
        sleep: Sleep function (test seam)
        log_func: Logging function to use

    Raises:
        ChainAbort: If the manifest is still absent after timeout
    """
    start = now()
    attempt = 1
    while True:
        result = _run_probe(
            f"docker manifest inspect {image}",
            cwd=checkout,
            step=ChainStep.MANIFEST_VERIFY,
            log_func=log_func,
        )
        if _is_rate_limited(result):
            _backoff_sleep(interval, sleep, log_func)
            continue
        if result.returncode == 0:
            log_func(f"manifest present for {image} (attempt {attempt})", to_console=True)
            return
        elapsed = now() - start
        if elapsed >= timeout:
            raise ChainAbort(
                ChainStep.MANIFEST_VERIFY,
                f"manifest not present for {image} after {timeout:.0f}s — "
                "check the claude-yolo build-multiarch workflow",
            )
        log_func(
            f"manifest unknown for {image} (attempt {attempt}, elapsed {elapsed:.0f}s) — "
            f"retrying in {interval:.0f}s",
            to_console=True,
        )
        sleep(interval)
        attempt += 1


def _docker_available(log_func: Callable[..., None] = log_message) -> bool:
    """Return whether the docker CLI is present, without raising.

    Args:
        log_func: Logging function to use

    Returns:
        True if `docker version` exits 0, False otherwise (e.g. exit 127)
    """
    try:
        run_command(
            "docker version --format '{{.Client.Version}}'",
            quiet=True,
            log_func=log_func,
        )
        return True
    except RuntimeError:
        return False


class InfraChain:
    """Orchestrate the four infra-tier handlers in runbook order."""

    def __init__(
        self,
        *,
        go_version: str,
        dry_run: bool,
        claude_yolo_checkout: Path | None = None,
        dark_factory_checkout: Path | None = None,
        bundlewrap_checkout: Path | None = None,
        trading_checkout: Path | None = None,
        pr_merge_interval: float = PR_MERGE_INTERVAL_SECONDS,
        manifest_interval: float = MANIFEST_INTERVAL_SECONDS,
        manifest_timeout: float = MANIFEST_TIMEOUT_SECONDS,
        now: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        """Initialize the chain.

        The interval/timeout/now/sleep parameters are the testability seam —
        tests inject a fake clock and no-op sleep. They are not CLI flags.

        Args:
            go_version: Target Go version (X.Y.Z)
            dry_run: If True, print the plan and exit with no side effects
            claude_yolo_checkout: Path to the bborbe/claude-yolo checkout
            dark_factory_checkout: Path to the bborbe/dark-factory checkout
            bundlewrap_checkout: Path to the BundleWrap checkout
            trading_checkout: Path to the bborbe/trading checkout
            pr_merge_interval: Seconds between PR-merge polls
            manifest_interval: Seconds between manifest-inspect attempts
            manifest_timeout: Total seconds before the manifest gate aborts
            now: Monotonic clock (test seam)
            sleep: Sleep function (test seam)
        """
        self._state: ChainState | None = None
        self.go_version = go_version
        self.dry_run = dry_run
        self.claude_yolo_checkout = claude_yolo_checkout
        self.dark_factory_checkout = dark_factory_checkout
        self.bundlewrap_checkout = bundlewrap_checkout
        self.trading_checkout = trading_checkout
        self.pr_merge_interval = pr_merge_interval
        self.manifest_interval = manifest_interval
        self.manifest_timeout = manifest_timeout
        self.now = now
        self.sleep = sleep

    def plan(self) -> list[str]:
        """Return the fixed ordered step names (the state machine never reorders)."""
        return ["claude-yolo", "manifest-verify", "dark-factory", "bundlewrap", "trading"]

    def _print_plan(self) -> None:
        """Print the planned chain sequence, one line per step."""
        log_message(
            f"Step 1: claude-yolo — bump ARG GO_VERSION in {CLAUDE_YOLO_REPO} Dockerfile "
            "(opens PR)",
            to_console=True,
        )
        log_message(
            f"Step 2: manifest-verify — docker manifest inspect {MANIFEST_IMAGE_PREFIX}<tag> "
            "(retry every 30s up to 30 min)",
            to_console=True,
        )
        log_message(
            f"Step 3: dark-factory — bump DefaultContainerImage in {DARK_FACTORY_REPO} "
            "pkg/const.go",
            to_console=True,
        )
        log_message(
            "Step 4: bundlewrap — bump default_golang_version in BundleWrap "
            "bundles/golang/items.py (parallel with trading)",
            to_console=True,
        )
        log_message(
            f"Step 5: trading — bump Go version across {TRADING_REPO} monorepo "
            "(parallel with bundlewrap)",
            to_console=True,
        )
        log_message("(dry-run — no handler invoked, no side effects)", to_console=True)

    def _set_state(self, state: ChainState) -> None:
        """Record the observable chain state and log the transition."""
        self._state = state
        log_message(f"[chain] state → {state.value}", to_console=True)

    async def run(self) -> int:
        """Run the full infra-tier chain in runbook order.

        Returns:
            Exit code: 0 on success, 1 on validation failure or chain abort
        """
        if not validate_go_version(self.go_version):
            log_message(
                f"✗ Invalid Go version: {self.go_version!r} (expected X.Y.Z)", to_console=True
            )
            return 1

        self._set_state(ChainState.START)

        if self.dry_run:
            self._print_plan()
            self._set_state(ChainState.DONE)
            return 0

        missing = [
            name
            for name, checkout in (
                ("claude-yolo", self.claude_yolo_checkout),
                ("dark-factory", self.dark_factory_checkout),
                ("bundlewrap", self.bundlewrap_checkout),
                ("trading", self.trading_checkout),
            )
            if checkout is None
        ]
        if missing:
            log_message(
                f"✗ Chain real run requires checkout paths for: {', '.join(missing)}",
                to_console=True,
            )
            return 1

        assert self.claude_yolo_checkout is not None
        assert self.dark_factory_checkout is not None
        assert self.bundlewrap_checkout is not None
        assert self.trading_checkout is not None

        try:
            self._set_state(ChainState.CLAUDE_YOLO)
            rc = ClaudeYoloHandler().run(
                self.claude_yolo_checkout, dry_run=False, go_version=self.go_version
            )
            if rc != 0:
                raise ChainAbort(ChainStep.CLAUDE_YOLO, f"claude-yolo handler exited {rc}")

            self._set_state(ChainState.WAITING_PR_MERGE)
            wait_for_pr_merge(
                self.claude_yolo_checkout,
                interval=self.pr_merge_interval,
                sleep=self.sleep,
                log_func=log_message,
            )

            self._set_state(ChainState.WAITING_PUBLISH)
            tag = resolve_latest_claude_yolo_tag(self.claude_yolo_checkout)

            self._set_state(ChainState.MANIFEST_GATE)
            if not _docker_available(log_func=log_message):
                raise ChainAbort(
                    ChainStep.MANIFEST_VERIFY,
                    "docker not available — install docker or run where available",
                )
            wait_for_manifest(
                self.claude_yolo_checkout,
                f"{MANIFEST_IMAGE_PREFIX}{tag}",
                interval=self.manifest_interval,
                timeout=self.manifest_timeout,
                now=self.now,
                sleep=self.sleep,
                log_func=log_message,
            )

            self._set_state(ChainState.DARK_FACTORY)
            rc = DarkFactoryHandler().run(
                self.dark_factory_checkout, dry_run=False, claude_yolo_tag=tag
            )
            if rc != 0:
                raise ChainAbort(ChainStep.DARK_FACTORY, f"dark-factory handler exited {rc}")

            self._set_state(ChainState.PARALLEL)
            results = await asyncio.gather(
                asyncio.to_thread(self._run_bundlewrap),
                asyncio.to_thread(self._run_trading),
                return_exceptions=True,
            )
            for step, result in zip(
                (ChainStep.BUNDLEWRAP, ChainStep.TRADING), results, strict=True
            ):
                if isinstance(result, Exception):
                    raise ChainAbort(step, f"{type(result).__name__}: {result}")
                if result != 0:
                    raise ChainAbort(step, f"handler exited {result}")

            self._set_state(ChainState.DONE)
            return 0
        except ChainAbort as e:
            log_message(f"✗ Chain aborted at step {e.step.value}: {e}", to_console=True)
            return 1
        except (RuntimeError, InfraTargetError) as e:
            log_message(
                f"✗ Chain aborted at step {ChainStep.MANIFEST_VERIFY.value}: {e}",
                to_console=True,
            )
            return 1

    def _run_bundlewrap(self) -> int:
        """Run the BundleWrap handler; invoked in a worker thread."""
        assert self.bundlewrap_checkout is not None
        return BundleWrapHandler().run(
            self.bundlewrap_checkout, dry_run=False, go_version=self.go_version
        )

    def _run_trading(self) -> int:
        """Run the trading handler; invoked in a worker thread."""
        assert self.trading_checkout is not None
        return TradingHandler().run(
            self.trading_checkout, dry_run=False, go_version=self.go_version
        )
