---
status: draft
---

## Summary

- The updater currently hardcodes Claude CLI as its only LLM backend for analyzing changes and generating changelogs
- Rate limit errors and timeouts cause failures that require manual retry
- Add Gemini CLI and Codex CLI as alternative backends
- The existing `--model` flag gains a `backend:model` format to select backend and model in one argument
- Backend selection affects only the LLM calls, not the update pipeline logic

## Problem

The updater depends entirely on Claude CLI for change analysis, version bump decisions, and changelog generation. When Claude hits rate limits or times out, the entire update process stalls. There is no fallback. Having alternative backends (Gemini CLI, Codex CLI) provides resilience and lets users choose based on cost, speed, or availability.

## Goal

After this work, the updater supports multiple LLM backends behind a common interface. Users select a backend and model via `--model backend:model`. The default remains Claude with identical behavior to today. Gemini and Codex backends provide alternatives when Claude is unavailable or rate-limited.

## Non-goals

- API-based backends (google-genai SDK, OpenAI SDK) — CLI tools are simpler and sufficient
- Changing the prompts themselves (reuse existing prompt templates)
- Parallel/fallback chains (use backend A, fall back to B)
- Auto-detection of available backends

## Assumptions

- All three CLIs accept prompts and return text to stdout in non-interactive mode
- All three CLIs have a stable interface for non-interactive prompt execution
- All three LLMs can produce structured JSON when instructed to do so

## CLI Interface Mapping

| Feature | Claude | Gemini | Codex |
|---------|--------|--------|-------|
| Binary | `claude` | `gemini` | `codex` |
| Non-interactive | `--print -p <prompt>` | `-p <prompt>` | `exec <prompt>` |
| Output format | `--output-format text` | `--output-format text` | `--json` (JSONL) or `-o <file>` |
| Model flag | `--model <m>` | `-m <m>` | `-m <m>` |
| Auto-approve tools | N/A (--print is non-agentic) | `--yolo` | `--full-auto` |
| Working dir | `cwd=` parameter | `cwd=` parameter | `--cd <dir>` or `cwd=` |
| Stdin | `DEVNULL` (required) | `DEVNULL` (required) | `DEVNULL` (required) |

## `--model` Flag Format

The `--model` flag uses a `backend:model` format to combine backend selection and model choice:

```
--model claude:sonnet      # Claude backend, sonnet model
--model gemini:gemini-2.5-pro  # Gemini backend, specific model
--model codex:o3           # Codex backend, o3 model
--model gemini             # Gemini backend, default model
--model claude             # Claude backend, default model (same as no flag)
--model sonnet             # Claude backend, sonnet model (backward compat)
```

Parsing logic:

```python
def parse_model(value: str | None) -> tuple[str, str | None]:
    """Parse --model value into (backend, model).

    Returns:
        (backend_name, model_or_none)
    """
    if value is None:
        return ("claude", None)

    known_backends = {"claude", "gemini", "codex"}
    backend, _, model = value.partition(":")

    if backend in known_backends:
        return (backend, model or None)

    # No colon or unknown prefix → assume Claude backend, entire value is model name
    # e.g. "--model sonnet" → ("claude", "sonnet")
    return ("claude", value)
```

## Desired Behavior

1. `update-all --model gemini` uses Gemini CLI with default model
2. `update-all --model gemini:gemini-2.5-pro` uses Gemini CLI with specific model
3. `update-all --model codex:o3` uses Codex CLI with o3
4. `update-all --model claude:sonnet` uses Claude CLI with sonnet (also the default)
5. `update-all --model sonnet` backward compatible — Claude backend, sonnet model
6. `update-all` without `--model` defaults to Claude with default model
7. Auth check is backend-specific: each backend verifies its own CLI availability and auth
8. All backends produce identical JSON output format for the same prompts
9. Rate limit and timeout retry logic is backend-specific (each backend recognizes its own error patterns)

## Architecture

### Backend Interface

```python
class LLMBackend(Protocol):
    async def run(self, prompt: str, cwd: Path | None, timeout: int) -> str:
        """Send prompt, return text response. Raise LLMError on failure."""
        ...

    async def verify_auth(self) -> tuple[bool, str]:
        """Check backend is available and authenticated."""
        ...

    @property
    def name(self) -> str: ...
```

### Backend Implementations

Each backend is a thin wrapper around subprocess exec:

- `ClaudeBackend` — wraps current `_run_claude()` logic
  - `claude --print -p <prompt> --output-format text [--model <m>]`
- `GeminiBackend` — `gemini -p <prompt> --output-format text --yolo [-m <m>]`
- `CodexBackend` — `codex exec <prompt> --full-auto [-m <m>]`

### Factory

```python
def create_backend(model_spec: str | None) -> LLMBackend:
    backend, model = parse_model(model_spec)
    match backend:
        case "claude": return ClaudeBackend(model)
        case "gemini": return GeminiBackend(model)
        case "codex":  return CodexBackend(model)
        case _: raise ValueError(f"Unknown backend: {backend}")
```

### Integration Point

`claude_analyzer.py` becomes `llm_analyzer.py`. The module-level functions (`analyze_changes_with_claude`, `verify_claude_auth`, etc.) become backend-agnostic by accepting a backend instance:

```python
async def analyze_changes(backend: LLMBackend, module_path: Path, ...) -> dict:
    response = await backend.run(prompt, cwd=module_path, timeout=120)
    return _extract_json_from_response(response)
```

## Constraints

- Existing tests must still pass unchanged
- Backend-specific code must not leak into the shared pipeline layer
- Prompts (the text sent to the LLM) remain identical across backends
- JSON response parsing remains identical across backends
- `--model sonnet` (without colon) must remain backward compatible with current behavior
- `--check-command` and all other existing flags unchanged
- No new Python package dependencies may be added
- All subprocess calls must set `stdin=DEVNULL`

## Failure Modes

| Trigger | Expected behavior | Recovery |
|---------|-------------------|----------|
| CLI not installed | Auth check fails with install instructions | User installs CLI |
| Backend returns non-JSON | Same JSON parse error handling for all backends | Retry with backoff |
| Rate limited | Retry with backend-specific delays | Exponential backoff |
| Subprocess exceeds timeout | Process killed, error returned | Caller retries or user skips |
| Invalid backend in `--model` | Error listing valid backends (claude, gemini, codex) | User corrects flag |
| Model incompatible with backend | LLM returns error, propagated with backend context | User corrects model |

## Security / Abuse Cases

- `--model` is a CLI argument from the local user who already has shell access — no privilege escalation
- All CLIs are invoked via subprocess; prompt content is passed as arguments, not interpolated into shell commands — no command injection
- No network-facing surface; all invocations are local CLI tool calls
- Subprocess timeout must be enforced to prevent hangs
- `stdin=DEVNULL` on all subprocesses to prevent terminal corruption

## Acceptance Criteria

- [ ] `update-all --model gemini` completes change analysis using Gemini CLI
- [ ] `update-all --model codex:o3` completes change analysis using Codex CLI
- [ ] `update-all --model claude:sonnet` produces identical behavior to current `--model sonnet`
- [ ] `update-all --model sonnet` backward compatible (Claude backend, sonnet model)
- [ ] `update-all` without `--model` defaults to Claude with default model
- [ ] Auth check fails with actionable error when selected backend CLI is unavailable
- [ ] Unit tests assert all backends parse a fixture response into the same output structure
- [ ] All existing tests pass without modification
- [ ] New tests verify Gemini and Codex backends with mocked subprocess calls
- [ ] New tests verify `parse_model()` with all input variants

## Verification

```
make precommit
```

## Do-Nothing Option

Keep Claude-only. When rate limited, wait and retry manually. Acceptable short-term, but limits resilience and locks into a single provider.
