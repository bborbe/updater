---
status: completed
execution_id: updater-exec-051-stop-prerelease-selection
dark-factory-version: v0.198.17
created: "2026-11-11T00:00:00Z"
queued: "2026-11-11T21:09:12Z"
started: "2026-11-11T21:20:46Z"
completed: "2026-11-11T22:45:00Z"
---

# fix: never leave a direct Go module on a pre-release version

<summary>
- A sweep no longer leaves a direct Go module on a pre-release version: the module is moved to the highest stable release of its own major version and the correction is named in the updater's own output
- A module already sitting on a pre-release when the sweep starts is corrected, even though no upgrade is available for it
- A pre-release reported as the available upgrade is skipped, never applied
- The upgrade path pins the exact version it validated instead of asking for the newest one
- A module with no stable release to move to, and a module pinned to a commit pseudo-version, are left alone and the skip is logged
- Every module already on stable versions behaves exactly as before
</summary>

<objective>
Make `updater` resolve every direct Go module to its highest stable release within the major version it already requires, and never leave one on a pre-release version. A pre-release must either be corrected to that stable release and the correction logged, or be left in place with the reason logged — it must never pass through a sweep unmentioned. Modules already on stable versions are unaffected.
</objective>

<context>
Read CLAUDE.md for project conventions and `docs/dod.md` for the definition of done.

Read `src/updater/go_updater.py` — `update_go_dependencies` in full. Its loop runs `go list -mod=mod -m -u -f '{{if not (or .Main .Indirect)}}{{.Path}}{{end}}' all`, then per module `go list -mod=mod -m -u {module}`, and applies `go get {module}@latest` when the output contains `[`. Note the early `return False` when no updates were made, and the trailing `go mod tidy`.

Read `src/updater/log_manager.py` — `run_command` is the only shell entry point; with `capture_output=True, quiet=True` it returns the completed process, and a non-zero exit raises `RuntimeError`.

Read `src/updater/config.py` — `GO_MAX_ITERATIONS`, `VERBOSE_MODE`.

Read `tests/test_go_updater.py` — the existing pytest style: class-based test classes, `patch("updater.go_updater.run_command")` with a `side_effect` list, `Mock(returncode=0, stdout=..., stderr="")`, the `reset_config` and `mock_module_path` fixtures. This file uses `unittest.mock.patch` only — it does not use the `mocker` fixture, and new tests here match the file, not the `mocker` line in `docs/dod.md`.

`tests/test_cli.py`, `tests/test_pipeline.py` and `tests/test_gomod_excludes.py` patch `updater.pipeline.update_go_dependencies` — they are unaffected by the new internal calls and need no edit.

Measured defect this prompt fixes, on this machine with go 1.27.3: a module whose `go.mod` already requires `k8s.io/api v0.38.0-beta.0` prints `k8s.io/api v0.38.0-beta.0` for `go list -mod=mod -m -u k8s.io/api` — no bracket — so `update_go_dependencies` takes no action and reports "No dependency updates needed". From a stable requirement (`v0.37.2`) the same command reports an upgrade bracket and `go get k8s.io/api@latest` stays on `v0.37.2`, so neither `@latest` nor `-u` applies a pre-release from a stable base: the tool's blind spot is that it never looks at the stability of the version it has, only at whether an upgrade bracket exists. Reproduced end-to-end against a copy of `lib/k8s` at its pre-sweep commit with `k8s.io/{api,apimachinery,client-go}` seeded to `v0.38.0-beta.0`: the run upgraded the other modules, reported success, and left all three k8s.io modules on the beta. That is the state that broke the 2026-11 `lib/k8s` sweep — the beta survived alongside the stable `bborbe/k8s v1.14.33`, whose generated mocks implement the `v0.37.2` interface set, so `make precommit` aborted on `missing method AuthorizationV1alpha1` / `DeleteWithResult`.
</context>

<requirements>
1. In `src/updater/go_updater.py`, add a module-level pure helper `def _is_prerelease(version: str) -> bool` with a Google-style docstring. It strips a leading `v`, strips anything from a `+` build-metadata suffix onward, and returns True iff what remains contains a `-`. The docstring must describe exactly that plain `"-" in core` rule. It must classify `v0.38.0-beta.0`, `v1.0.0-rc.1`, `v2.0.0-alpha` and `v0.0.0-20260101120000-abcdef123456` as pre-releases, and `v0.37.2`, `v1.14.33`, `v1.2.3+build.7` and `1.2.3` as stable.

2. In `src/updater/go_updater.py`, add a module-level pure helper `def _is_pseudo_version(version: str) -> bool` with a Google-style docstring: strip a leading `v` and any `+build` suffix, then return True iff what remains matches `^\d+\.\d+\.\d+-.*\d{14}-[0-9a-f]{12}$` — a Go commit pseudo-version. That pattern covers all three forms Go emits: `v0.0.0-20260101120000-abcdef123456`, `v1.2.3-0.20260101120000-abcdef123456` and `v1.2.3-pre.0.20260101120000-abcdef123456`, each ending in a 14-digit timestamp and 12 lowercase hex characters. Use a compiled module-level regex; a pseudo-version is a deliberate commit pin, not an upgrade accident, and callers must leave it alone.

3. In `src/updater/go_updater.py`, add a module-level pure helper `def _version_parts(version: str) -> tuple[int, int, int] | None` with a Google-style docstring: strip a leading `v`, strip any `+build` suffix, strip everything from the first `-` onward (so the pre-release suffix never reaches the numeric parse), split on `.`, and return the three components as ints, or `None` when any component is missing or non-numeric. It must therefore return `(0, 38, 0)` for `v0.38.0-beta.0` — the major component of a pre-release is needed on the correction path, which is exactly the case being fixed. Import `Iterable` from `collections.abc` — the module currently imports only `Callable` from there.

4. In `src/updater/go_updater.py`, add a module-level pure helper `def _highest_stable(versions: Iterable[str], major: int | None = None) -> str | None` with a Google-style docstring. It returns the highest version in `versions` that `_is_prerelease` classifies as stable, or `None` when no such version exists. When `major` is not `None`, only versions whose `_version_parts` major component equals it are candidates — this is what keeps a correction inside the major version the module already requires. Ordering is numeric per component via `_version_parts`, so `v0.10.0` outranks `v0.9.0`; entries whose `_version_parts` is `None` are ignored, not raised on. The docstring must state that a pre-release never wins over a stable version even when it is numerically higher, and that `None` means "no eligible stable release exists", which callers must treat as "leave it alone".

5. In `src/updater/go_updater.py`, add `def downgrade_prerelease_requirements(module_path: Path, log_func: Callable[..., None] = log_message) -> bool` with a Google-style docstring, placed after `update_go_dependencies`. It:
   - runs `go list -mod=mod -m -f '{{if not (or .Main .Indirect)}}{{.Path}}@{{.Version}}{{end}}' all` via `run_command` (`cwd=module_path, capture_output=True, quiet=True, log_func=log_func`), and splits the stdout into `path@version` entries, skipping empty lines and lines without `@` — the `{{if …}}` template emits an empty line for every module it filters out, so blank lines are the normal case, not an error case;
   - for each entry whose version `_is_prerelease` classifies as a pre-release:
     - when `_is_pseudo_version` is True, logs `f"  → {path} {version} is a commit pseudo-version; leaving it"` with `to_console=True` and makes no `go get` call for it — a deliberate pin is not an accident;
     - otherwise runs `go list -mod=mod -m -versions {path}` via `run_command` with the same arguments, splits its stdout on whitespace, and takes `_highest_stable` of the tokens restricted to the current version's major component (`_version_parts(version)[0]`);
     - when that stable version exists and differs from the current version, logs `f"  → {path} {version} is a pre-release; selecting highest stable {stable}"` with `to_console=True`, runs `go get {path}@{stable}` via `run_command` (`cwd=module_path, quiet=True, log_func=log_func`), and records that a correction was made;
     - when it does not exist, logs `f"  → {path} {version} is a pre-release and no stable release of major {major} exists; leaving it"` with `to_console=True` and makes no `go get` call;
   - returns True iff at least one module was corrected.
   These log lines are the "naming the skip" this fix exists to produce: a pre-release that survives the sweep must always be visible in the output with its reason, and so must a correction.

6. In `src/updater/go_updater.py`, `update_go_dependencies`:
   - after the `while` loop ends and BEFORE the `if not any_updates_made: … return False` early return, call `corrected = downgrade_prerelease_requirements(module_path, log_func=log_func)` and fold it in with `any_updates_made = any_updates_made or corrected`. No separate flag: folding into `any_updates_made` is what makes the existing `go mod tidy` block and the existing `return True` run after a correction, so a sweep that finds no upgrade but corrects a pre-release neither takes the early return nor skips the tidy.
   - in the per-module branch that sees `[` in the `go list -m -u {module}` output, extract the bracketed candidate (the first whitespace-separated token inside the `[` … `]`) and validate it with `_is_prerelease` before applying anything. When the candidate is a pre-release, do NOT apply it: resolve the highest stable version with `_highest_stable` over `go list -mod=mod -m -versions {module}`, restricted to the major component of the version `go.mod` currently requires for that module (the middle field of the same `go list -m -u` output line), log `f"  → Skipping {module}: {candidate} is a pre-release; selecting highest stable {stable}"` with `to_console=True`, and apply `go get {module}@{stable}` when such a stable version exists — when none does, log `f"  → Skipping {module}: {candidate} is a pre-release and no stable release of major {major} exists; leaving it"` with `to_console=True` and apply nothing.
   - when the candidate is stable, replace `go get {module}@latest` with `go get {module}@{candidate}` so the version that was validated is the version applied. Keep the surrounding `quiet=True, log_func=log_func` arguments and the `updates_made` / `any_updates_made` bookkeeping as they are.
   - the literal string `@latest` must not appear anywhere in `src/updater/go_updater.py` after this change — comments and docstrings included; the `<verification>` block asserts zero occurrences.

7. Add tests in `tests/test_go_updater.py`, matching the file's existing style (class-based, `unittest.mock.patch`, the `reset_config` and `mock_module_path` fixtures, no network, no real subprocess). Put the helper tests and the two named behaviour tests in a new `class TestPrereleaseHelpers`:
   - a parametrized test for `_is_prerelease` covering every case named in requirement 1, with the expected boolean;
   - a parametrized test for `_is_pseudo_version` covering `v0.0.0-20260101120000-abcdef123456` (True), `v1.2.3-0.20260101120000-abcdef123456` (True), `v1.2.3-pre.0.20260101120000-abcdef123456` (True), `v0.38.0-beta.0` (False) and `v0.37.2` (False);
   - a parametrized test for `_version_parts` covering `v0.38.0-beta.0` → `(0, 38, 0)` (the pre-release suffix must not defeat the parse), `v1.2.3+build.7` → `(1, 2, 3)`, `v0.37.2` → `(0, 37, 2)` and `not-a-version` → `None`;
   - a parametrized test for `_highest_stable` covering: a two-digit-patch list (`v0.9.0`, `v0.10.0`, `v0.10.2` → `v0.10.2`, which any string-sort implementation gets wrong); a mixed list where the numerically highest entry is a pre-release (must return the highest stable); an all-stable list; an all-pre-release list (`None`); an empty list (`None`); a list containing an unparseable entry alongside stable entries (ignored, not raised); and a `major=`-restricted case where a higher stable of another major exists (`v0.9.0`, `v1.0.0`, `major=0` → `v0.9.0`);
   - **`test_downgrade_corrects_prerelease_to_highest_stable`** — the regression test for the measured defect, in exactly this shape so the `<verification>` block can grep its assertions:

```python
    def test_downgrade_corrects_prerelease_to_highest_stable(self, mock_module_path, reset_config):
        """The measured lib/k8s defect: a pre-release requirement is moved to the highest stable."""
        with patch("updater.go_updater.run_command") as mock_run:
            mock_run.side_effect = [
                Mock(returncode=0, stdout="k8s.io/api@v0.38.0-beta.0\n\nbborbe/k8s@v1.14.33\n\n", stderr=""),
                Mock(returncode=0, stdout="k8s.io/api v0.37.0 v0.37.1 v0.37.2 v0.38.0-alpha.0 v0.38.0-beta.0", stderr=""),
                Mock(returncode=0, stdout="", stderr=""),
            ]
            corrected = downgrade_prerelease_requirements(mock_module_path)
        commands = [call.args[0] for call in mock_run.call_args_list]
        get_commands = [command for command in commands if command.startswith("go get")]
        assert corrected is True
        assert "go get k8s.io/api@v0.37.2" in get_commands
        assert not any("v0.38.0-beta.0" in command for command in get_commands)
        assert not any("bborbe/k8s" in command for command in commands)
```

   The two blank lines in the first fixture are what the `{{if …}}` template really emits for the modules it filters out, and this fixture must contain them.
   - a test that a pseudo-version entry is logged as left alone and issues no `go get`, and a test that a module whose only stable releases are of a different major version returns False and issues no `go get`;
   - a test that `update_go_dependencies` on a module with no upgrades but a pre-release requirement returns True, runs `go mod tidy`, and issues the correction — this is the case the old code returned False for;
   - **`test_upgrade_guard_skips_prerelease_candidate`** — `go list -m -u k8s.io/api` returns `"k8s.io/api v0.37.2 [v0.38.0-beta.0]"` and the versions call returns the list from above; collect the command strings the same way (`commands = [call.args[0] for call in mock_run.call_args_list]`) and assert the applied command is `go get k8s.io/api@v0.37.2`, that no command contains `@latest`, and that no command contains `v0.38.0-beta.0`.
   - update the tests that pin a call count or a `side_effect` sequence to the new call sequence: `test_no_updates_available` (`assert_called_once`), `test_single_update_available` (`call_count == 5`), `test_multiple_updates_single_iteration`, `test_iterative_updates` (`call_count == 7`), `test_max_iterations_reached`, `test_module_with_no_update_available` (`call_count == 2`), `test_verbose_mode_logging` (`call_count == 1`) and `test_go_mod_tidy_called`. Keep what each test asserts specific — a test that passes only because its expectation was loosened is not acceptable.
   - **Red run, then green run — required evidence, not optional.** Write the new tests first, against the unmodified `go_updater.py`, and run `uv run pytest tests/test_go_updater.py` — the new tests must fail (an import error for the new helpers is a legitimate red; record it verbatim). Then implement requirements 1–6, re-run the same command, and quote the passing run. In your final response, paste both transcripts verbatim, each preceded by the exact command that produced it. A test that never failed proves nothing.
8. Add a `## Unreleased` bullet to `CHANGELOG.md` (create the heading above the newest release heading when absent): `- fix: never leave a direct Go module on a pre-release version — resolve each direct module to its highest stable release and log the skip`.

9. Self-check: before finishing, re-run `<verification>` and confirm it passes; walk each requirement above against the diff.
</requirements>

<constraints>
- Do NOT commit — dark-factory handles git
- Existing tests must still pass (`uv run pytest`), and `make precommit` must pass
- `run_command` stays the only shell entry point; add no direct `subprocess` calls
- Do NOT change `clean_indirect_deps`, `fix_osv_vulnerabilities`, `run_precommit`, or any pipeline step — the OSV path (`go get -u {pkg}`) and the `updater fix` pipeline are out of scope
- Do NOT change the `go list` flags already present (`-mod=mod`, the `{{if not (or .Main .Indirect)}}` filter) — new calls copy that shape
- Do NOT bump any version, do NOT touch `pyproject.toml`, do NOT add a dependency
- Do NOT add a per-module or per-repo workaround outside the tool — the fix belongs in `updater`
- Do NOT special-case `k8s.io` or any module path: the rule is the stability and major version of the version, nothing else
- The correction only moves within the major version the module already requires: `v0.38.0-beta.0` → `v0.37.2` is the intended case. Never cross a major version to find a stable release, and never invent a version
- Keep the existing `while iteration < max_iterations` loop and its `updates_made` semantics intact; the correction is not an extra iteration and must not consume one
- The two test names in requirement 7 (`test_downgrade_corrects_prerelease_to_highest_stable`, `test_upgrade_guard_skips_prerelease_candidate`) are contractual — the `<verification>` block runs them by node id, so they must exist under exactly those names in `class TestPrereleaseHelpers` and must assert the mocked `run_command` arguments, not merely call the code
</constraints>

<verification>
Run `make precommit` — must pass.
Run `uv run pytest tests/test_go_updater.py -q` — must pass.
Run `uv run pytest "tests/test_go_updater.py::TestPrereleaseHelpers::test_downgrade_corrects_prerelease_to_highest_stable" -q` — must pass.
Run `uv run pytest "tests/test_go_updater.py::TestPrereleaseHelpers::test_upgrade_guard_skips_prerelease_candidate" -q` — must pass.
Run `grep -c 'def _is_prerelease' src/updater/go_updater.py` — must print `1`.
Run `grep -c 'def _is_pseudo_version' src/updater/go_updater.py` — must print `1`.
Run `grep -c 'def _version_parts' src/updater/go_updater.py` — must print `1`.
Run `grep -c 'def _highest_stable' src/updater/go_updater.py` — must print `1`.
Run `grep -c 'def downgrade_prerelease_requirements' src/updater/go_updater.py` — must print `1`.
Run `grep -cE '= _highest_stable\(' src/updater/go_updater.py` — must print `2` (the correction call site and the upgrade-guard call site; anchoring on `= ` keeps prose in docstrings out of the count).
Run `! grep -q '@latest' src/updater/go_updater.py` — must exit 0 (the string is absent; `grep -c` prints `0` but exits 1 on zero matches, so it cannot be used here).
Run `grep -q 'no stable release of major' src/updater/go_updater.py && echo ok` — must print `ok`.
Run `grep -q 'is a commit pseudo-version; leaving it' src/updater/go_updater.py && echo ok` — must print `ok`.
Run `grep -q 'class TestPrereleaseHelpers' tests/test_go_updater.py && echo ok` — must print `ok`.
Run `grep -qF 'assert "go get k8s.io/api@v0.37.2" in commands' tests/test_go_updater.py && echo ok` — must print `ok` (the regression test really asserts the correction command).
Run `grep -qF 'assert corrected is True' tests/test_go_updater.py && echo ok` — must print `ok`.
Run `grep -qF 'assert not any("v0.38.0-beta.0" in command for command in get_commands)' tests/test_go_updater.py && echo ok` — must print `ok`.
Run `grep -q 'v0.10.2' tests/test_go_updater.py && echo ok` — must print `ok`.
Run `awk '!/^def / && /downgrade_prerelease_requirements\(module_path/{a=NR} /if not any_updates_made/{b=NR} END{exit !(a && b && a < b)}' src/updater/go_updater.py` — must exit 0 (the correction call, not its definition, precedes the early return).
Run `awk '/^## /{sec=$0} /never leave a direct Go module on a pre-release/{print sec}' CHANGELOG.md` — must print `## Unreleased`.
</verification>
