---
status: created
---

<summary>
- The release summary (version, tag, changelog entries) appears in the per-module log file
- All pipeline steps now consistently use the same output mechanism
- No behavior change for the user — same release summary appears on console
- The release summary can be reviewed after the fact in `.update-logs/` without re-running
- Only the release step is changed; all other steps are untouched
</summary>

<objective>
The release step's summary output (version bump, tag, changelog entries) is not captured in the per-module log file because it writes directly to stdout. All other pipeline steps write to the log file. The release step should do the same for consistency and post-run debugging.
</objective>

<context>
Read CLAUDE.md for project conventions.
Read `src/updater/pipeline.py`, specifically `ReleaseStep.run()` around lines 558-567.

`log_message` is already imported: `from .log_manager import log_message` (line 38). The pattern used by all other steps: `log_message("text", to_console=True)`.

Current code uses `print()` directly:
```python
print("\n" + "=" * 60)
print(f"READY TO RELEASE: {module_path.name}")
print("=" * 60)
print(f"Version:        {old_version} → {new_version} ({analysis['version_bump']} bump)")
print(f"Commit message: Release {new_version}")
print(f"Git tag:        {new_version}")
print("\nUnreleased entries:")
for entry in entries:
    print(f"  {entry}")
print("=" * 60)
```

All other pipeline steps use `log_message(..., to_console=True)`. This step bypasses logging, so the release summary never appears in `.update-logs/*.log`.
</context>

<requirements>
1. Replace all `print()` calls in `ReleaseStep.run()` (lines ~558-567) with `log_message(..., to_console=True)`
</requirements>

<constraints>
- Do NOT change the text content of the messages
- Do NOT change any other pipeline step
- Do NOT commit — dark-factory handles git
</constraints>

<verification>
Run `make precommit` — must pass with exit code 0.
</verification>
