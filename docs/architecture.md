# Architecture

## Design Principle

The updater is built around **composable, independent steps** that can be used standalone or chained together. Each command the user calls is a **recipe** — a list of steps executed in sequence.

## Pipeline Steps

A module update follows a pipeline. Each step is independent and only modifies files or git state:

```
┌─────────────┐    ┌────────────┐    ┌───────────┐    ┌─────────┐    ┌─────┐
│  Updaters   │ →  │ Precommit  │ →  │ Changelog │ →  │ Release │ →  │ Git │
│  (modify    │    │ (validate) │    │ (analyze  │    │(promote │    │(com-│
│   files)    │    │            │    │  + write) │    │ + tag)  │    │mit +│
│             │    │            │    │           │    │         │    │push)│
└─────────────┘    └────────────┘    └───────────┘    └─────────┘    └─────┘
```

### 1. Updaters (modify files, no git operations)

Each updater focuses on one concern. Multiple updaters can run in sequence on the same module.

| Updater | What it updates |
|---------|----------------|
| `GoVersionUpdater` | Go version in go.mod, Dockerfile, CI configs |
| `GoDepUpdater` | Go dependencies via `go get -u` + excludes/replaces |
| `PythonVersionUpdater` | Python version in .python-version, pyproject.toml, Dockerfile |
| `PythonDepUpdater` | Python dependencies via `uv sync --upgrade` |
| `DockerUpdater` | Base image versions in Dockerfile (golang, python, alpine) |

**Contract:** Updaters only modify files on disk. They return whether changes were made. They never commit, tag, or push.

### 2. Precommit (validate)

Runs `make precommit` (or equivalent) to validate the changes compile, pass tests, and are properly formatted.

**Contract:** May modify files (auto-formatting). Raises on failure (with retry/skip prompt).

### 3. Changelog (analyze + write)

Analyzes the diff (via Claude) and writes CHANGELOG.md entries.

Two modes:
- **Versioned** — Creates `## vX.Y.Z` section directly (single-step workflow)
- **Unreleased** — Adds entries under `## Unreleased` (two-step workflow, released later)

**Contract:** Modifies CHANGELOG.md only. Returns version info.

### 4. Release (promote + tag)

Promotes `## Unreleased` entries to a versioned section. Determines version bump from the existing bullet points (via Claude).

**Contract:** Modifies CHANGELOG.md. Creates git tag. Only runs when `## Unreleased` has entries.

### 5. Git (commit + push)

Commits all staged changes and pushes to origin (including tags).

**Contract:** Git operations only. No file modifications.

## User-Facing Commands (Recipes)

Each command is a recipe — a specific combination of pipeline steps:

| Command | Steps |
|---------|-------|
| `update-go` | GoVersionUpdater → GoDepUpdater → Precommit → Changelog(versioned) → Git |
| `update-go-only` | GoVersionUpdater → Precommit → Changelog(versioned) → Git |
| `update-go-with-deps` | GoVersionUpdater → GoDepUpdater → Precommit → Changelog(versioned) → Git |
| `update-python` | PythonVersionUpdater → PythonDepUpdater → Precommit → Changelog(versioned) → Git |
| `update-docker` | DockerUpdater → Git |
| `update-all` | All updaters → Precommit → Changelog(versioned) → Git |
| `release-only` | Release → Git |

### The `--no-tag` flag

Changes the Changelog step from **versioned** to **unreleased** mode, and skips tagging:

| Command | Steps with `--no-tag` |
|---------|----------------------|
| `update-go --no-tag` | GoVersionUpdater → GoDepUpdater → Precommit → Changelog(unreleased) → Git |
| `update-all --no-tag` | All updaters → Precommit → Changelog(unreleased) → Git |

This enables a two-step workflow:
1. `update-all --no-tag` → updates + commits with `## Unreleased`
2. `release-only` → promotes unreleased → versioned + tag + push

## Module Discovery

All commands accept one or more paths. The discovery system finds modules by type:

- **Go modules**: directories containing `go.mod`
- **Python modules**: directories containing `pyproject.toml` + `uv.lock`
- **Docker projects**: directories containing `Dockerfile` (not part of Go/Python project)

For monorepos, `lib/` modules are processed before root modules (dependency ordering).

## Error Handling

- Each module processes independently (one failure doesn't stop others)
- On failure: prompt for **Skip** or **Retry**
- Retry re-runs the full pipeline for that module from step 1
- Summary at the end shows: updated / up-to-date / skipped / failed

## Current State vs Target

**Current:** Steps are interleaved within monolithic `process_single_go_module()` / `process_single_python_module()` functions. The pipeline is implicit.

**Target:** Extract each step into independent, composable units. Commands become explicit pipelines. This enables:
- Easier testing of individual steps
- New commands by combining existing steps
- Clearer separation of concerns
- Potential parallel execution of independent updaters
