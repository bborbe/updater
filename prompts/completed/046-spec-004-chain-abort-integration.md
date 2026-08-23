---
status: completed
spec: [004-infra-tier-state-machine]
summary: Added tests/test_chain_integration.py — in-process managed-chain integration suite driving the real InfraChain.run() with stubbed handlers and a fake clock, locking down the state sequence, manifest-gate retry/abort (including the 30-min timeout naming manifest-verify), handler-failure aborts, the parallel tail, the exact dry-run plan output, and the gh/docker shell-command boundary, plus contract-preservation guards that chain.py consumes the handler classes and their keyword-only dry_run signatures remain intact.
execution_id: updater-exec-046-spec-004-chain-abort-integration
dark-factory-version: dev
created: "2026-08-23T11:06:36Z"
queued: "2026-08-23T11:16:19Z"
started: "2026-08-23T11:23:09Z"
completed: "2026-08-23T11:26:22Z"
---

# Infra-tier chain: managed-chain integration tests for ordering, dry-run output, and abort paths

<summary>
- Adds an end-to-end in-process "managed chain" test suite that drives the real `updater chain` control flow with the four handlers stubbed and a fake clock
- Proves the full state sequence (claude-yolo → waiting-pr-merge → waiting-publish → manifest-gate → dark-factory → parallel(bundlewrap, trading) → done) is logged in the exact runbook order
- Proves the manifest gate really retries with strictly increasing timestamps before proceeding (the AC #3 probe) and aborts on the 30-minute timeout naming `manifest-verify`
- Proves a failing handler in any step aborts the chain with a non-zero exit and a log line naming the step, and that the parallel tail's successful branch still runs and leaves its PR
- Locks down the `--dry-run` plan output as an exact, order-sensitive assertion (the AC #1 negative evidence)
- Verifies the handlers' existing `--dry-run`/real-run contracts are preserved: the chain reuses the handler classes and no handler module changed
- Adds no production code — this prompt is tests plus verification only, satisfying the spec's "mocked/managed chain run (handlers stubbed) verifies ordering + abort behavior end-to-end in-process" container-executable rung
</summary>

<objective>
Prove the chain's orchestration and abort behavior end-to-end in-process — the real `InfraChain.run()` dispatch path with handlers stubbed and a fake clock, so ordering, the manifest gate's retry/abort semantics, the parallel tail, and the dry-run output are locked down by tests rather than by a live four-repo run that only the operator can make.
</objective>

<context>
This prompt runs AFTER prompt 1 (`1-spec-004-chain-state-machine.md`) — it assumes `src/updater/chain.py` exists with the module-level functions `wait_for_pr_merge`, `wait_for_manifest`, `_docker_available`, `_run_probe`, `_is_rate_limited`, `_backoff_sleep`, the enums `ChainStep`/`ChainState`, `ChainAbort`, and the class `InfraChain` (with `async def run(self) -> int`, `def plan(self)`, `def _print_plan(self)`, `def _set_state(self)`, `_run_bundlewrap`, `_run_trading`), wired as the `updater chain` subcommand in `/workspace/src/updater/cli.py`. If any of that is missing, STOP and re-run prompt 1 first.

Read `/workspace/CLAUDE.md` for project conventions (Python, uv + hatchling, pytest, dark-factory flow, changelog rules).

Read these files fully before writing tests:
- `/workspace/src/updater/chain.py` — the exact signatures and log-line shapes from prompt 1. The state transitions are logged as `[chain] state → {ChainState.value}`; the manifest attempts as `manifest unknown for {image} (attempt N, elapsed Ns) — retrying in Ns`; the PR wait as `waiting for claude-yolo PR merge: {url}`; the abort as `✗ Chain aborted at step {ChainStep.value}: {message}`. The chain constructs the manifest image as `f"{MANIFEST_IMAGE_PREFIX}{tag}"` where `MANIFEST_IMAGE_PREFIX = "docker.io/bborbe/claude-yolo:"`. The chain's `_docker_available` calls `run_command("docker version ...")` from `log_manager` (NOT the `_run_probe` helper) — so integration tests patch `updater.chain._docker_available` directly.
- `/workspace/src/updater/claude_yolo_handler.py`, `/workspace/src/updater/dark_factory_handler.py`, `/workspace/src/updater/bundlewrap_handler.py`, `/workspace/src/updater/trading_handler.py` — the four handler classes the chain imports and calls (`run(checkout, *, dry_run, ...) -> int`).
- `/workspace/src/updater/log_manager.py` — `log_message(message: str, to_console: bool = True)`; the chain logs its state/abort/wait lines through the module-level name imported into `chain.py`.
- `/workspace/tests/conftest.py` — `tmp_git_repo` fixture. `/workspace/tests/test_dark_factory_handler.py` — the mocking conventions: `from unittest.mock import Mock, patch`, patch the name imported into the module under test (`patch("updater.chain.ClaudeYoloHandler")`, `patch("updater.chain.log_message")`, etc.). pytest config sets `asyncio_mode = "auto"` — async tests are plain `async def test_...` with no decorator.

Reference docs (in-container paths — the executor container runs from `/home/node`):
- `/home/node/.claude/plugins/marketplaces/coding/docs/python-logging-guide.md` — logging conventions
- `/home/node/.claude/plugins/marketplaces/coding/docs/python-project-structure.md` — `src/` layout

OPEN QUESTIONS FOR THE REVIEWER (resolved as best-effort; adjust if you disagree):
- This prompt is deliberately tests-only (no production edits). The abort machinery and dry-run printer were implemented in prompt 1 because the manifest gate's 30-minute timeout abort (AC #3) is intrinsic to the state machine; the spec's suggested prompt 2 focus ("dry-run sequence printer + abort-on-failure naming + idempotency re-use") is therefore realized here as the full managed-chain integration tests plus the contract-preservation verification, which is what the spec's Verification section names as the container-executable evidence.
- The "overlapping timestamps" probe for the parallel tail (AC #5) is asserted structurally in-process: both parallel handlers are invoked and both results are collected before the chain proceeds/aborts; true wall-clock concurrency is only observable on a real run (operator rung). The integration test asserts the invocation + collection contract, not microsecond overlap.
- To drive the real `run()` control flow without sleeping, the tests patch `updater.chain._run_probe` and inject a fake `now`/`sleep` into the `InfraChain` constructor — the pollers execute their real retry/backoff logic against the fake clock. Rate-limit backoff in tests patches `updater.chain.random.uniform` to 0.0 so delays are deterministic.
</context>

<requirements>

## 1. Create `tests/test_chain_integration.py` — the managed chain run

New file. These tests drive the REAL `InfraChain.run()` end-to-end (all handlers stubbed, `_run_probe` faked, fake clock), which is the distinction from prompt 1's per-helper unit tests. Use `tmp_path` for the checkout paths; the handlers are patched so no real git/gh/docker runs happen.

Shared helpers at the top of the file:
- A `_FakeClock` class: `now` callable returning a mutable `t` (starting at 0.0), with `advance(seconds)`; a `_make_fake_sleep(clock)` factory returning a `sleep` function that calls `clock.advance(seconds)` (so elapsed time advances exactly with the sleeps — no real sleeping).
- A `_probe(returncode, stdout="", stderr="")` helper returning `subprocess.CompletedProcess(args=("probe",), returncode=returncode, stdout=stdout, stderr=stderr)`.
- A `_capture_log()` context manager: patch `updater.chain.log_message` with a `Mock(side_effect=lambda msg, to_console=True: lines.append(msg))` appending to a local list, and yield that list.
- A `_stub_handlers()` context manager: patch `updater.chain.ClaudeYoloHandler`, `updater.chain.DarkFactoryHandler`, `updater.chain.BundleWrapHandler`, `updater.chain.TradingHandler` so each `.return_value.run` returns a configurable exit code (default 0), recording each invocation (step name + kwargs) in a shared list so tests can assert ordering and that the tail ran as two collected results.

### Managed happy path

1. `test_full_chain_happy_path_state_sequence` — stub all four handlers → 0; patch `updater.chain._docker_available` → True; patch `updater.chain.resolve_latest_claude_yolo_tag` → `"v0.16.0"`; patch `updater.chain._run_probe` with a side-effect function that returns, based on the command string:
   - `gh pr list` calls → open-PR JSON `[{"url": "https://github.com/bborbe/claude-yolo/pull/7"}]` for the first call, then `[]` for the second;
   - `docker manifest inspect` calls → `returncode=1` for the first two attempts, `returncode=0` on the third.
   Construct `InfraChain(go_version="1.28.0", dry_run=False, claude_yolo_checkout=tmp_path, dark_factory_checkout=tmp_path, bundlewrap_checkout=tmp_path, trading_checkout=tmp_path, now=clock, sleep=fake_sleep)` and `await run()` → returns 0. Assert, from the captured log:
   - The state-transition lines appear in EXACT order: `claude-yolo`, `waiting-pr-merge`, `waiting-publish`, `manifest-gate`, `dark-factory`, `parallel(bundlewrap, trading)`, `done` (parse the `[chain] state → X` lines).
   - The PR URL `https://github.com/bborbe/claude-yolo/pull/7` appears in a `waiting for claude-yolo PR merge:` line.
   - At least two `manifest unknown` attempts appear with STRICTLY increasing `elapsed Ns` values, followed by a `manifest present` line (the AC #3 probe).
   - Handler invocation order is claude-yolo, then dark-factory, then bundlewrap + trading; `DarkFactoryHandler().run` received `claude_yolo_tag="v0.16.0"`; both tail handlers were invoked and both results collected.
   - Every `docker manifest inspect` command string passed to `_run_probe` is exactly `docker manifest inspect docker.io/bborbe/claude-yolo:v0.16.0` and every `gh pr list` command string is exactly `gh pr list --repo bborbe/claude-yolo --search 'head:updater' --state open --json url` (the shell-command boundary — built only from the validated gh-resolved tag and constants, no user-supplied string).

### Abort paths (the AC #6 negative evidence)

2. `test_full_chain_abort_on_manifest_timeout` — handlers stubbed (claude-yolo → 0); patch `updater.chain._docker_available` → True; `_run_probe` returns `[]` for the `gh pr list` call and `returncode=1` for every `docker manifest inspect` call; `resolve_latest_claude_yolo_tag` → `"v0.16.0"`; fake clock whose `sleep` advances past the 1800s timeout. `await run()` returns 1; the captured log contains `✗ Chain aborted at step manifest-verify` and mentions `docker.io/bborbe/claude-yolo:v0.16.0` and the 30-minute budget; `DarkFactoryHandler`/`BundleWrapHandler`/`TradingHandler` were NEVER invoked (the chain stopped at the gate).
3. `test_full_chain_abort_on_handler_failure_names_step` — dark-factory stub → 1 (claude-yolo → 0; `_docker_available` → True; `gh pr list` → `[]` immediately; `docker manifest inspect` → `returncode=0`; tag → `"v0.16.0"`). `await run()` returns 1; log contains `✗ Chain aborted at step dark-factory`; bundlewrap/trading NOT invoked.
4. `test_full_chain_parallel_tail_one_fails_other_runs` — all up to the tail succeed; bundlewrap stub → 1, trading stub → 0. `await run()` returns 1; log contains `✗ Chain aborted at step bundlewrap`; the invocation record shows trading WAS invoked (the successful branch's PR is opened and left, never rolled back — no chain code attempts to close or revert the successful branch).
5. `test_full_chain_docker_unavailable_aborts` — happy-path scaffolding up to the gate: `InfraChain` constructed with all four checkouts (`tmp_path`), claude-yolo stub → 0, `gh pr list` → `[]` immediately, `docker manifest inspect` → `returncode=0`, `resolve_latest_claude_yolo_tag` → `"v0.16.0"` — then patch `updater.chain._docker_available` → False; `await run()` returns 1; log contains `✗ Chain aborted at step manifest-verify` and the word `docker` (the documented "install docker or run where available" error); dark-factory and the tail NOT invoked.

### Dry-run printer (the AC #1 negative evidence as an assertion)

6. `test_full_chain_dry_run_exact_output` — `InfraChain(go_version="1.28.0", dry_run=True)` (no checkouts — all `None`); patch all four handler classes, `updater.chain.resolve_latest_claude_yolo_tag`, and `updater.chain._run_probe`; `await run()` returns 0; the captured log, filtered to the `Step N:` lines plus the final line, equals EXACTLY (order-sensitive, `manifest-verify` between `claude-yolo` and `dark-factory`):
   ```
   Step 1: claude-yolo — bump ARG GO_VERSION in bborbe/claude-yolo Dockerfile (opens PR)
   Step 2: manifest-verify — docker manifest inspect docker.io/bborbe/claude-yolo:<tag> (retry every 30s up to 30 min)
   Step 3: dark-factory — bump DefaultContainerImage in bborbe/dark-factory pkg/const.go
   Step 4: bundlewrap — bump default_golang_version in BundleWrap bundles/golang/items.py (parallel with trading)
   Step 5: trading — bump Go version across bborbe/trading monorepo (parallel with bundlewrap)
   (dry-run — no handler invoked, no side effects)
   ```
   Assert none of the four handlers, `_run_probe`, or `resolve_latest_claude_yolo_tag` was called (dry-run makes no network calls and has no side effects).

### Boundary: the gh/docker shell commands the chain builds

7. `test_chain_shell_command_boundaries` — a SEPARATE test function (the exact-command-string assertions live in test 1, not here) holding the dedicated assertion that the raw stdout of `_run_probe` (the gh JSON) is parsed via `json.loads` and never interpolated into a command — patch `_run_probe` to return a URL string containing shell metacharacters in a `wait_for_pr_merge`-only call and assert the function still treats it as data (parses it), never as a command fragment.

## 2. Contract-preservation verification (AC #7)

Do NOT modify any production file in this prompt. Add the following as plain pytest tests that inspect the repo state, so they fail loudly if the handler contract ever drifts:

8. `test_chain_consumes_handler_classes_not_reimplementations` — read `/workspace/src/updater/chain.py` source (via `Path(__file__).parents[1] / "src" / "updater" / "chain.py"`) and assert it imports `ClaudeYoloHandler`, `DarkFactoryHandler`, `BundleWrapHandler`, `TradingHandler` from their handler modules (i.e. the chain invokes the SAME code paths as `updater <handler>`, not a duplicate implementation).
9. `test_handler_dry_run_contracts_intact` — assert the four handler modules' source is unchanged from the shipped v0.24.0 contract: each still exposes `run(self, checkout: Path, *, dry_run: bool, ...) -> int` with a `dry_run` keyword-only parameter (grep the source for `*, dry_run:`). This is a shape guard — the behavior is exercised by the existing handler test files, which `make precommit` runs unchanged.

## 3. No production edits

Do NOT edit `src/updater/chain.py`, `src/updater/cli.py`, any handler module, `infra_tier.py`, or the CHANGELOG. This prompt only adds `tests/test_chain_integration.py`. If the tests reveal a bug in the chain, record it in the completion report as a blocker with the failing assertion — do not fix production code here (that belongs in a new prompt on the same spec).
</requirements>

<constraints>
- Tests only: NO production code changes in this prompt. No edits to `src/updater/chain.py`, `src/updater/cli.py`, the four handler modules, or `infra_tier.py`.
- Tests use pytest with the repo conventions (patch the name imported into the module under test, `tmp_path`/`tmp_git_repo` fixtures, no real network, no real sleeping — always the injected fake clock and no-op/patching sleep). pytest config sets `asyncio_mode = "auto"`; async tests are plain `async def test_...`.
- The four handlers' existing `--dry-run`/real-run contracts are PRESERVED — this prompt only verifies that, it does not change them.
- No credentials, no secrets in tests or logs; the tests fake `gh`/docker entirely.
- `make precommit` stays green; existing tests unchanged (the existing handler test files still pass untouched).
- Do NOT commit — dark-factory handles git.
</constraints>

<verification>
Run `make precommit` — must exit 0 (sync + format + test + lint + typecheck). This runs the FULL suite including the four existing handler test files, proving their contracts are intact.

Confirm the integration suite exists and passes:
```
uv run pytest tests/test_chain_integration.py -q
```

Run the whole chain test surface (prompt 1's unit tests + this prompt's integration tests):
```
uv run pytest tests/test_chain.py tests/test_chain_integration.py tests/test_cli.py -q
```

Confirm no production file was touched by this prompt:
```
git diff --stat -- src/
```
(Expected: empty — this prompt adds tests only. If `src/` shows changes, the prompt was not followed.)

Confirm the four handler modules are byte-identical to the shipped v0.24.0 contract (no drift):
```
git diff --stat -- src/updater/claude_yolo_handler.py src/updater/dark_factory_handler.py src/updater/bundlewrap_handler.py src/updater/trading_handler.py src/updater/infra_tier.py
```
(Expected: empty.)

Coverage check for the new integration file (≥80% statement coverage of `updater.chain` across both test files combined):
```
uv run --with pytest-cov pytest --cov=updater.chain --cov-report=term-missing tests/test_chain.py tests/test_chain_integration.py
```
</verification>
