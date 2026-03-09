---
status: completed
summary: Replaced traceback.print_exc() with log_message(traceback.format_exc(), to_console=config.VERBOSE_MODE) in all three exception handlers so tracebacks are always written to the module log file.
container: updater-014-log-tracebacks-always
dark-factory-version: v0.30.17-dirty
created: "2026-03-09T20:55:36Z"
queued: "2026-03-09T20:55:36Z"
started: "2026-03-09T20:59:48Z"
completed: "2026-03-09T21:00:35Z"
---

<summary>
- Error tracebacks are always captured in the per-module log file for later debugging
- Console output is unchanged — tracebacks still only appear in verbose mode
- Debugging failures no longer requires reproducing the issue with --verbose
- The fix is identical in all three affected error handlers
- No new error handlers are added; no error messages change
</summary>

<objective>
When a module update fails, the full error traceback is lost unless the user happened to run with --verbose. The traceback should always be written to the module's log file so failures can be diagnosed after the fact without re-running.
</objective>

<context>
Read CLAUDE.md for project conventions.
Read `src/updater/cli.py`.

Three identical patterns at lines ~145-149, ~225-229, ~1138-1142:
```python
except Exception as e:
    log_message(f"\n✗ Error processing {module_path}: {e}", to_console=True)
    if config.VERBOSE_MODE:
        traceback.print_exc()
    return (False, "failed")
```

`traceback.print_exc()` writes to stderr directly — it bypasses `log_message()` entirely, so the traceback is never written to the `.update-logs/*.log` file. In non-verbose mode, the traceback is permanently lost.
</context>

<requirements>
1. In all three exception handlers, replace:
   ```python
   if config.VERBOSE_MODE:
       traceback.print_exc()
   ```
   with:
   ```python
   log_message(traceback.format_exc(), to_console=config.VERBOSE_MODE)
   ```
   This writes the traceback to the log file always, and to console only in verbose mode.

2. Ensure `traceback` is imported (it already is — verify).
</requirements>

<constraints>
- Do NOT change error messages or return values
- Do NOT add new exception handlers
- Do NOT commit — dark-factory handles git
</constraints>

<verification>
Run `make precommit` — must pass with exit code 0.
</verification>
