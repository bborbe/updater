# Dependency Updater

Multi-language dependency updater with Claude-powered CHANGELOG generation and commit messages.

**Supported Languages:** Go, Python | Node.js (planned)

## Install

```bash
uv tool install git+https://github.com/bborbe/updater
```

## Upgrade

```bash
uv tool upgrade updater
```

## Quick Start

```bash
# Auto-detect language and update
update-deps /path/to/module

# Language-specific
update-go /path/to/go-module
update-python /path/to/python-project
update-docker /path/to/project  # Dockerfile base images only, no commit

# Multiple modules or parent directory (discovers recursively)
update-deps /path/to/moduleA /path/to/moduleB
update-deps /path/to/modules

# Options
update-deps /path/to/module --verbose               # Show all output
update-deps /path/to/module --model haiku           # Choose Claude model (default: sonnet)
update-deps /path/to/module --require-commit-confirm  # Confirm before committing
```

## How It Works

**Go modules:**
1. **Update versions** - golang, alpine (Dockerfile, go.mod, CI configs)
2. **Apply excludes/replaces** - Standard go.mod exclusions for problematic versions
3. **Update dependencies** - Iterative `go get -u`
4. **Run validation** - `make precommit` (tests, linters, formatting)
5. **Analyze changes** - Claude determines version bump and generates CHANGELOG entries
6. **Commit & tag** - Git commit with Claude-generated message, git tag from CHANGELOG

**Python projects** (requires `pyproject.toml` + `uv.lock`):
1. **Update Python version** - `.python-version`, `pyproject.toml`, Dockerfile
2. **Update dependencies** - `uv sync --upgrade`
3. **Run validation** - `make precommit`
4. **Analyze changes** - Claude determines version bump and generates CHANGELOG entries
5. **Commit & tag** - Git commit with Claude-generated message, git tag from CHANGELOG

### Retry/Skip on Failure

If a module fails, you'll be prompted:

```
✗ Module lib/alert failed
  → Fix the issues and retry, or skip this module

Skip or Retry? [s/R]:
```

- **Retry (R)**: Fix the issue, press R to retry from Phase 1
- **Skip (s)**: Skip this module and continue to next

## Commands

| Command | Description |
|---------|-------------|
| `update-deps` / `update-all` | Auto-detect Go/Python and update |
| `update-go` | Go modules with dependencies (same as `update-go-with-deps`) |
| `update-go-only` | Go version updates only (no dependency updates) |
| `update-go-with-deps` | Go versions and dependencies (explicit name) |
| `update-python` | Python projects only (requires `pyproject.toml` + `uv.lock`) |
| `update-docker` | Dockerfile base images only (no commit) |
| `release-only` | Release unreleased CHANGELOG entries (version bump, commit, tag, push) |

## Requirements

- **[uv](https://docs.astral.sh/uv/)** - `curl -LsSf https://astral.sh/uv/install.sh | sh`
- `ANTHROPIC_API_KEY` environment variable
- Git repository
- For Go modules: `CHANGELOG.md` in module/package
- For Python projects: `pyproject.toml` + `uv.lock` (legacy `requirements.txt` not supported)

## Features

- **Claude-powered CHANGELOG** - Analyzes changes and generates meaningful entries
- **Smart version bumping** - MAJOR/MINOR/PATCH for code/deps, NONE for infrastructure
- **Multi-language support** - Go modules and Python projects (uv-based)
- **Monorepo support** - Recursive discovery with smart lib/-first ordering
- **Idempotent** - Skips modules already up-to-date
- **Version updates** - golang, alpine, python (Dockerfile, go.mod, pyproject.toml, CI)
- **Clean output** - Quiet mode with per-module logs (`.update-logs/`)
- **Legacy project detection** - Warns about `requirements.txt` projects

## Documentation

- [Monorepo Mode](docs/monorepo-mode.md)
- [Version Bumping](docs/version-bumping.md)
- [Logging](docs/logging.md)
- [Development](docs/development.md)
- [Roadmap](docs/roadmap.md)

## License

BSD 2-Clause - see [LICENSE](LICENSE).
