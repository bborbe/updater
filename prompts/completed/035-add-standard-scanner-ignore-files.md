---
status: completed
container: updater-035-add-standard-scanner-ignore-files
dark-factory-version: v0.107.5
created: "2026-04-08T06:40:41Z"
queued: "2026-04-08T06:50:48Z"
started: "2026-04-08T06:50:50Z"
completed: "2026-04-08T06:54:41Z"
---
<summary>
- Updater distributes standard `.osv-scanner.toml` and `.trivyignore` files to Go modules
- Repos get consistent ignore rules for known unfixable vulnerabilities
- New pipeline step runs early, before precommit, so scanners pass
- Ignore entries are declarative and centralized in one list
- Existing ignore files are merged, not overwritten
</summary>

<objective>
Automatically ensure Go modules have up-to-date `.osv-scanner.toml` and `.trivyignore` files with standard ignore entries for known unfixable vulnerabilities. This prevents `make precommit` failures from osv-scanner/trivy on indirect deps with no available fix.
</objective>

<context>
Read CLAUDE.md for project conventions and pipeline architecture.
Read src/updater/gomod_excludes.py — understand the pattern: declarative lists (`STANDARD_REPLACES`) + function that applies them to a module.
Read src/updater/pipeline.py — understand Step base class pattern and existing steps.
Read src/updater/cli.py — find all Go pipelines that include `PrecommitStep` (the step where scanners run and fail).

Reference files to distribute:
- `.osv-scanner.toml` format: `[[IgnoredVulns]]` with `id` and `reason` fields
- `.trivyignore` format: comment line + CVE IDs, one per line

Current known unfixable vulns (these are the initial entries — verify IDs are still valid):
```toml
# .osv-scanner.toml
[[IgnoredVulns]]
id = "GHSA-pxq6-2prw-chj9"
reason = "github.com/docker/docker indirect dep, no fix available"

[[IgnoredVulns]]
id = "GHSA-x744-4wpc-v9h2"
reason = "github.com/docker/docker indirect dep, no fix available"

[[IgnoredVulns]]
id = "GO-2026-4923"
reason = "go.etcd.io/bbolt v1.4.3 dep, no fix available"
```

```
# .trivyignore
# github.com/docker/docker indirect dep, no fix available via Go modules
CVE-2026-34040
CVE-2026-33997

# go.etcd.io/bbolt v1.4.3 dep, no fix available
CVE-2026-33817
```
</context>

<requirements>
1. Create `src/updater/scanner_ignores.py` with:
   - `STANDARD_OSV_IGNORES: list[dict]` — list of `{"id": "GHSA-...", "reason": "..."}` entries
   - `STANDARD_TRIVY_IGNORES: list[dict]` — list of `{"id": "CVE-...", "reason": "..."}` entries. When writing `.trivyignore`, emit the `reason` as a `# comment` line immediately before the CVE id. Multiple CVEs sharing the same reason may be grouped under one comment (see example in `<context>`), but a simpler per-entry comment is also acceptable.
   - `apply_scanner_ignores(module_path: Path, log_func) -> bool` function that:
     - Reads existing `.osv-scanner.toml` if present, parses `[[IgnoredVulns]]` entries
     - Adds missing entries from `STANDARD_OSV_IGNORES` (skip if already present by id)
     - Writes updated `.osv-scanner.toml` — append new standard entries after existing user entries
     - Reads existing `.trivyignore` if present
     - Adds missing CVE lines from `STANDARD_TRIVY_IGNORES` (skip if already present)
     - Writes updated `.trivyignore` — append new standard entries after existing user entries
     - Returns True if any changes were made
   - Use manual string building for `.osv-scanner.toml` — no external TOML libraries
   - Use simple string operations for `.trivyignore`

2. Create `ScannerIgnoresStep` in `src/updater/pipeline.py`:
   - Follow existing step pattern (`GoExcludesStep` at line 108 as model)
   - Calls `apply_scanner_ignores(module_path, log_func=log_message)`
   - Log with a descriptive label (e.g. `=== Apply Scanner Ignores ===`) — phase numbering not required

3. Wire `ScannerIgnoresStep` into ALL Go pipelines in `src/updater/cli.py`:
   - Add after `GoExcludesStep` and before `OsvFixStep`/`PrecommitStep`
   - Must be in: `process_single_go_module`, `process_single_go_fix_module`
   - Verify these function names exist before editing (they should be in cli.py)

4. Update CLAUDE.md pipeline table to include the new step.

5. Add tests in `tests/test_scanner_ignores.py`:
   - Test adding ignores to empty/missing files
   - Test merging with existing entries (no duplicates)
   - Test no changes when all entries present
   - Follow existing test patterns

6. Run `make precommit` — must pass.
</requirements>

<constraints>
- Do NOT commit or push changes
- Do NOT use external TOML libraries — use string building for `.osv-scanner.toml` (keeps deps minimal)
- Merge, never overwrite — preserve existing user-added ignores
- Follow existing code style and import patterns
</constraints>

<verification>
Run `make precommit` — must pass.
</verification>
