# Dependency Updater

Multi-language dependency updater with Claude-powered CHANGELOG generation and commit messages.

**Supported Languages:** Go, Python | Node.js (planned)

## Installation

From GitHub:
```bash
# Auto-detect language (Go or Python)
uvx --from git+https://github.com/bborbe/updater update-deps /path/to/module

# Language-specific commands
uvx --from git+https://github.com/bborbe/updater update-go /path/to/go-module
uvx --from git+https://github.com/bborbe/updater update-python /path/to/python-project
uvx --from git+https://github.com/bborbe/updater update-docker /path/to/project  # Dockerfile only

# Multiple specific modules (explicit paths)
uvx --from git+https://github.com/bborbe/updater update-deps /path/to/moduleA /path/to/moduleB /path/to/moduleC

# Parent directory (discovers all recursively, including nested)
uvx --from git+https://github.com/bborbe/updater update-deps /path/to/modules

# Monorepo (discovers all nested modules with smart ordering)
cd /path/to/monorepo
uvx --from git+https://github.com/bborbe/updater update-deps .
```

Local development:
```bash
# Run from local directory
uv --directory /path/to/updater run update-deps /path/to/module --verbose

# Or with uvx --reinstall (picks up latest changes)
uvx --reinstall --from /path/to/updater update-deps /path/to/module --verbose

# Multiple specific modules
uvx --reinstall --from /path/to/updater update-deps ~/workspace/raw ~/workspace/k8s ~/workspace/jira
```

## Usage

The tool follows this workflow:

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

**Dockerfile only** (`update-docker`):
1. **Update base images** - python, golang, alpine versions in Dockerfile
2. No commit (changes only)

### Options

```bash
# Verbose mode (show all output in console)
uvx --from git+https://github.com/bborbe/updater update-deps /path/to/module --verbose

# Choose Claude model (default: sonnet)
uvx --from git+https://github.com/bborbe/updater update-deps /path/to/module --model haiku

# Require confirmation before commits (default: auto-commit)
uvx --from git+https://github.com/bborbe/updater update-deps /path/to/module --require-commit-confirm

# Multiple modules with options
uvx --from git+https://github.com/bborbe/updater update-deps /path/to/module1 /path/to/module2 --verbose
```

### Retry/Skip on Failure

If a module fails (tests, precommit errors), you'll be prompted:

```
✗ Module lib/alert failed
  → Fix the issues and retry, or skip this module

Skip or Retry? [s/R]:
```

- **Retry (R)**: Fix the issue, press R to retry from Phase 1
- **Skip (s)**: Skip this module and continue to next

## Entry Points

| Command | Description |
|---------|-------------|
| `update-deps` / `update-all` | Auto-detect Go/Python and update |
| `update-go` | Go modules only |
| `update-python` | Python projects only (requires `pyproject.toml` + `uv.lock`) |
| `update-docker` | Dockerfile base images only (no commit) |

## Features

- **Claude-powered CHANGELOG** - Analyzes changes and generates meaningful entries
- **Smart version bumping** - MAJOR/MINOR/PATCH for code/deps, NONE for infrastructure
- **Multi-language support** - Go modules and Python projects (uv-based)
- **Monorepo support** - Recursive discovery with smart lib/-first ordering
- **Idempotent** - Skips modules already up-to-date
- **Version updates** - golang, alpine, python (Dockerfile, go.mod, pyproject.toml, CI)
- **Standard excludes** - Applies go.mod excludes/replaces for problematic versions
- **Clean output** - Quiet mode with per-module logs (`.update-logs/`)
- **Retry/skip workflow** - Fix issues and retry, or skip failed modules
- **Auto-gitignore** - Adds temporary files to each module's .gitignore
- **Legacy project detection** - Warns about `requirements.txt` projects (migrate to uv first)

## Requirements

- **[uv](https://docs.astral.sh/uv/)** - Python package manager (install: `curl -LsSf https://astral.sh/uv/install.sh | sh`)
- Python 3.12+ (automatically managed by uv)
- `ANTHROPIC_API_KEY` environment variable
- Git repository
- For Go modules: CHANGELOG.md in module/package
- For Python projects: `pyproject.toml` + `uv.lock` (legacy `requirements.txt` not supported)

**Note**: This project uses uv for dependency management. No need for pyenv, pip, or virtualenv.

## Documentation

- [Monorepo Mode](docs/monorepo-mode.md) - Smart ordering and discovery
- [Version Bumping](docs/version-bumping.md) - How Claude determines version bumps
- [Logging](docs/logging.md) - Output and log management
- [Development](docs/development.md) - Development setup and testing
- [Roadmap](docs/roadmap.md) - Future plans and phases

## License

This project is licensed under the BSD 2-Clause License - see the [LICENSE](LICENSE) file for details.
