---
status: completed
summary: Removed k8s excludes/replaces from STANDARD_EXCLUDES/STANDARD_REPLACES and added OBSOLETE_EXCLUDES_PREFIXES/OBSOLETE_REPLACES with cleanup logic to drop stale entries from projects during updates
container: updater-025-remove-k8s-excludes-replaces
dark-factory-version: v0.57.5
created: "2026-03-18T10:03:36Z"
queued: "2026-03-18T10:03:36Z"
started: "2026-03-18T10:03:43Z"
completed: "2026-03-18T10:06:39Z"
---
<summary>
- The updater no longer injects kube-openapi replace directives into any Go module
- The updater no longer adds k8s version excludes (k8s.io/api, apimachinery, client-go, etc.) to Go modules
- The updater no longer adds structured-merge-diff/v6 version excludes to Go modules
- When the updater runs on a project, it actively removes any existing kube-openapi replace directives
- When the updater runs on a project, it actively removes any existing k8s-related and structured-merge-diff/v6 excludes
- Projects like vault-cli that don't use k8s will have clean go.mod files after the next updater run
- Projects that do use k8s (like bborbe/k8s) also get cleaned up since we now use the latest k8s.io + structured-merge-diff/v6 natively
</summary>

<objective>
Remove all k8s-related workarounds (kube-openapi replace, k8s version excludes, structured-merge-diff/v6 excludes) from the updater AND make the updater actively clean up these entries from projects it updates. The k8s ecosystem has been upgraded to the latest version which uses structured-merge-diff/v6 natively, so these workarounds are no longer needed.
</objective>

<context>
Read CLAUDE.md for project conventions.
Read `src/updater/gomod_excludes.py` — this is the only file that needs changes.

Background: The `STANDARD_EXCLUDES` list contains entries for k8s.io/api, k8s.io/apiextensions-apiserver, k8s.io/apimachinery, k8s.io/client-go, k8s.io/code-generator (various versions from v0.34.0 through v0.35.2), and sigs.k8s.io/structured-merge-diff/v6 (v6.0.0 through v6.3.0). The `STANDARD_REPLACES` list contains a kube-openapi replace. These were workarounds for k8s dependency conflicts that are now resolved by upgrading to the latest k8s.io versions.

The function `apply_gomod_excludes_and_replaces()` currently only ADDS excludes and replaces. It needs to also REMOVE obsolete ones.
</context>

<requirements>
1. In `src/updater/gomod_excludes.py`, remove ALL k8s-related entries from `STANDARD_EXCLUDES`:
   - Remove all `k8s.io/api@*` entries (lines 19-27)
   - Remove all `k8s.io/apiextensions-apiserver@*` entries (lines 28-36)
   - Remove all `k8s.io/apimachinery@*` entries (lines 37-45)
   - Remove all `k8s.io/client-go@*` entries (lines 46-54)
   - Remove all `k8s.io/code-generator@*` entries (lines 55-63)
   - Remove all `sigs.k8s.io/structured-merge-diff/v6@*` entries (lines 64-67)
   - Keep the non-k8s entries (cloud.google.com/go, go-logr, go.yaml.in, golang.org/x/tools)

2. Empty the `STANDARD_REPLACES` list completely (remove the kube-openapi entry at line 74). Keep the list variable but make it empty: `STANDARD_REPLACES = []`

3. Add a new constant `OBSOLETE_EXCLUDES` — a list of exclude patterns that should be REMOVED from projects when found. Use module prefix patterns:
   ```python
   OBSOLETE_EXCLUDES_PREFIXES = [
       "k8s.io/api@",
       "k8s.io/apiextensions-apiserver@",
       "k8s.io/apimachinery@",
       "k8s.io/client-go@",
       "k8s.io/code-generator@",
       "sigs.k8s.io/structured-merge-diff/v6@",
   ]
   ```

4. Add a new constant `OBSOLETE_REPLACES` — a list of module names whose replace directives should be REMOVED:
   ```python
   OBSOLETE_REPLACES = [
       "k8s.io/kube-openapi",
   ]
   ```

5. In function `apply_gomod_excludes_and_replaces()`, AFTER the existing add-excludes and add-replaces logic, add new logic to remove obsolete entries:
   - For each exclude in `existing_excludes`, check if it starts with any prefix in `OBSOLETE_EXCLUDES_PREFIXES`. If so, run `go mod edit -dropexclude {module}@{version}` and log `  → Removing obsolete exclude: {exclude}`
   - For each replace key in `existing_replaces`, check if it is in `OBSOLETE_REPLACES`. If so, run `go mod edit -dropreplace {old_module}` and log `  → Removing obsolete replace: {old_module}`
   - Set `changes_made = True` for each removal

6. Update the "All excludes and replaces already present" log message to also account for removals. Change it to "All excludes and replaces up to date" or similar.
</requirements>

<constraints>
- Do NOT commit — dark-factory handles git
- Existing tests must still pass
- Keep the same code style and patterns as the existing file
- Only modify `src/updater/gomod_excludes.py` — no other files
- The `OBSOLETE_EXCLUDES_PREFIXES` approach allows matching any version of a module, not just specific versions — this is future-proof
</constraints>

<verification>
Run `make precommit` -- must pass.
</verification>
