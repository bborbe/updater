---
status: completed
spec: [004-infra-tier-state-machine]
execution_id: updater-exec-045-spec-004-chain-state-machine
dark-factory-version: dev
created: "2026-08-23T11:06:36Z"
queued: "2026-08-23T11:16:19Z"
started: "2026-08-23T11:16:54Z"
completed: "2026-08-23T11:23:08Z"
---

# Infra-tier chain command and state machine

<summary>
- A new `updater chain` subcommand runs all four infra-tier handlers (claude-yolo, dark-factory, bundlewrap, trading) in the runbook order, enforced in code instead of operator intuition
- The chain runs claude-yolo first, then waits for its PR to merge and for the new docker.io tag's manifest to appear before any later step
- A `docker manifest inspect` gate retries every 30s up to 30 minutes and aborts with a named step on timeout, so `DefaultContainerImage` never resolves to a non-existent image (the runbook's 2026-06-03 `manifest unknown` incident)
- dark-factory runs strictly after the manifest gate passes, with the exact claude-yolo tag that was verified
- bundlewrap and trading run concurrently after the dark-factory pin (the parallel tail)
- `--dry-run` prints the exact planned sequence and exits with no side effects (no handler invoked, no network)
- Any step failure aborts the chain with a log line naming the failed step and a non-zero exit; GitHub/docker.io rate limits back off with jitter and are never treated as step failures
- The chain is a new module following the repo's class convention, reusing the four shipped handler classes and the shared infra-tier helpers — no new bespoke git implementation
</summary>

<objective>
Add the orchestration layer that makes the four infra-tier handlers run unattended in the runbook order — claude-yolo first, verified published, then dark-factory, then bundlewrap + trading in parallel — so the operator's ~30-60 min hand-sequencing per Go release is replaced by one `updater chain` command that aborts loudly on the first wrong link.
</objective>

<context>
Read `/workspace/CLAUDE.md` for project conventions (Python, uv + hatchling, pytest, dark-factory flow, changelog rules).

Read `/workspace/docs/infra-tier-targets.md` — the frozen target map and the claude-yolo release flow (on merge of a handler PR, `build-multiarch` auto-publishes the new claude-yolo tag to docker.io; dark-factory's `DefaultContainerImage` tracks the claude-yolo **release tag**, not the Go version).

Read these files fully before editing:
- `/workspace/src/updater/claude_yolo_handler.py` — `ClaudeYoloHandler`, `CLAUDE_YOLO_REPO = "bborbe/claude-yolo"`, `run(self, checkout: Path, *, dry_run: bool, go_version: str) -> int`.
- `/workspace/src/updater/dark_factory_handler.py` — `DarkFactoryHandler`, `DARK_FACTORY_REPO = "bborbe/dark-factory"`, `run(self, checkout: Path, *, dry_run: bool, claude_yolo_tag: str | None) -> int`, and `resolve_latest_claude_yolo_tag(checkout: Path) -> str` (resolves claude-yolo's latest release via `gh release view -R bborbe/claude-yolo --json tagName --jq .tagName`; raises `RuntimeError` on gh failure and `InfraTargetError` on an unexpected tag shape).
- `/workspace/src/updater/bundlewrap_handler.py` — `BundleWrapHandler`, `BUNDLEWRAP_REPO = "bw2/BundleWrap"`, `run(self, checkout: Path, *, dry_run: bool, go_version: str) -> int`.
- `/workspace/src/updater/trading_handler.py` — `TradingHandler`, `TRADING_REPO = "bborbe/trading"`, `run(self, checkout: Path, *, dry_run: bool, go_version: str) -> int`.
- `/workspace/src/updater/infra_tier.py` — `validate_go_version(value: str) -> bool` (regex `^\d+\.\d+\.\d+$`), `InfraTargetError`, `require_clean_worktree(checkout: Path)`.
- `/workspace/src/updater/log_manager.py` — `log_message(message: str, to_console: bool = True)` and `run_command(cmd, cwd=None, capture_output=False, quiet=False, log_func=log_message) -> subprocess.CompletedProcess`. IMPORTANT: `run_command` RAISES `RuntimeError` on non-zero exit and does not carry the output on the exception.
- `/workspace/src/updater/git_operations.py` — `find_existing_pull_request(module_path: Path, repo: str, log_func=log_message) -> str | None` runs `gh pr list --repo {repo} --search "head:updater" --state open --json url`. The chain's PR poll uses the SAME gh invocation string via its own probe (so it can inspect output for rate limits).
- `/workspace/src/updater/cli.py` — `main_updater_async()`: the `subparsers = parser.add_subparsers(dest="subcommand", metavar="SUBCOMMAND")` construction, the `_sub_descs` loop, the handler subparsers (claude-yolo/dark-factory/bundlewrap/trading added by spec 003), the `if args.subcommand == ...` dispatch chain, and the final `else` branch whose `valid` list is `", ".join([*_sub_descs.keys(), "claude-yolo", "dark-factory", "bundlewrap", "trading"])`. `asyncio` is already imported; `Path` is already imported.
- `/workspace/tests/conftest.py` — the `tmp_git_repo` fixture (real git repo with user configured). `/workspace/tests/test_dark_factory_handler.py` and `/workspace/tests/test_cli.py` — the mocking conventions: `from unittest.mock import Mock, patch`, `patch("updater.<module>.<name>")` on the name imported into the module under test, `sys.argv` + `patch("updater.cli.<HandlerClass>")` for dispatch tests. pytest config has `asyncio_mode = "auto"` — async tests are plain `async def test_...` with no decorator.
- `/workspace/src/updater/claude_analyzer.py` — the repo's `asyncio` usage idiom (asyncio is the concurrency model; `main_updater_async` is an async function).

Reference docs (in-container paths — the executor container runs from `/home/node`):
- `/home/node/.claude/plugins/marketplaces/coding/docs/python-cli-arguments-guide.md` — CLI subcommand/argument conventions
- `/home/node/.claude/plugins/marketplaces/coding/docs/python-logging-guide.md` — `log_message`/`run_command` conventions
- `/home/node/.claude/plugins/marketplaces/coding/docs/python-project-structure.md` — `src/` layout

OPEN QUESTIONS FOR THE REVIEWER (resolved as best-effort; adjust if you disagree):
- The four target checkouts come from CLI flags (`--claude-yolo`, `--dark-factory`, `--bundlewrap`, `--trading`), NOT positional args, so the 4-path ordering is explicit and `--dry-run` can run with no checkouts at all (it only prints the plan — no network, no handler invocation).
- The chain invokes the four handlers IN-PROCESS (imports the classes, calls `.run(...)`), per the spec's "where" decision — it does not re-spawn `updater <handler>` as a subprocess.
- The manifest gate and PR poll need to inspect command output (for 403/429 rate limits and for "manifest still unknown"), which `run_command` cannot return because it raises on non-zero exit. The chain therefore uses a private `_run_probe` helper that shells out via `subprocess.run` WITHOUT raising — the DoD's documented carve-out for exactly this case (`run_command() used for all shell operations — no direct subprocess calls, except subprocess.run in specific cases like fix_osv_vulnerabilities`). Mark it with a comment referencing the carve-out.
- After the claude-yolo handler returns 0 (PR opened, or idempotent no-op), the chain polls the open `head:updater` PR list until empty — an empty open-list means the PR merged. A closed-without-merge PR degrades gracefully (the chain proceeds, and the manifest gate of the unchanged tag passes); re-run is idempotent.
- The chain's `--dry-run` prints the plan only and does NOT forward a dry-run to the handlers (a handler dry-run patches its target working tree — a side effect the chain dry-run must not have). Each handler's own `--dry-run` contract is untouched (AC #7 is verified in prompt 2).
</context>

<requirements>

## 1. Create `src/updater/chain.py` — the orchestration module

Module docstring (Google-style) explaining this is the state machine that chains the four infra-tier handlers in runbook order with the docker.io manifest gate between claude-yolo and dark-factory, per spec 004.

```python
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
```

Module-level constants:

```python
MANIFEST_IMAGE_PREFIX = "docker.io/bborbe/claude-yolo:"
MANIFEST_INTERVAL_SECONDS = 30.0
MANIFEST_TIMEOUT_SECONDS = 30 * 60  # 1800s — runbook's verify-before-proceed budget
PR_MERGE_INTERVAL_SECONDS = 60.0
RATE_LIMIT_RE = re.compile(r"(?:403|429)")
```

Two enums:

```python
class ChainStep(Enum):
    """The five chain steps, in fixed order (the state machine never reorders)."""

    CLAUDE_YOLO = "claude-yolo"
    MANIFEST_VERIFY = "manifest-verify"
    DARK_FACTORY = "dark-factory"
    BUNDLEWRAP = "bundlewrap"
    TRADING = "trading"


class ChainState(Enum):
    """Observable chain states; each transition is logged with its value."""

    START = "start"
    CLAUDE_YOLO = "claude-yolo"
    WAITING_PR_MERGE = "waiting-pr-merge"
    WAITING_PUBLISH = "waiting-publish"
    MANIFEST_GATE = "manifest-gate"
    DARK_FACTORY = "dark-factory"
    PARALLEL = "parallel(bundlewrap, trading)"
    DONE = "done"
```

And the abort exception:

```python
class ChainAbort(Exception):
    """Raised to abort the chain, naming the step that failed."""

    def __init__(self, step: ChainStep, message: str) -> None:
        self.step = step
        super().__init__(f"{step.value}: {message}")
```

## 2. Probe and rate-limit helpers

Add these module-level functions. `_run_probe` is the one deliberate exception to the `run_command()`-only rule (see the DoD carve-out for `subprocess.run` in specific cases); it exists because the chain's polling loops treat a non-zero exit as NORMAL control flow (PR not yet merged, manifest still unknown) and must inspect stdout/stderr (rate-limit markers) — `run_command` raises and discards output, so it cannot serve these loops. Mark the function with a one-line comment citing the carve-out.

```python
def _run_probe(
    cmd: str, cwd: Path, log_func: Callable[..., None] = log_message
) -> subprocess.CompletedProcess:
    """Run cmd and return the result WITHOUT raising on non-zero exit.

    Deliberate exception to the run_command() convention (see DoD carve-out):
    the chain's polling loops treat a non-zero exit as normal control flow and
    must inspect the output for rate-limit markers.
    """

def _is_rate_limited(result: subprocess.CompletedProcess) -> bool:
    """Return whether result's output indicates a GitHub/docker.io 403/429 rate limit."""

def _backoff_sleep(
    base: float,
    sleep: Callable[[float], None],
    log_func: Callable[..., None] = log_message,
) -> None:
    """Log a rate-limit backoff and sleep base + a jitter term."""
```

Behavior:
- `_run_probe`: `subprocess.run(cmd, shell=True, cwd=cwd, capture_output=True, text=True, timeout=300)`; log via `log_func(f"→ Running: {cmd}", to_console=False)`; return the `CompletedProcess` regardless of `returncode`; on `subprocess.TimeoutExpired`, raise `ChainAbort` naming the step (a hung `gh pr list` / `docker manifest inspect` must escalate, not hang the chain). Do NOT raise on non-zero `returncode`.
- `_is_rate_limited`: `bool(RATE_LIMIT_RE.search((result.stdout or "") + (result.stderr or "")))`.
- `_backoff_sleep`: `delay = base + random.uniform(0.0, base)`; log `f"rate limit; backing off {delay:.0f}s"` via `log_func(..., to_console=True)`; call `sleep(delay)`. (Never aborts — a rate limit is not a step failure per the spec.)

## 3. Polling functions

### `wait_for_pr_merge`

```python
def wait_for_pr_merge(
    checkout: Path,
    *,
    interval: float = PR_MERGE_INTERVAL_SECONDS,
    sleep: Callable[[float], None] = time.sleep,
    log_func: Callable[..., None] = log_message,
) -> None:
    """Poll until no open head:updater PR remains for bborbe/claude-yolo."""
```

Behavior (an infinite wait — the spec says the chain "continues polling, never proceeds" until the operator merges):
1. Loop: `result = _run_probe(f"gh pr list --repo {CLAUDE_YOLO_REPO} --search 'head:updater' --state open --json url", cwd=checkout, log_func=log_func)`. Use exactly this single-quoted `--search 'head:updater'` form (not the double-quoted form in `git_operations.py`) — prompt 2 asserts this exact command string at the shell boundary.
2. If `_is_rate_limited(result)`: `_backoff_sleep(interval, sleep, log_func)` and continue (never a step failure).
3. If `result.returncode != 0`: `raise ChainAbort(ChainStep.CLAUDE_YOLO, f"gh pr list failed: {result.stderr.strip()}")` (persistent non-rate-limit gh failure — auth/network — is an abort, not a poll).
4. Parse `json.loads(result.stdout or "[]")` — wrap the parse in `try/except ValueError: raise ChainAbort(ChainStep.CLAUDE_YOLO, "gh pr list returned malformed JSON")` so malformed gh output aborts loudly naming the step instead of escaping as a raw traceback. If the list is empty: log `"claude-yolo PR merged — proceeding"` via `log_func(..., to_console=True)` and return. If non-empty: log `f"waiting for claude-yolo PR merge: {urls[0]['url']}"` via `log_func(..., to_console=True)` (this is the "wait state with the PR URL" probe) and `sleep(interval)`, then repeat.

### `wait_for_manifest`

```python
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
    """Block until `docker manifest inspect image` succeeds, aborting after timeout."""
```

Behavior (verify-before-proceed per runbook step 4 — retry every 30s up to 30 min, then abort):
1. `start = now()`.
2. Loop with an `attempt` counter starting at 1:
   - `result = _run_probe(f"docker manifest inspect {image}", cwd=checkout, log_func=log_func)`.
   - If `_is_rate_limited(result)`: `_backoff_sleep(interval, sleep, log_func)` and continue (no timeout abort on rate limit).
   - If `result.returncode == 0`: log `f"manifest present for {image} (attempt {attempt})"` via `log_func(..., to_console=True)` and return.
   - `elapsed = now() - start`. If `elapsed >= timeout`: `raise ChainAbort(ChainStep.MANIFEST_VERIFY, f"manifest not present for {image} after {timeout:.0f}s — check the claude-yolo build-multiarch workflow")` (the runbook's 2026-06-03 `manifest unknown` escalation — never a silent infinite poll).
   - Log `f"manifest unknown for {image} (attempt {attempt}, elapsed {elapsed:.0f}s) — retrying in {interval:.0f}s"` via `log_func(..., to_console=True)`, `sleep(interval)`, increment attempt. The per-attempt `elapsed` log is the "≥2 manifest-verify attempts with strictly increasing timestamps" probe.

### `_docker_available`

```python
def _docker_available(log_func: Callable[..., None] = log_message) -> bool:
    """Return whether the docker CLI is present, without raising."""
```

Behavior: `try: run_command("docker version --format '{{.Client.Version}}'", quiet=True, log_func=log_func); return True`, `except RuntimeError: return False`. (An exit code 127 — docker not installed — surfaces here as False; the caller aborts with a documented error naming the binary, per the spec failure mode.)

## 4. The `InfraChain` class

```python
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
```

The interval/timeout/`now`/`sleep` parameters are the testability seam (tests inject a fake clock and no-op sleep; defaults are the spec-mandated values). They are NOT surfaced as CLI flags.

Methods:

- `def plan(self) -> list[str]` — return the fixed ordered step names: `["claude-yolo", "manifest-verify", "dark-factory", "bundlewrap", "trading"]`. The state machine never reorders.
- `def _print_plan(self) -> None` — log, via `log_message(..., to_console=True)`, one line per step in the order above with the target repo/handler and the parallel annotation for the tail, e.g.:
  ```
  Step 1: claude-yolo — bump ARG GO_VERSION in bborbe/claude-yolo Dockerfile (opens PR)
  Step 2: manifest-verify — docker manifest inspect docker.io/bborbe/claude-yolo:<tag> (retry every 30s up to 30 min)
  Step 3: dark-factory — bump DefaultContainerImage in bborbe/dark-factory pkg/const.go
  Step 4: bundlewrap — bump default_golang_version in BundleWrap bundles/golang/items.py (parallel with trading)
  Step 5: trading — bump Go version across bborbe/trading monorepo (parallel with bundlewrap)
  ```
  then a final `"(dry-run — no handler invoked, no side effects)"` line. The `<tag>` in step 2 is the literal placeholder (the actual tag is resolved at runtime via gh after the PR merges; the dry-run makes NO network calls).
- `def _set_state(self, state: ChainState) -> None` — store the state and log `f"[chain] state → {state.value}"` via `log_message(..., to_console=True)`. This is the observable state-transition trace the AC probes read.
- `async def run(self) -> int` — the orchestrator, with this exact control flow:
  1. Validate: `if not validate_go_version(self.go_version): log_message(f"✗ Invalid Go version: {self.go_version!r} (expected X.Y.Z)", to_console=True); return 1`.
  2. `_set_state(ChainState.START)`.
  3. If `dry_run`: `_print_plan()`; `_set_state(ChainState.DONE)`; return 0. (No handler invoked, no network, no checkout required.)
  4. Real run — require all four checkouts: if any of `claude_yolo_checkout`, `dark_factory_checkout`, `bundlewrap_checkout`, `trading_checkout` is `None`, log `f"✗ Chain real run requires checkout paths for: {', '.join(missing)}"` and return 1.
  5. `_set_state(ChainState.CLAUDE_YOLO)`; `rc = ClaudeYoloHandler().run(self.claude_yolo_checkout, dry_run=False, go_version=self.go_version)`; if `rc != 0` raise `ChainAbort(ChainStep.CLAUDE_YOLO, f"claude-yolo handler exited {rc}")`.
  6. `_set_state(ChainState.WAITING_PR_MERGE)`; `wait_for_pr_merge(self.claude_yolo_checkout, interval=self.pr_merge_interval, sleep=self.sleep, log_func=log_message)`.
  7. `_set_state(ChainState.WAITING_PUBLISH)`; resolve the new tag: `tag = resolve_latest_claude_yolo_tag(self.claude_yolo_checkout)` (raises `RuntimeError`/`InfraTargetError` on gh failure — a release never cut means the workflow never fired; let it propagate and be converted in the `except` below).
  8. `_set_state(ChainState.MANIFEST_GATE)`; if not `_docker_available(log_func=log_message)`: raise `ChainAbort(ChainStep.MANIFEST_VERIFY, "docker not available — install docker or run where available")`. Otherwise `wait_for_manifest(self.claude_yolo_checkout, f"{MANIFEST_IMAGE_PREFIX}{tag}", interval=self.manifest_interval, timeout=self.manifest_timeout, now=self.now, sleep=self.sleep, log_func=log_message)`.
  9. `_set_state(ChainState.DARK_FACTORY)`; `rc = DarkFactoryHandler().run(self.dark_factory_checkout, dry_run=False, claude_yolo_tag=tag)` — pass the EXPLICIT verified tag (the same tag that passed the manifest gate); if `rc != 0` raise `ChainAbort(ChainStep.DARK_FACTORY, f"dark-factory handler exited {rc}")`.
  10. `_set_state(ChainState.PARALLEL)`; run the tail concurrently:
      ```python
      results = await asyncio.gather(
          asyncio.to_thread(self._run_bundlewrap),
          asyncio.to_thread(self._run_trading),
          return_exceptions=True,
      )
      for step, result in zip((ChainStep.BUNDLEWRAP, ChainStep.TRADING), results):
          if isinstance(result, Exception):
              raise ChainAbort(step, f"{type(result).__name__}: {result}")
          if result != 0:
              raise ChainAbort(step, f"handler exited {result}")
      ```
      (`return_exceptions=True` so a failing branch does not cancel the other — the successful branch's PR is opened and left, per the spec.)
  11. `_set_state(ChainState.DONE)`; return 0.
  12. Wrap the whole real-run body (steps 5-11) in `try/except ChainAbort as e:` that logs `f"✗ Chain aborted at step {e.step.value}: {e}"` via `log_message(..., to_console=True)` and returns 1, plus `except (RuntimeError, InfraTargetError) as e:` (from the tag resolution) that logs `f"✗ Chain aborted at step {ChainStep.MANIFEST_VERIFY.value}: {e}"` and returns 1.

- `def _run_bundlewrap(self) -> int` — `return BundleWrapHandler().run(self.bundlewrap_checkout, dry_run=False, go_version=self.go_version)`.
- `def _run_trading(self) -> int` — `return TradingHandler().run(self.trading_checkout, dry_run=False, go_version=self.go_version)`.

Do NOT add any tunable CLI knobs, extra flags, or metrics — the spec asks only for this flow. The five steps and their order are FIXED; the state machine does not reorder.

## 5. Wire the CLI in `src/updater/cli.py`

In `main_updater_async`:
- Add the import at the top with the other handler imports: `from .chain import InfraChain`.
- AFTER the `trading` subparser, add the `chain` subparser:
  ```python
  sub = subparsers.add_parser(
      "chain",
      help="Run the full infra-tier chain: claude-yolo → manifest-verify → dark-factory → bundlewrap + trading",
  )
  sub.add_argument(
      "--go-version",
      required=True,
      metavar="X.Y.Z",
      help="Target Go version (e.g. 1.28.0)",
  )
  sub.add_argument(
      "--dry-run",
      action="store_true",
      help="Print the planned sequence and exit without invoking any handler",
  )
  for flag, help_text in (
      ("--claude-yolo", "Path to the bborbe/claude-yolo checkout (required for a real run)"),
      ("--dark-factory", "Path to the bborbe/dark-factory checkout (required for a real run)"),
      ("--bundlewrap", "Path to the BundleWrap checkout (required for a real run)"),
      ("--trading", "Path to the bborbe/trading checkout (required for a real run)"),
  ):
      sub.add_argument(flag, metavar="PATH", help=help_text)
  ```
  The checkout flags are NOT `required=True` — `--dry-run` must work with no checkouts (it only prints the plan).
- In the dispatch chain, add before the final `else`:
  ```python
  elif args.subcommand == "chain":
      return await InfraChain(
          go_version=args.go_version,
          dry_run=args.dry_run,
          claude_yolo_checkout=Path(args.claude_yolo) if args.claude_yolo else None,
          dark_factory_checkout=Path(args.dark_factory) if args.dark_factory else None,
          bundlewrap_checkout=Path(args.bundlewrap) if args.bundlewrap else None,
          trading_checkout=Path(args.trading) if args.trading else None,
      ).run()
  ```
- In the final `else` branch, extend `valid` to include the new subcommand (without touching `_sub_descs`): `valid = ", ".join([*_sub_descs.keys(), "claude-yolo", "dark-factory", "bundlewrap", "trading", "chain"])`.

Do NOT touch the existing 8 subcommands, the four handler subparsers, `_run_go_modules`, `_run_python_modules`, `_run_docker_modules`, `_run_release_modules`, `_run_all_modules`, or any `process_*` function. Do NOT modify `claude_yolo_handler.py`, `dark_factory_handler.py`, `bundlewrap_handler.py`, `trading_handler.py`, or `infra_tier.py` — the chain only consumes them (AC #7: each handler's `--dry-run`/real-run contract stays untouched).

## 6. CHANGELOG

The updater repo has a CHANGELOG.md. Add (or append to) the `## Unreleased` section:
`- feat: Add infra-tier chain (updater chain) — state machine orchestrating claude-yolo → manifest-verify → dark-factory → bundlewrap + trading in runbook order`

## 7. Tests

Use pytest with the conventions from `tests/test_dark_factory_handler.py` / `tests/test_cli.py` (pytest, `unittest.mock.patch` on the name imported into the module under test, `tmp_path`, no real network). pytest config sets `asyncio_mode = "auto"` — async tests are plain `async def test_...`. Never let a test sleep for real — always inject the fake `sleep`/`now` or patch the poller.

### `tests/test_chain.py` (new file)

Unit tests (each helper in isolation; the pollers are NOT driven here — the end-to-end managed run lives in prompt 2's `tests/test_chain_integration.py`):

1. `test_plan_order` — `InfraChain(go_version="1.28.0", dry_run=True).plan() == ["claude-yolo", "manifest-verify", "dark-factory", "bundlewrap", "trading"]`.
2. `test_validate_go_version_rejects` — `run()` with `go_version="1.28"` returns 1.
3. `test_chain_steps_and_states` — assert `[s.value for s in ChainStep]` and `[s.value for s in ChainState]` match the fixed lists (shape test guarding against accidental reorder).
4. `test_run_dry_run_prints_plan_no_side_effects` — `InfraChain(go_version="1.28.0", dry_run=True)` with all four handler classes patched; `await run()` returns 0; captured `log_message` output contains the five step lines in the fixed order (`claude-yolo` line before `manifest-verify`, ..., `trading` last) and the `(dry-run — no handler invoked, no side effects)` line; assert NONE of the four handlers was called. Capture by patching `updater.chain.log_message` with a `Mock(side_effect=...)` that appends to a list.
5. `test_run_real_missing_checkout_aborts` — real run with `bundlewrap_checkout=None` (others patched away) → returns 1 and the logged message names `bundlewrap`.
6. `test_run_real_claude_yolo_failure_aborts` — patch `updater.chain.ClaudeYoloHandler` → `run` returns 1, and patch `wait_for_pr_merge`/`wait_for_manifest`/`_docker_available`/`resolve_latest_claude_yolo_tag` as no-ops; `await run()` returns 1; the logged abort message contains `claude-yolo`; `DarkFactoryHandler`/`BundleWrapHandler`/`TradingHandler` NOT called.
7. `test_run_real_dark_factory_failure_aborts` — ClaudeYoloHandler → 0, pollers no-ops, `resolve_latest_claude_yolo_tag` → `"v0.16.0"`, DarkFactoryHandler → 1 → returns 1, abort message contains `dark-factory`, bundlewrap/trading NOT called.
8. `test_run_real_parallel_one_fails` — all handlers up to the tail succeed; `BundleWrapHandler` → 1 and `TradingHandler` → 0 → returns 1, abort message contains `bundlewrap`, and `TradingHandler` WAS called (both branches ran; the successful one's PR is left).
9. `test_run_real_parallel_unexpected_exception_aborts` — `TradingHandler.run` raises `ValueError` → returns 1, abort message contains `trading`.
10. `test_run_real_full_sequence_order_and_tag` — all handlers → 0, pollers no-ops, `_docker_available` → True, `resolve_latest_claude_yolo_tag` → `"v0.16.0"`; `await run()` returns 0; assert the captured state log contains the exact transition sequence `claude-yolo → waiting-pr-merge → waiting-publish → manifest-gate → dark-factory → parallel(bundlewrap, trading) → done` in order; assert `DarkFactoryHandler().run` was called with `claude_yolo_tag="v0.16.0"` (the verified tag, not a fresh resolution); assert handler invocation order is claude-yolo → dark-factory → {bundlewrap, trading} (record call order via a list appended in each handler Mock's side effect).
11. `test_run_real_docker_unavailable_aborts` — `_docker_available` → False → returns 1; abort message names `manifest-verify` and mentions `docker`.
12. `test_wait_for_pr_merge_blocks_until_merged` — patch `updater.chain._run_probe` to return, in sequence: a `subprocess.CompletedProcess` with `returncode=0, stdout='[{"url": "https://github.com/bborbe/claude-yolo/pull/7"}]'`, then `returncode=0, stdout='[]'`; inject a fake `sleep` recording calls; assert the first log shows the PR URL and the function returns after the empty poll; assert `sleep` was called once.
13. `test_wait_for_pr_merge_rate_limit_backs_off` — probe returns `returncode=1, stdout='', stderr='API rate limit exceeded (403)'` then `returncode=0, stdout='[]'`; patch `updater.chain.random.uniform` → 0.0 so the delay is deterministic; assert the function does NOT raise, logs `rate limit`, calls `sleep` with a positive delay, and returns once the empty poll arrives.
14. `test_wait_for_pr_merge_persistent_failure_aborts` — probe always `returncode=1, stdout='', stderr='gh: not authenticated'` (no rate-limit marker) → `pytest.raises(ChainAbort)` whose message contains `claude-yolo`.
15. `test_wait_for_manifest_retries_then_present` — fake clock: a `now` callable backed by a mutable counter advanced by the injected fake `sleep`; probe returns `returncode=1` for the first 2 attempts then `returncode=0`; assert the captured log shows at least 2 `manifest unknown` attempts with STRICTLY increasing `elapsed` values (parse the `elapsed Ns` from the captured lines), then `manifest present`; assert `sleep` was called twice with the interval.
16. `test_wait_for_manifest_timeout_aborts` — fake clock whose `sleep` advances past `timeout` on the first sleep; probe always `returncode=1` → `pytest.raises(ChainAbort)` whose message contains `manifest-verify` and the image `docker.io/bborbe/claude-yolo:v0.16.0`.
17. `test_wait_for_manifest_image_boundary` — boundary test: with `resolve_latest_claude_yolo_tag` → `"v0.16.0"`, patch `updater.chain.wait_for_manifest` with a spy and assert it was called with EXACTLY `image="docker.io/bborbe/claude-yolo:v0.16.0"` (the tag that flows into the `docker manifest inspect` shell command is constructed only from the validated gh-resolved tag — no user-supplied string reaches the shell).

### `tests/test_cli.py` (append)

18. `test_chain_subcommand_dispatch_dry_run` — `sys.argv = ["updater", "chain", "--dry-run", "--go-version", "1.28.0"]`; `patch("updater.cli.InfraChain")` with `.return_value.run` an `AsyncMock` returning 0; assert exit 0 and `run` awaited; assert `InfraChain` constructed with `go_version="1.28.0"`, `dry_run=True`, and all four checkout kwargs `None`.
19. `test_chain_subcommand_dispatch_real_paths` — `sys.argv = ["updater", "chain", "--go-version", "1.28.0", "--claude-yolo", str(tmp_path), "--dark-factory", str(tmp_path), "--bundlewrap", str(tmp_path), "--trading", str(tmp_path)]`; assert `InfraChain` constructed with the four checkout kwargs as `Path(str(tmp_path))`.
20. `test_chain_subcommand_requires_go_version` — `sys.argv = ["updater", "chain"]` → `pytest.raises(SystemExit)`.

Coverage: new module must have ≥80% statement coverage — verify with `uv run --with pytest-cov pytest --cov=updater.chain --cov-report=term-missing tests/test_chain.py tests/test_cli.py`.
</requirements>

<constraints>
- Lives in `src/updater/` as a module; CLI wiring goes in `cli.py`. Reuse `infra_tier.py`, `git_operations.py`, `config.py` — NO new bespoke git implementation, NO changes to the four handler modules or `infra_tier.py`.
- Ordering is FIXED: claude-yolo → manifest gate → dark-factory per the runbook's hard prerequisite; bundlewrap + trading as the parallel tail (the architecture's design — no hard dependency between them or with dark-factory); the state machine does NOT reorder.
- The chain invokes the handlers IN-PROCESS (imports the classes and calls `.run(...)`); it does not re-spawn `updater <handler>` as a subprocess.
- `--go-version` is validated against the `X.Y.Z` regex BEFORE use; the manifest image string is built only from a `vX.Y.Z`-validated gh-resolved tag or a constant — no user-supplied image string ever reaches the shell.
- No credentials are handled by the chain itself; `gh`/docker auth are the operator's ambient session. No secrets written to logs.
- The four handlers' existing `--dry-run`/real-run contracts are PRESERVED unchanged (AC #7) — the chain only consumes them; `updater <handler> --dry-run` behaves exactly as before.
- `--dry-run` prints the plan and exits WITHOUT side effects: no handler invoked, no patch applied, no network call (the manifest `<tag>` is a literal placeholder, resolved only at runtime).
- PRs use conventional `chore:`/`feat:` prefixes and `## Unreleased` CHANGELOG bullets (the updater repo's own CHANGELOG gets the chain's `feat:` bullet).
- `make precommit` stays green; existing tests unchanged.
- Follow project Python conventions (pytest, type hints, uv, Google-style docstrings); no `print` — use `log_message()`; no new dependencies.
- Do NOT commit — dark-factory handles git.
</constraints>

<verification>
Run `make precommit` — must exit 0 (sync + format + test + lint + typecheck).

Confirm the chain module, enums, and class exist:
```
grep -nE 'class (InfraChain|ChainStep|ChainState|ChainAbort)|def (wait_for_pr_merge|wait_for_manifest|_docker_available)' src/updater/chain.py
```

Confirm the CLI subcommand exists:
```
grep -n 'chain' src/updater/cli.py
```

Confirm no production file outside the allowed set changed (the handler contract is untouched):
```
git diff --stat -- src/updater/claude_yolo_handler.py src/updater/dark_factory_handler.py src/updater/bundlewrap_handler.py src/updater/trading_handler.py src/updater/infra_tier.py
```
(Expected: empty — nothing may change in the four handler modules or the shared helper.)

Run the new unit tests:
```
uv run pytest tests/test_chain.py tests/test_cli.py -q
```

Coverage check for the new module (≥80%):
```
uv run --with pytest-cov pytest --cov=updater.chain --cov-report=term-missing tests/test_chain.py tests/test_cli.py
```

Manual dry-run (produces the spec's AC #1 container evidence — no checkouts needed, no network):
```
uv run updater chain --dry-run --go-version 1.28.0
```
The output must list `claude-yolo → manifest-verify → dark-factory → bundlewrap → trading` in that order, end with `(dry-run — no handler invoked, no side effects)`, and exit 0.
</verification>
