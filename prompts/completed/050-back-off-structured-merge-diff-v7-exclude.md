---
status: completed
execution_id: updater-smd-v7-backoff-exec-050-back-off-structured-merge-diff-v7-exclude
dark-factory-version: v0.198.7
created: "2026-10-15T19:36:59Z"
queued: "2026-10-15T19:36:59Z"
started: "2026-10-15T19:37:39Z"
completed: "2026-10-15T19:43:49Z"
---

# fix: back off the structured-merge-diff v7 exclude when a module imports v7

<summary>
- A sweep no longer aborts on a module whose graph genuinely imports structured-merge-diff v7
- The fleet-wide exclude is still applied everywhere it is correct, unchanged
- When the dependency update fails because the exclude removed a package the graph imports, the updater drops that one exclude for that one module and re-runs the update once
- A failing update that is not this conflict still fails, exactly as today
- Both phrasings Go prints for this conflict are recognised, so the back-off fires whichever updater command hits it
- Every module that does not hit the conflict behaves exactly as before
</summary>

<objective>
Stop `updater` from aborting a sweep when its own fleet-wide `sigs.k8s.io/structured-merge-diff/v7@v7.0.0` exclude removes a package that the module's graph actually imports, by removing that exclude for the affected module and retrying the dependency update once. The exclude exists to hold back a kube-openapi tip that needs the unreleased Kubernetes 1.38 line; on a module that has already moved to that line the same exclude is what makes the module unresolvable, so it must yield to the module that needs v7 rather than the other way round.
</objective>

<context>
Read CLAUDE.md for project conventions.
Read `src/updater/gomod_excludes.py` — `STANDARD_EXCLUDES`, its comment block, `read_gomod_excludes_and_replaces`, `apply_gomod_excludes_and_replaces`.
Read `src/updater/pipeline.py` — the `Step` base class, `GoExcludesStep`, `GoDepUpdateStep`.
Read `src/updater/go_updater.py` — `update_go_dependencies`; note it raises from two places: the `go get {module}@latest` call inside the loop and the trailing `go mod tidy`.
Read `src/updater/log_manager.py` — `run_command`, specifically the non-zero-exit branch.
Read `tests/test_gomod_excludes.py` — the existing pytest style (`mocker`, `tmp_path`, patching `run_command`).
Read `tests/test_pipeline.py` — the async step-test style (`asyncio_mode = "auto"` is set in `pyproject.toml`, so `async def test_…` works without a decorator in either test module).
Read `tests/test_log_manager.py` — check whether any test asserts the exact `RuntimeError` text before changing it.
</context>

<requirements>
1. In `src/updater/log_manager.py`, `run_command`: on a non-zero exit, include the captured stderr in the raised `RuntimeError` so a caller can classify the failure without re-reading a log file. Keep the existing prefix verbatim — `Command failed: {cmd} (exit code {result.returncode})` — and append the trimmed stderr after it. Leave the success path, the return value, and the existing `log_func` calls unchanged. The existing tests use `pytest.raises(..., match=...)`, which is a regex search, so appending stderr should not break them — confirm by running the suite rather than by assuming.

2. In `src/updater/gomod_excludes.py`, introduce the v7 entry as its own module-level constant and make `STANDARD_EXCLUDES` reference it, so there is one source of truth for the string:
   `STRUCTURED_MERGE_DIFF_V7_EXCLUDE: str = "sigs.k8s.io/structured-merge-diff/v7@v7.0.0"`, then `STANDARD_EXCLUDES: list[str] = [STRUCTURED_MERGE_DIFF_V7_EXCLUDE]`. The list must still contain exactly that one entry. Do NOT change the comment block above it — the documented reason and the removal trigger stay exactly as written. Add a short comment at the constant noting both why the back-off exists (the exclude is only correct while the module still sits on the pre-1.38 k8s line) and that the constant is retired by the removal trigger documented on `STANDARD_EXCLUDES`.

3. In `src/updater/gomod_excludes.py`, add a module-level tuple `EXCLUDE_CONFLICT_PHRASES: tuple[str, ...]` holding the phrasings Go prints when an `exclude` has removed a module that a dependency still imports — `"cannot find module providing package"` (printed by `go get <module>@latest`), `"does not contain package"` (printed by `go mod tidy`), and `"excluded by go.mod"` (included defensively — a plausible third wording for the same directive, but **not** observed in this repo's captured evidence, so do not treat it as verified) — and add `def is_exclude_conflict(error_text: str) -> bool` with a docstring: returns True iff `error_text` names `sigs.k8s.io/structured-merge-diff/v7` AND contains any phrase in `EXCLUDE_CONFLICT_PHRASES`. The first two are required and empirically observed: `update_go_dependencies` raises from its `go get {module}@latest` call and again from its trailing `go mod tidy`, and the two print different text for the same root cause — matching only the first leaves the second path aborting the sweep. The list errs toward inclusion on purpose: the back-off is gated by `drop_exclude` (which returns True only when that exact exclude is present), it is per run and non-persistent, and the module's own `make precommit` still gates the result — so an over-broad phrase costs at worst one extra update pass, while a missed phrase is the exact defect this prompt exists to fix. Add a comment on the tuple saying so.

4. In `src/updater/gomod_excludes.py`, add `def drop_exclude(module_path: Path, exclude: str, log_func: Callable[..., None] = log_message) -> bool` with a docstring: read the module's current excludes via `read_gomod_excludes_and_replaces`; when `exclude` is present, run `go mod edit -dropexclude {exclude}` and then `go mod download`, and return True; when it is absent, log that and return False. Use `run_command` for both shell calls, passing `cwd=module_path, quiet=True, log_func=log_func` on each — matching the calls in `apply_gomod_excludes_and_replaces`. No direct `subprocess`.

5. In `src/updater/pipeline.py`, `GoDepUpdateStep.run`: keep the existing `is_disabled(module_config, "go-dependencies")` early return (`StepResult(StepStatus.SKIP)`) exactly as it is, then wrap the `update_go_dependencies(module_path, log_func=log_message)` call in a `try`. On `RuntimeError`, when `is_exclude_conflict(str(exc))` is True AND `drop_exclude(module_path, STRUCTURED_MERGE_DIFF_V7_EXCLUDE, log_func=log_message)` returned True, log the back-off via `log_message(..., to_console=True)` and call `update_go_dependencies` once more, reporting that retry's result. In every other case the failure must not be swallowed: when the signature does not match, when the exclude was not present (`drop_exclude` returned False), or when `drop_exclude` itself raises, re-raise the original exception unchanged so the pipeline's existing failure handling is untouched; when the retry's `update_go_dependencies` call raises, let that exception propagate so the operator sees the failure the retry actually hit. The retry must not loop: at most one re-run per module.

6. Add tests covering the predicate and every branch of requirement 5, following the existing style. **Sequence this deliberately:** implement requirements 1–4 first (all additive), then write these tests and capture the failing run, then implement requirement 5.
   - In `tests/test_gomod_excludes.py`: a parametrized test for `is_exclude_conflict` covering all six cases — v7 named plus each of the three `EXCLUDE_CONFLICT_PHRASES` entries → True, v7 named without any phrase → False, a phrase without v7 → False, neither → False. Enumerate the tuple itself (do not hard-code two phrasings) so a future fourth phrase cannot be added without a matching case.
   - In `tests/test_gomod_excludes.py`: a test for `drop_exclude` asserting the exact `go mod edit -dropexclude sigs.k8s.io/structured-merge-diff/v7@v7.0.0` call, that `go mod download` follows it, and that an absent exclude returns False with no `go mod edit` call.
   - In `tests/test_gomod_excludes.py`: the regression test — patch `updater.pipeline.update_go_dependencies` so its first call raises `RuntimeError` carrying the verbatim `go get` text `sigs.k8s.io/structured-merge-diff/v7/merge: cannot find module providing package sigs.k8s.io/structured-merge-diff/v7/merge` and its second call succeeds; patch `updater.gomod_excludes.run_command`; give the `tmp_path` module a `go.mod` containing `exclude sigs.k8s.io/structured-merge-diff/v7 v7.0.0`. Assert that `go mod edit -dropexclude sigs.k8s.io/structured-merge-diff/v7@v7.0.0` was called, that `update_go_dependencies` was called exactly twice, and that the step reports success.
   - In `tests/test_gomod_excludes.py`: the tidy-phrased regression test — same shape, but the first call raises with the verbatim `go mod tidy` text `sigs.k8s.io/structured-merge-diff/v7/merge: module sigs.k8s.io/structured-merge-diff@latest found (v1.0.2), but does not contain package sigs.k8s.io/structured-merge-diff/v7/merge`; assert the same three things.
   - In `tests/test_pipeline.py`: the non-retry branches, patching `updater.pipeline.update_go_dependencies` and `updater.pipeline.drop_exclude` (both imports need extending — that module does not yet import `GoDepUpdateStep`, and `src/updater/pipeline.py` currently imports only `apply_gomod_excludes_and_replaces` from `gomod_excludes`). The success path (no exception) asserts the step returns `StepStatus.SUCCESS` and that `update_go_dependencies` was called exactly once. Each of the three failure branches asserts `pytest.raises(RuntimeError)` and that `update_go_dependencies` was called exactly once — a `RuntimeError` whose text does not match the predicate; a matching `RuntimeError` where `drop_exclude` is mocked to return False (with `drop_exclude` patched, the `go.mod` content is inert — only the mock's return value selects the branch, so do not leave it at a truthy default); and a matching `RuntimeError` where `drop_exclude` itself raises. Add a fifth test for the remaining branch: a matching `RuntimeError` where `drop_exclude` returns True and the retry `update_go_dependencies` call raises again — assert the step raises and that `update_go_dependencies` was called exactly twice.
   - **Red run, then green run — required evidence, not optional.** Once the tests above exist but before requirement 5 is implemented, run `uv run pytest tests/test_gomod_excludes.py tests/test_pipeline.py` and record the output: the two regression tests and the retry-branch test must **not pass** against the unmodified `GoDepUpdateStep` — the two regression tests fail on the propagated `RuntimeError`, while every test that patches `updater.pipeline.drop_exclude` — the retry-branch test and both `drop_exclude` failure branches — errors at patch setup because that name does not exist in `pipeline` until requirement 5 lands (that is expected; do **not** implement requirement 5 early just to make them pass) — while the predicate and `drop_exclude` tests pass. Quote that failing run verbatim in your completion report. Then implement requirement 5, re-run the same command, and quote the passing run alongside it. A test that never failed proves nothing — do not skip this ordering.
   Paste the captured transcripts verbatim rather than paraphrasing them, each with a provenance comment naming the command it came from.
7. Add a `## Unreleased` bullet to `CHANGELOG.md` (create the heading above the newest release heading when absent): `- fix: back off the structured-merge-diff v7 exclude when a module's graph imports v7, so a sweep no longer aborts on it`.

8. Self-check: before finishing, re-run `<verification>` and confirm it passes; walk each requirement above against the diff.
</requirements>

<constraints>
- Do NOT commit — dark-factory handles git
- Existing tests must still pass
- Do NOT change the entries in `STANDARD_EXCLUDES`, its comment block, `STANDARD_REPLACES`, `OBSOLETE_EXCLUDES_PREFIXES`, or `OBSOLETE_REPLACES`
- Do NOT bump any version
- Do NOT add a per-module or per-repo workaround outside the tool — the fix belongs in `updater`
- `run_command` stays the only shell entry point; add no direct `subprocess` calls
- The back-off is per module and per run — do not persist a marker into `go.mod` or any other file
- Out of scope: the `updater fix` pipeline (`process_single_go_fix_module`), which runs `GoExcludesStep` with no `GoDepUpdateStep` and then `GoCleanIndirectStep` → `go mod tidy`, so it hits the same abort with no back-off at all. Leave that pipeline untouched and name it in the completion report as a known residual — `is_exclude_conflict` + `drop_exclude` are already the reusable pair for it.
- Catch the bare `RuntimeError` that `run_command` raises; do not introduce or convert to a typed exception for this path.
- Accepted, and not to be worked around: because `STANDARD_EXCLUDES` is unchanged, `GoExcludesStep` re-adds the exclude on every later sweep and the back-off drops it again — one extra failed update pass per affected module per sweep, until the entry's documented removal trigger fires. Do not add caching or a persisted marker to avoid this.
</constraints>

<verification>
Run `ROOTDIR=/workspace make precommit` — must pass.
Run `grep -c 'def drop_exclude' src/updater/gomod_excludes.py` — must print `1`.
Run `grep -c 'def is_exclude_conflict' src/updater/gomod_excludes.py` — must print `1`.
Run `grep -q 'does not contain package' src/updater/gomod_excludes.py && echo ok` — must print `ok`.
Run `grep -c 'STANDARD_EXCLUDES: list\[str\] = \[STRUCTURED_MERGE_DIFF_V7_EXCLUDE\]' src/updater/gomod_excludes.py` — must print `1`.
Run `awk '/^## /{sec=$0} /back off the structured-merge-diff/{print sec}' CHANGELOG.md` — must print `## Unreleased`.
</verification>
