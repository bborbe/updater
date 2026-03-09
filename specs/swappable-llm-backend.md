---
status: draft
---

## Summary

- The updater currently hardcodes Claude Code SDK as its only LLM backend for analyzing changes and generating changelogs
- Rate limit errors and SDK bugs (e.g. unknown message types) cause failures that require full restarts
- Introduce a swappable backend so users can choose between Claude Code SDK and Gemini CLI
- A `--backend` flag selects the backend; default remains Claude
- Backend selection affects only the LLM calls, not the update pipeline logic

## Problem

The updater depends entirely on Claude Code SDK for change analysis, version bump decisions, and changelog generation. When Claude hits rate limits or the SDK encounters unknown message types (e.g. `rate_limit_event`), the entire update process fails. There is no fallback. Users must restart and hope the issue resolved. Having an alternative backend (Gemini CLI) provides resilience and lets users choose based on cost, speed, or availability.

## Goal

After this work, the updater supports multiple LLM backends behind a common interface. Users select a backend via `--backend claude|gemini`. The default remains Claude with identical behavior to today. A Gemini backend provides an alternative when Claude is unavailable or rate-limited.

## Non-goals

- OpenAI or other backends (future work)
- Gemini API (google-genai SDK) — CLI is simpler and sufficient
- Changing the prompts themselves (reuse existing prompt templates)
- Parallel/fallback chains (use backend A, fall back to B)

## Assumptions

- Gemini CLI (`gemini`) accepts prompts via stdin and returns text to stdout
- Gemini CLI has a stable interface for non-interactive prompt execution
- Both LLMs can produce structured JSON when instructed to do so

## Desired Behavior

1. `update-go --backend gemini` uses Gemini CLI for all LLM analysis
2. `update-go --backend claude` uses Claude Code SDK (current behavior, also the default)
3. `update-go` without `--backend` defaults to `claude`
4. Auth check is backend-specific: Claude checks OAuth, Gemini checks CLI availability
5. Both backends produce identical JSON output format for the same prompts
6. Rate limit and timeout retry logic is backend-specific (each backend recognizes its own error patterns)

## Constraints

- Existing tests must still pass unchanged
- Backend-specific code must not leak into the shared pipeline layer
- Prompts (the text sent to the LLM) remain identical across backends
- JSON response parsing remains identical across backends
- `config.MODEL` continues to work (passed to selected backend)
- `--check-command` and all other existing flags unchanged
- No new Python package dependencies may be added for the Gemini backend

## Failure Modes

| Trigger | Expected behavior | Recovery |
|---------|-------------------|----------|
| Gemini CLI not installed | Auth check fails with actionable install instructions | User installs CLI |
| Gemini returns non-JSON | Same JSON parse error handling as Claude path | Retry with backoff |
| Gemini rate limited | Retry with appropriate delays | Exponential backoff |
| Gemini subprocess exceeds timeout | Process killed, error returned to caller | Caller retries or user aborts |
| Invalid `--backend` value | Argparse error listing valid choices | User corrects flag |
| `--model` incompatible with backend | LLM returns error, propagated with backend context | User corrects model |

## Security / Abuse Cases

- `--model` and `--backend` are CLI arguments from the local user who already has shell access — no privilege escalation
- Gemini CLI is invoked via subprocess; prompt content is passed via stdin/tempfile, not interpolated into shell commands — no command injection
- No network-facing surface; all invocations are local CLI tool calls
- Subprocess timeout must be enforced to prevent hangs

## Acceptance Criteria

- [ ] Running `update-go --backend gemini` completes change analysis without invoking Claude SDK
- [ ] Running `update-go --backend claude` produces identical behavior to current (no `--backend` flag)
- [ ] Running `update-go` without `--backend` defaults to Claude
- [ ] Auth check fails with actionable error when selected backend is unavailable
- [ ] Unit tests assert both backends parse a fixture response into the same output structure
- [ ] All existing tests pass without modification
- [ ] New tests verify Gemini backend with mocked subprocess calls
- [ ] New tests verify backend selection and default behavior

## Verification

```
make precommit
```

## Do-Nothing Option

Keep Claude-only. When rate limited, wait and retry manually. Acceptable short-term, but limits resilience and locks into a single provider. The `rate_limit_event` SDK bug showed how fragile single-backend dependency is.
