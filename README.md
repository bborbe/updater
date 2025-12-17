# Dependency Updater

Multi-language dependency updater with Claude-powered CHANGELOG generation and commit messages.

**Supported Languages:**
- Go (Phase 0 - implemented)
- Python (Phase 1 - planned)
- Node.js (Phase 1 - planned)
- Other languages (future phases)

## Core Workflow

1. Update dependencies (language-specific)
2. Update CHANGELOG.md using Claude (analyzes changes intelligently)
3. Run validation (tests, precommit, linters)
4. Generate commit message using Claude (concise, descriptive)
5. Git commit
6. Git tag from CHANGELOG

## Installation

```bash
# Install with uv
make install

# Install with test dependencies
make install-dev

# Or manually
uv sync
uv sync --all-extras  # with test dependencies
```

## Development

```bash
# Run tests
make test

# Run tests with verbose output
make test-verbose

# Or manually
uv run pytest
uv run pytest -v
```

## Usage

```bash
# Single module (quiet output with logs)
cd /path/to/your-monorepo
uvx github.com/bborbe/updater update-deps lib/alert

# Multiple modules (discover all modules in lib/)
uvx github.com/bborbe/updater update-deps lib

# Monorepo mode (discovers nested modules recursively with smart ordering)
cd /path/to/your-monorepo
uvx github.com/bborbe/updater update-deps .

# Verbose mode (show full command output)
uvx github.com/bborbe/updater update-deps lib/alert --verbose

# Use specific Claude model (default: sonnet)
uvx github.com/bborbe/updater update-deps lib/alert --model sonnet
uvx github.com/bborbe/updater update-deps lib/alert --model haiku

# Future: Update Python package
# uvx github.com/bborbe/updater update-deps python-service/

# Future: Update Node.js package
# uvx github.com/bborbe/updater update-deps node-service/
```

### Monorepo Mode

When run on a monorepo root (directory without go.mod but with nested modules), the tool automatically discovers all modules recursively and processes them in **dependency order**:

**Update Order:**
1. `lib/**` - Root-level shared libraries/packages (updated first)
2. Root-level services (depend on lib/, not in subdirectories)
3. `{dir}/lib/**` - Shared libraries/packages in each subdirectory
4. `{dir}/**` - Services in that subdirectory (depend on their lib/)

**Example structure:**
```
1. lib/*                  ← Base packages (dependencies)
2. service1, service2     ← Services using base packages
3. module-a/lib/*         ← Module-a packages
4. module-a/service*      ← Services using module-a packages
5. module-b/lib/*         ← Module-b packages
6. module-b/service*      ← Services using module-b packages
```

This ensures library packages are updated before the services that depend on them, reducing circular update loops.

### Retry/Skip on Failure

If a module update fails (precommit errors, test failures, etc.), you'll be prompted:

```
✗ Module lib/alert failed
  → Fix the issues and retry, or skip this module

Skip or Retry? [s/R]:
```

- **Retry (R)**: Fix the issue in another terminal, press R to retry from Phase 1
- **Skip (s)**: Skip this module and continue to the next
- No limit on retries - keeps prompting until success or skip

### Logging

By default, verbose output is saved to `.update-logs/{timestamp}.log` in each module:

```
lib/
  alert/
    .gitignore            # Automatically updated to ignore temporary files
    .update-logs/
      2025-12-17-143022.log  # Full output from this run
      2025-12-18-091505.log
```

- **Default mode**: Clean console output, full details in log files
- **`--verbose` flag**: Show all output in console (no log files created)
- Keeps last 5 logs per module automatically
- **Auto-gitignore**: Automatically adds to each module's .gitignore:
  - `/.update-logs/` - log directory
  - `/.claude/` - Claude Code temporary files
  - `/CLAUDE.md` - Claude Code local config
  - `/.mcp-*` - MCP server cache/state files

## Requirements

- Python 3.12+
- `ANTHROPIC_API_KEY` environment variable must be set
- CHANGELOG.md in the module/package
- Git repository

## Features

- **Multi-language support**: Go (now), Python/Node (planned)
- **Intelligent updates**: Language-specific dependency updaters
- **Claude-powered CHANGELOG**: Analyzes changes and generates meaningful entries
- **Claude-powered commit messages**: Creates concise, descriptive messages
- **Automated git tagging**: Creates tags from CHANGELOG versions
- **Smart version bumping**: MAJOR/MINOR/PATCH for code changes, or "none" for infrastructure-only changes
- **Validation**: Runs tests and precommit checks before committing
- **Retry/Skip on failure**: Fix issues and retry, or skip failed modules
- **Clean output**: Quiet mode with per-module logs, optional verbose mode
- **Multi-module discovery**: Process all modules in a directory automatically
- **Monorepo support**: Recursive discovery with smart lib/-first ordering for dependency management
- **Idempotency**: Skips modules that are already up-to-date
- **Auto-gitignore**: Automatically adds temporary files to each module's .gitignore (`/.update-logs/`, `/.claude/`, `/CLAUDE.md`, `/.mcp-*`)

### Version Bump Behavior

Claude analyzes **all changes since the last git tag** (or uncommitted changes if no tag exists) and determines the appropriate version bump (in priority order):

**1. Dependency Changes = At Least PATCH**
- Any changes to `go.mod`, `go.sum`, `package.json`, `pyproject.toml`, or `Dockerfile` → minimum **PATCH**
- Dependency updates affect the library's behavior and always require a version bump
- Example: `.gitignore` added + dependencies updated → **PATCH** (not NONE)

**2. Code Changes:**
- **MAJOR**: Breaking API changes
- **MINOR**: New features (backwards-compatible)
- **PATCH**: Bug fixes or small improvements

**3. Infrastructure Only = NONE**
- **NONE**: ONLY when there are ZERO dependency updates AND ZERO code changes
- Examples: `.gitignore`, `.github/workflows`, `README.md`, `CLAUDE.md`, `Makefile`, `docs/`, CI configs
- Changes are committed without updating CHANGELOG or creating a git tag

## Roadmap

### Phase 0: Go Modules (Completed)
- ✅ Iterative go dependency updates
- ✅ Claude CHANGELOG generation
- ✅ Claude commit messages
- ✅ Git tagging
- ✅ Idempotency (skip if no updates)
- ✅ Multi-module discovery and processing
- ✅ Per-module logging with cleanup
- ✅ Git pre-flight checks (branch switching, uncommitted changes)
- ✅ Independent Claude sessions per module

### Phase 1: Python/Node Support + Enhancements
- Add Python dependency updates (pip, poetry, uv)
- Add Node.js dependency updates (npm, yarn, pnpm)
- Add version updates (golang, alpine, npm in Dockerfiles)
- Add dry-run mode
- Parallel module processing for speed

### Phase 2: Advanced Features
- Interactive mode for review before each commit
- Rollback functionality if errors occur
- Custom CHANGELOG templates
- Support for monorepos with mixed languages
