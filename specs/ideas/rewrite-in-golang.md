---
status: idea
---

## Summary

- Rewrite the dependency-updater from Python to Go
- The main reason for Python (claude-code-sdk) has been removed — now uses `claude --print -p` subprocess calls
- Go is the primary language across all other projects (dark-factory, etc.)
- Single static binary — no venv, no uv, no Python version management
- All existing functionality preserved: go/python/docker update pipelines, Claude-powered analysis, changelog generation

## Problem

The updater is the only Python project in an otherwise all-Go ecosystem. After dropping the claude-code-sdk (v0.17.6), the only Python-specific dependency is gone — Claude integration is now a subprocess call that works identically from any language. Maintaining a Python project adds friction: separate toolchain (uv, venv, pip), different testing patterns (pytest vs go test), different CI setup, and context-switching cost.

## Goal

A single `updater` Go binary that replaces all current `update-*` commands with identical behavior, distributed as a static binary without runtime dependencies.

## Non-goals

- Changing any pipeline logic, step order, or behavior
- Adding new features during the rewrite
- Supporting both Python and Go versions simultaneously
- Changing the Claude prompt text or JSON response formats

## Do-Nothing Option

Keep Python. It works after the SDK fix. Cost: ongoing maintenance friction, separate toolchain, but no functional impact. Acceptable if rewrite effort is too high relative to maintenance burden.
