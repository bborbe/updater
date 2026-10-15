---
status: completed
execution_id: updater-exclude-smd-v7-exec-049-exclude-structured-merge-diff-v7
dark-factory-version: dev
created: "2026-10-15T08:41:56Z"
queued: "2026-10-15T08:41:56Z"
started: "2026-10-15T08:43:10Z"
completed: "2026-10-15T08:52:26Z"
---

<summary>
- Every Go repo the updater touches gets an exclude for structured-merge-diff v7.0.0
- Sweeps stop pulling a kube-openapi revision that only works with the unreleased Kubernetes 1.38 line
- Repos on Kubernetes 1.37 libraries keep building after a sweep
- The reason and the removal trigger (Kubernetes 1.38 stable) are documented next to the entry
- Existing behaviour for repos without the exclude is unchanged apart from the one added line
- Tests that asserted "no standard excludes" are updated to the new single-entry list
</summary>

<objective>
Add `sigs.k8s.io/structured-merge-diff/v7@v7.0.0` to the standard excludes the updater applies to every go.mod, so `go mod tidy` falls back to the kube-openapi revision pinned by k8s.io v0.37.x (which uses structured-merge-diff v6) instead of kube-openapi tip (which requires v7 and breaks `k8s.io/apimachinery/pkg/util/managedfields`).
</objective>

<context>
Read CLAUDE.md for project conventions.
Read `src/updater/gomod_excludes.py` — `STANDARD_EXCLUDES`, its comment block, `OBSOLETE_EXCLUDES_PREFIXES`, and `apply_gomod_excludes_and_replaces`.
Read `tests/test_gomod_excludes.py` — every `test_apply_*` and `test_tools_go_*` test calls `apply_gomod_excludes_and_replaces` with a go.mod lacking the v7 exclude, so each assertion on `result` and `mock_run.call_count` must be re-checked; docstrings saying "STANDARD_EXCLUDES is empty" need rewording.
</context>

<requirements>
1. In `src/updater/gomod_excludes.py`, set `STANDARD_EXCLUDES` to contain exactly one entry: `"sigs.k8s.io/structured-merge-diff/v7@v7.0.0"`.
2. Extend the comment above `STANDARD_EXCLUDES` with: why (kube-openapi tip requires structured-merge-diff/v7, which only k8s 1.38 supports; with k8s.io v0.37.x it breaks managedfields), the accepted trade-off (the exclude breaks `go install <module>@latest` for repos carrying it — accepted by the operator 2026-10-15), and the removal trigger (when `k8s.io/apimachinery` v0.38.0 is released stable, delete the entry and add `"sigs.k8s.io/structured-merge-diff/v7@"` to `OBSOLETE_EXCLUDES_PREFIXES`). Keep the existing cloud.google.com/go history note. Reword the "Keep this list empty unless absolutely necessary" sentence to say the list holds only entries with a documented reason and removal trigger.
3. Ensure the exclude is not simultaneously removed by `OBSOLETE_EXCLUDES_PREFIXES` (no prefix there may match `sigs.k8s.io/structured-merge-diff/v7@`).
4. Update `tests/test_gomod_excludes.py`: fix tests that assume an empty `STANDARD_EXCLUDES` (expected go.mod content / change flags / docstrings) so they reflect the single entry: either add `exclude sigs.k8s.io/structured-merge-diff/v7 v7.0.0` to the fixture go.mod, or adjust expected `result` and `call_count` (+1 `go mod edit -exclude` call, plus `go mod download` when changes occur). Add a test that applying to a go.mod without the exclude returns True and calls `run_command` with `go mod edit -exclude sigs.k8s.io/structured-merge-diff/v7@v7.0.0` (assert the exact command) followed by `go mod download`; and a test that a go.mod containing `exclude sigs.k8s.io/structured-merge-diff/v7 v7.0.0` returns False with `call_count == 0`. Follow the existing test style in that file.
5. Add a `## Unreleased` bullet to `CHANGELOG.md` (create the heading above the newest release if absent): `- fix: exclude sigs.k8s.io/structured-merge-diff/v7 v7.0.0 in every go.mod so sweeps keep k8s.io v0.37 repos building`.
6. Self-check: re-run `<verification>` and confirm it passes; walk each requirement against the diff.
</requirements>

<constraints>
- Do NOT commit — dark-factory handles git
- Existing tests must still pass (after the updates in requirement 4)
- Do not change `STANDARD_REPLACES` or any other module list
- Do not bump versions
</constraints>

<verification>
Run `ROOTDIR=/workspace make precommit` — must pass.
Run `grep -c 'sigs.k8s.io/structured-merge-diff/v7@v7.0.0' src/updater/gomod_excludes.py` — must print `1` or more.
Run `awk '/^## /{sec=$0} /structured-merge-diff/{print sec}' CHANGELOG.md` — must print `## Unreleased`.
</verification>
