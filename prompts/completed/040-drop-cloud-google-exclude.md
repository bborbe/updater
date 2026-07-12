---
status: failed
execution_id: updater-exclude-fix-exec-040-drop-cloud-google-exclude
dark-factory-version: v0.191.4
created: "2026-07-12T18:33:38Z"
queued: "2026-07-12T18:33:38Z"
started: "2026-07-12T18:33:41Z"
completed: "2026-07-12T18:37:20Z"
lastFailReason: 'validate completion report: completion report status: partial'
---

<summary>
- `updater` stops injecting `exclude cloud.google.com/go v0.26.0` into every repo's `go.mod`. That directive breaks `go install <module>@latest` fleet-wide (go refuses a main-module go.mod with exclude/replace directives), and it is applied indiscriminately — even to repos that never depend on `cloud.google.com/go`.
- Achieved by emptying the `STANDARD_EXCLUDES` list, matching the module's own guidance ("keep this list empty unless absolutely necessary").
- Existing excludes in repos are left untouched: the entry is NOT added to `OBSOLETE_EXCLUDES_PREFIXES`, so nothing is actively stripped — the change only stops *adding* it.
- Tests and the stale "intentionally retained as a STANDARD exclude" rationale are updated to match.
</summary>

<objective>
Empty `STANDARD_EXCLUDES` in `src/updater/gomod_excludes.py` so `updater all` / `updater fix` no longer inject `exclude cloud.google.com/go@v0.26.0` (which breaks `go install …@latest`), update the explanatory comment, and fix the tests that asserted the old add-behavior. Pure list + comment + test change; no logic/flow changes to `apply_gomod_excludes_and_replaces`.
</objective>

<context>
Read `/workspace/CLAUDE.md` for project conventions (Python, uv + hatchling, pytest, dark-factory flow).
Read these files fully before editing:
- `/workspace/src/updater/gomod_excludes.py` — the `STANDARD_EXCLUDES` list (lines ~8-19) and `apply_gomod_excludes_and_replaces` (adds each STANDARD_EXCLUDES entry not already present, lines ~172-181). You edit ONLY the list + its comment.
- `/workspace/tests/test_gomod_excludes.py` — the test suite. Several tests reference `cloud.google.com/go v0.26.0`.

Why this change: `exclude`/`replace` directives make `go install github.com/bborbe/<repo>@latest` (and `@vX.Y.Z`) fail with "go.mod must not contain directives that would cause it to be interpreted differently than if it were the main module." The module's own comment already says excludes break `go install` and the list should stay empty. `cloud.google.com/go@v0.26.0` was added to resolve a `compute/metadata` split-module "ambiguous import" that only arises in repos pulling `golang.org/x/oauth2/google`; applying it to every repo breaks remote install everywhere for a conflict most repos never have. Surfaced 2026-07-12: `go install github.com/bborbe/distill@latest` failed because `updater` had injected this exclude into distill's go.mod.
</context>

<requirements>

## 1. Empty `STANDARD_EXCLUDES` in `src/updater/gomod_excludes.py`

Change the list to empty:
```python
STANDARD_EXCLUDES: list[str] = []
```
Rewrite the comment block above it so it no longer describes `cloud.google.com/go` as a needed exclude. The comment must state: excludes break `go install <module>@latest` (go rejects a main-module go.mod containing exclude/replace directives), so this list stays empty; the former `cloud.google.com/go@v0.26.0` entry was removed because it was applied to every repo — breaking remote install fleet-wide — for a `compute/metadata` split-module ambiguity that only affects repos pulling `golang.org/x/oauth2/google` and no longer triggers in modern dependency graphs (where `cloud.google.com/go` resolves far above v0.26.0). Keep the existing pointer that `OBSOLETE_EXCLUDES_PREFIXES` is the mechanism for actively removing old excludes.

Do NOT add `cloud.google.com/go` to `OBSOLETE_EXCLUDES_PREFIXES` — the change must only STOP ADDING the exclude, never actively strip existing ones from repos that may still need them.

Do NOT change `apply_gomod_excludes_and_replaces`, `read_gomod_excludes_and_replaces`, `STANDARD_REPLACES`, `OBSOLETE_EXCLUDES_PREFIXES`, `OBSOLETE_REPLACES`, or `TOOLS_GO_OBSOLETE_REPLACES`.

## 2. Fix `tests/test_gomod_excludes.py`

Run `make test` and fix every test that assumed `cloud.google.com/go@v0.26.0` is a STANDARD (auto-added) exclude. Specifically:

- `test_apply_adds_cloud_google_standard_exclude` — currently writes an empty go.mod and asserts the exclude IS added. With an empty `STANDARD_EXCLUDES`, nothing is added. Invert it: rename to `test_apply_does_not_add_cloud_google_exclude`, assert `result is False` and that NO call contains `-exclude cloud.google.com/go` (i.e. `not any("cloud.google.com/go" in c for c in calls)`), and that `go mod download` is not called.
- `test_apply_removes_old_non_k8s_excludes` — its docstring says `cloud.google.com/go@v0.26.0 is intentionally retained — it is a STANDARD exclude`. That is no longer true. Update the docstring to: it is left untouched because it is neither a standard exclude (no longer added) nor listed in `OBSOLETE_EXCLUDES_PREFIXES` (not actively removed). The assertions (8 dropexclude + 1 download; no dropexclude for cloud.google.com/go) still hold — keep them.
- `test_apply_excludes_to_empty_gomod` — its docstring says "no-op when standard excludes already present". With no standard excludes, update the docstring to describe that a go.mod containing only a non-standard, non-obsolete exclude produces no changes (nothing to add, nothing to drop). The assertions (`result is False`, 0 commands) still hold — keep them.
- Any other test that breaks after emptying the list: fix its assertion/docstring to match the new behavior (the entry is now neither added nor stripped). Do NOT weaken a test to hide a real behavior change — the only intended behavior change is "the cloud.google.com/go exclude is no longer auto-added".

## 3. CHANGELOG

Add a `## Unreleased` entry (create the section if absent) with a `fix:` bullet, e.g.:
`- fix: stop injecting \`exclude cloud.google.com/go v0.26.0\` into every go.mod (empty STANDARD_EXCLUDES) — it broke \`go install <module>@latest\` fleet-wide; existing excludes are left untouched (not added to OBSOLETE, so nothing is actively stripped).`
</requirements>

<constraints>
- ONLY empty the `STANDARD_EXCLUDES` list + rewrite its comment; do not touch other lists or any function body.
- Do NOT add `cloud.google.com/go` to `OBSOLETE_EXCLUDES_PREFIXES` (would actively strip from repos that may need it — out of scope; those surface a loud `go mod tidy` error and are handled case-by-case).
- Do NOT weaken tests to pass — update them to assert the corrected behavior.
- Follow project Python conventions (pytest, type hints, uv). No new dependencies.
- Do NOT commit — dark-factory handles git.
</constraints>

<verification>
Run `make precommit` — must exit 0 (format + test + lint + typecheck).

Confirm the list is empty and the exclude is gone from the source:
```
grep -nE 'STANDARD_EXCLUDES.*=.*\[\s*\]' src/updater/gomod_excludes.py
grep -c 'cloud.google.com/go@v0.26.0' src/updater/gomod_excludes.py   # expect 0 (only prose may mention it, not as a list entry)
```
First returns a line (empty list); no active `cloud.google.com/go@v0.26.0` list entry remains.

Confirm the add-test was inverted:
```
grep -n 'does_not_add_cloud_google\|cloud.google.com/go' tests/test_gomod_excludes.py
```
The inverted test exists and no test asserts the exclude IS added.

Confirm CHANGELOG:
```
grep -n '## Unreleased' CHANGELOG.md
```
Returns a line; section non-empty.
</verification>

<completion_report_template>
Append the standard DARK-FACTORY-REPORT block with `status`, `verification.command`, `verification.exitCode`. Then an `## Improvements` section (PROMPT / GUIDE / GLOBAL categories, or `- None`).
</completion_report_template>
