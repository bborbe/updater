# Development Guide

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

- Python 3.12+
- `ANTHROPIC_API_KEY` environment variable must be set
- Git repository
- For Go modules: CHANGELOG.md in the module/package
