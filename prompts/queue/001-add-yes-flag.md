---
status: queued
---

<objective>
Add a `--yes` / `-y` flag to auto-accept all interactive prompts, enabling non-interactive execution in CI/CD and dark-factory containers.
</objective>

<context>
Read src/updater/cli.py for the argument parser and where prompts are called.
Read src/updater/prompts.py for the interactive prompt functions.
Read src/updater/config.py for global config state.

The updater has two interactive prompts that block in non-interactive environments:
1. `prompt_yes_no("Continue anyway?")` — when uncommitted changes are detected (cli.py ~line 486)
2. `prompt_skip_or_retry()` — when a module fails (cli.py ~line 276)

Both use `input()` which hangs when there is no TTY (e.g., Docker containers, CI).
</context>

<requirements>
1. Add `--yes` / `-y` flag to the main argument parser in `main_async()`:
   ```python
   parser.add_argument(
       "--yes", "-y",
       action="store_true",
       help="Auto-accept all prompts (non-interactive mode, for CI/containers)",
   )
   ```
2. Store in config: `config.YES_MODE = args.yes`
3. Add `YES_MODE: bool = False` to `src/updater/config.py`
4. Update `prompt_yes_no()` in `src/updater/prompts.py`:
   - If `config.YES_MODE` is True, return `default_yes` immediately without calling `input()`
   - Log the auto-accepted choice to console
5. Update `prompt_skip_or_retry()` in `src/updater/prompts.py`:
   - If `config.YES_MODE` is True, return `"retry"` (default) immediately without calling `input()`
   - Log the auto-accepted choice to console
6. Add the `--yes` / `-y` flag to ALL other parsers that use interactive prompts:
   - `main_go_async()`
   - `main_go_only_async()`
   - `main_go_with_deps_async()`
   - `main_python_async()`
   - `main_release_async()`
7. Add tests in `tests/` for:
   - `prompt_yes_no()` returns default when `YES_MODE=True`
   - `prompt_skip_or_retry()` returns "retry" when `YES_MODE=True`
8. Update CHANGELOG.md: add entry under `## Unreleased` section (create if missing):
   ```
   ## Unreleased

   - Add `--yes` / `-y` flag for non-interactive mode (auto-accepts all prompts)
   ```
</requirements>

<constraints>
- Do NOT change the default behavior — without `--yes`, prompts must still be interactive
- Do NOT remove the `--require-commit-confirm` flag — it serves a different purpose
- Do NOT skip the sound notifications — they are harmless in non-interactive mode
- Keep backward compatibility — existing scripts without `--yes` must work unchanged
- Follow existing code patterns (config module for global state, prompt module for user interaction)
</constraints>

<verification>
Run `make precommit` — must pass with exit code 0.
Run `uv run pytest` — all tests must pass.
</verification>
