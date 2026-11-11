---
status: completed
created: "2026-11-11T00:00:00Z"
completed: "2026-11-11T23:40:00Z"
---

# fix: restore the module graph after a pre-release correction

<summary>
- Correcting a direct module off a pre-release no longer leaves the indirect pins that the pre-release dragged in behind it
- The indirect requirements are dropped and re-resolved against the corrected graph, so the module builds again
- The cleanup runs only when a correction happened; a sweep that corrects nothing issues exactly the commands it issues today
- The extra pass is visible in the sweep output, so the operator can see why the module was re-tidied
- No module path is special-cased — the cleanup follows the correction, whatever module carried it
</summary>

<objective>
After `downgrade_prerelease_requirements` moves a direct module off a pre-release, drop the indirect requirements that the pre-release pulled forward and let `go mod tidy` re-resolve them against the corrected graph. Without that step the corrected module still fails to build, because an indirect dependency stays at the version the pre-release needed.
</objective>

<context>
Read CLAUDE.md for project conventions and `docs/dod.md` for the definition of done.

Read `src/updater/go_updater.py` — `update_go_dependencies` (the correction call and the `go mod tidy` that follows it), `downgrade_prerelease_requirements`, and `clean_indirect_deps`, which already exists and does exactly the drop-and-retidy this change needs. `clean_indirect_deps` drops every indirect requirement via `go mod edit -droprequire` and re-adds only what the graph needs via `go mod tidy`; it returns True when it found indirect deps to drop.

Read `tests/test_go_updater.py` — `TestPrereleaseHelpers` holds the correction tests; `patch("updater.go_updater.run_command")` with a `side_effect` list is the file's style (`mocker` in `docs/dod.md` is stale; this file uses `patch`).

Measured reason this is needed (2026-11-11, in a clone of `seibert-data/lib-k8s` at its pre-sweep commit): `go get k8s.io/api@v0.38.0-beta.0 k8s.io/apimachinery@v0.38.0-beta.0 k8s.io/client-go@v0.38.0-beta.0` also bumps the indirect `k8s.io/kube-openapi` to a pseudo-version whose `schema` package is typed with `sigs.k8s.io/structured-merge-diff/v7`, and adds `sigs.k8s.io/structured-merge-diff/v7` to the graph. Correcting the three direct modules back to `v0.37.2` leaves both in place, and `go build k8s.io/apimachinery/pkg/util/managedfields/internal` then fails with `cannot use typeSchema.Types (variable of type []v7/schema.TypeDef) as []v6/schema.TypeDef value in struct literal` — `apimachinery@v0.37.2` requires `kube-openapi v0.0.0-20260721132016` and `structured-merge-diff/v6 v6.4.2` only. Running `clean_indirect_deps` after the correction restores `k8s.io/kube-openapi v0.0.0-20260821135717-be32def86098` and drops v7, after which `go build ./...` exits 0. The same residue appears when the pre-release arrives indirectly, measured in the same clone: `go get github.com/bborbe/strimzi@v1.8.24` upgraded `k8s.io/api`, `k8s.io/apimachinery`, `k8s.io/client-go` and `k8s.io/apiextensions-apiserver` to `v0.38.0-beta.0` in one command.
</context>

<requirements>
1. In `src/updater/go_updater.py`, `update_go_dependencies`: when `downgrade_prerelease_requirements` returned True, call `clean_indirect_deps(module_path, log_func=log_func)` immediately after it and before the existing `go mod tidy`, so the pins the pre-release dragged in are dropped and re-resolved against the corrected graph. Log `"  → Dropping indirect pins left behind by the pre-release correction"` with `to_console=True` before the call, so the extra pass is visible in the sweep output. When the correction returned False, make no extra call — a run that corrects nothing must issue exactly the commands it issues today.

2. Keep `any_updates_made` folding exactly as it is: the correction already sets it, and `clean_indirect_deps` must not introduce a second flag. It runs its own `go mod tidy` internally, so a corrected module gets two tidy runs — that is expected; keep the existing `go mod tidy` after the loop and add no parameter or second tidy decision of your own.

3. Add tests in `tests/test_go_updater.py`, in `class TestPrereleaseHelpers`, matching the file's style (`patch("updater.go_updater.run_command")`, no network, no real subprocess):
   - **`test_correction_cleans_indirect_pins`** — patch `updater.go_updater.clean_indirect_deps` and `updater.go_updater.run_command`; make the audit fixture report one pre-release (`example.com/lib@v1.0.0-rc.1` with a stable `v1.0.0` available) so a correction happens; assert `clean_indirect_deps` was called exactly once and that the step still returns True.
   - **`test_no_correction_skips_indirect_cleanup`** — the same patch, with one module genuinely upgraded in the loop (so `any_updates_made` is True and the early return is not what skips the cleanup) and the audit reporting only stable requirements; assert `clean_indirect_deps` was never called and the step returns True.
   - **`test_update_go_dependencies_corrects_prerelease_without_upgrade`** (already in the class) does not patch `clean_indirect_deps`, so the new call consumes one more `run_command`; add one `Mock(returncode=0, stdout="", stderr="")` for the indirect-list call to its `side_effect` so it still passes.
4. Add a `## Unreleased` bullet to `CHANGELOG.md` (create the heading above the newest release heading when absent): `- fix: drop the indirect pins a pre-release dragged in, so a corrected module builds again`.

5. Self-check: before finishing, re-run `<verification>` and confirm it passes; walk each requirement above against the diff.
</requirements>

<constraints>
- Do NOT commit — dark-factory handles git
- Existing tests must still pass (`uv run pytest`), and `make precommit` must pass
- Do NOT change `clean_indirect_deps` itself, `fix_osv_vulnerabilities`, `run_precommit`, or any pipeline step
- `run_command` stays the only shell entry point; add no direct `subprocess` calls
- Do NOT special-case `k8s.io`, `kube-openapi`, `structured-merge-diff` or any module path — the cleanup follows the correction, whatever module carried it
- Do NOT bump any version, do NOT touch `pyproject.toml`, do NOT add a dependency
- The cleanup runs only when a correction happened; do not run it on every sweep
</constraints>

<verification>
Run `make precommit` — must pass.
Run `uv run pytest tests/test_go_updater.py -q` — must pass.
Run `uv run pytest "tests/test_go_updater.py::TestPrereleaseHelpers::test_correction_cleans_indirect_pins" -q` — must pass.
Run `uv run pytest "tests/test_go_updater.py::TestPrereleaseHelpers::test_no_correction_skips_indirect_cleanup" -q` — must pass.
Run `grep -q 'Dropping indirect pins left behind by the pre-release correction' src/updater/go_updater.py && echo ok` — must print `ok`.
Run `grep -A8 'corrected = downgrade_prerelease_requirements' src/updater/go_updater.py | grep -q 'clean_indirect_deps(module_path' && echo ok` — must print `ok` (the call sits immediately after the correction, inside the corrected branch).
Run `grep -qF 'mock_clean.assert_not_called()' tests/test_go_updater.py && echo ok` — must print `ok`.
Run `grep -qF 'assert "go get example.com/lib@v1.1.0" in commands' tests/test_go_updater.py && echo ok` — must print `ok` (the negative test really drives an upgrade, so it cannot pass by returning early).
Run `awk '/^## /{sec=$0} /drop the indirect pins a pre-release dragged in/{print sec}' CHANGELOG.md` — must print `## Unreleased`.
</verification>
