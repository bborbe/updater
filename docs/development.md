# Development Guide

## Prerequisites

### Install uv

This project uses **uv** for Python version management, dependency installation, and execution.

```bash
# macOS/Linux
curl -LsSf https://astral.sh/uv/install.sh | sh

# Or with Homebrew
brew install uv

# Verify installation
uv --version
```

**Note**: This project does NOT use pyenv. If you have pyenv installed, see [Migrating from pyenv](#migrating-from-pyenv) below.

## Installation

```bash
# Install dependencies (including dev tools: ruff, mypy, pytest)
make install

# Or manually
uv sync --all-extras
```

## Running Tests

```bash
# Run tests
make test

# Run tests with verbose output
make test-verbose

# Or manually
uv run pytest
uv run pytest -v
```

## Code Quality Checks

```bash
# Run all precommit checks (format, test, lint, typecheck)
make precommit

# Format code with ruff
make format

# Lint code with ruff
make lint

# Type check with mypy
make typecheck

# Run lint + typecheck
make check
```

## Local Development

Run from local directory using `uv --directory`:

```bash
# Run with --directory flag (no need to cd)
uv --directory /path/to/updater run update-deps /path/to/module --verbose

# Example: Update skeleton module from local development copy
uv --directory /Users/bborbe/Documents/workspaces/updater run update-deps \
  /Users/bborbe/Documents/workspaces/sm-octopus/skeleton --verbose
```

Or use `uvx --reinstall` for development:

```bash
# Always picks up latest local changes
uvx --reinstall --from /path/to/updater update-deps /path/to/module --verbose
```

## Project Structure

```
updater/
├── updater/               # Main package
│   ├── cli.py            # CLI entry point
│   ├── go_updater.py     # Go dependency updater
│   ├── gomod_excludes.py # Go mod excludes/replaces
│   ├── version_updater.py # Version updates (golang, alpine)
│   ├── claude_analyzer.py # Claude integration
│   ├── git_operations.py # Git operations
│   └── ...
├── tests/                 # Test suite
├── docs/                  # Documentation
├── pyproject.toml         # Project configuration
└── README.md              # Main documentation
```

## Requirements

- Python 3.12+ (managed by uv)
- `ANTHROPIC_API_KEY` environment variable must be set
- Git repository
- For Go modules: CHANGELOG.md in the module/package

## Migrating from pyenv

If you previously used pyenv, here's how to migrate to uv-only:

### 1. Install uv

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### 2. Remove pyenv from shell PATH

**For zsh (~/.zshrc)**:
```bash
# Comment out or remove these lines:
# export PYENV_ROOT="$HOME/.pyenv"
# export PATH="$PYENV_ROOT/bin:$PATH"
# eval "$(pyenv init -)"
# eval "$(pyenv virtualenv-init -)"

# Reload shell
source ~/.zshrc
```

**For bash (~/.bashrc or ~/.bash_profile)**:
```bash
# Comment out or remove these lines:
# export PYENV_ROOT="$HOME/.pyenv"
# export PATH="$PYENV_ROOT/bin:$PATH"
# eval "$(pyenv init -)"
# eval "$(pyenv virtualenv-init -)"

# Reload shell
source ~/.bashrc
```

### 3. Verify uv is working

```bash
# uv should now handle Python versions automatically
uv --version

# Install project dependencies
cd /path/to/updater
uv sync --all-extras

# Run tools through uv
uv run pytest
uv run ruff check .
uv run mypy updater/
```

### 4. Optional: Remove pyenv installation

```bash
# Only if you're completely done with pyenv
rm -rf ~/.pyenv

# Remove from homebrew if installed that way
brew uninstall pyenv pyenv-virtualenv
```

### Why uv over pyenv?

- **Faster**: Built in Rust, ~10-100x faster than pip
- **Simpler**: One tool for versions + dependencies + execution
- **Modern**: Native PEP 621 support (pyproject.toml)
- **Reliable**: Lock files, reproducible builds
- **All-in-one**: `uv run` handles Python version + virtualenv + execution
