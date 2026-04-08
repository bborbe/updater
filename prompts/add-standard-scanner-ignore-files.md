---
status: draft
created: "2026-04-08T06:40:41Z"
---
<summary>
- Updater distributes standard `.osv-scanner.toml` and `.trivyignore` files to Go modules
- Repos get consistent ignore rules for known unfixable vulnerabilities
- New pipeline step runs early, before precommit, so scanners pass
- Ignore entries are declarative and centralized like STANDARD_REPLACES
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
```

```
# .trivyignore
# github.com/docker/docker indirect dep, no fix available via Go modules
CVE-2026-34040
CVE-2026-33997
```
</context>

<requirements>
1. Create `src/updater/scanner_ignores.py` with:
   - `STANDARD_OSV_IGNORES: list[dict]` — list of `{"id": "GHSA-...", "reason": "..."}` entries
   - `STANDARD_TRIVY_IGNORES: list[dict]` — list of `{"id": "CVE-...", "reason": "..."}` entries
   - `apply_scanner_ignores(module_path: Path, log_func) -> bool` function that:
     - Reads existing `.osv-scanner.toml` if present, parses `[[IgnoredVulns]]` entries
     - Adds missing entries from `STANDARD_OSV_IGNORES` (skip if already present by id)
     - Writes updated `.osv-scanner.toml` — append new standard entries after existing user entries
     - Reads existing `.trivyignore` if present
     - Adds missing CVE lines from `STANDARD_TRIVY_IGNORES` (skip if already present)
     - Writes updated `.trivyignore` — append new standard entries after existing user entries
     - Returns True if any changes were made
   - Use `toml` or manual string building for `.osv-scanner.toml` (check what's available in project deps)
   - Use simple string operations for `.trivyignore`

2. Create `ScannerIgnoresStep` in `src/updater/pipeline.py`:
   - Follow existing step pattern (GoExcludesStep as model)
   - Calls `apply_scanner_ignores(module_path, log_func=log_message)`
   - Log label: pick the next free phase number after existing steps in each pipeline (check `=== Phase` labels in pipeline.py and go_updater.py)

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

6. Run `make precommit` — must pass (also runs via `validationCommand`).
</requirements>

<constraints>
- Do NOT commit or push changes
- Do NOT use external TOML libraries — use string building for `.osv-scanner.toml` (keeps deps minimal)
- Merge, never overwrite — preserve existing user-added ignores
- Follow existing code style and import patterns
</constraints>

<verification>
- `make precommit` passes
- `ScannerIgnoresStep` appears in both Go pipelines
- New tests cover add, merge, and no-op cases
- Existing tests still pass
</verification>
