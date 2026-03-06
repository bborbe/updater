---
status: queued
---
<objective>
Add a max retry limit to `process_module_with_retry` and `process_release_with_retry` in `src/updater/cli.py`.
Currently, when `-y` / `--yes` flag is set (YES_MODE), these functions retry forever on failure because `prompt_skip_or_retry()` always returns "retry". This causes infinite loops when a module consistently fails.
</objective>

<context>
Read CLAUDE.md for project conventions.
Read `src/updater/cli.py` before changing it.
Read `tests/test_cli.py` before adding tests.
Read `src/updater/config.py` to understand YES_MODE.
</context>

<requirements>
1. Add `max_retries: int = 3` parameter to `process_module_with_retry` in `src/updater/cli.py`
2. Add `max_retries: int = 3` parameter to `process_release_with_retry` in `src/updater/cli.py`
3. In both functions: after a failure, if `config.YES_MODE` is True AND `attempt >= max_retries`, print a clear message and return `(False, "skipped")` WITHOUT calling `prompt_skip_or_retry()`. Example message:
   ```
   ✗ Module /path/to/module failed
     -> Max retries (3) reached in -y mode, skipping
   ⚠ Skipping /path/to/module
   ```
4. In interactive mode (YES_MODE = False), behavior is unchanged: prompt forever until user chooses skip.
5. Add tests in `tests/test_cli.py` for:
   - `process_module_with_retry` in YES_MODE auto-skips after max_retries failures
   - `process_module_with_retry` in YES_MODE succeeds on retry before hitting limit
   - `process_module_with_retry` in interactive mode (not YES_MODE) prompts and does not auto-skip based on count
</requirements>

<constraints>
- Do NOT change the default behavior in interactive mode (no max limit when YES_MODE=False)
- Do NOT change the `prompt_skip_or_retry` function in `src/updater/prompts.py`
- Do NOT change function signatures at call sites (max_retries has a default value)
- Keep the `attempt` counter starting at 1 (existing behavior)
- The check is `attempt >= max_retries` (attempt starts at 1, so 3 attempts = 1 initial + 2 retries)
</constraints>

<verification>
Run `make precommit` -- must pass without errors.
</verification>
