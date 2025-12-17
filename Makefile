.PHONY: help install install-dev test test-verbose clean

help:
	@echo "Available targets:"
	@echo "  install       - Install package with uv"
	@echo "  install-dev   - Install package with test dependencies"
	@echo "  test          - Run tests"
	@echo "  test-verbose  - Run tests with verbose output"
	@echo "  clean         - Remove build artifacts and cache"

install:
	uv sync --all-extras

test:
	uv run pytest

test-verbose:
	uv run pytest -v

run:
	uv run update-deps /Users/bborbe/Documents/workspaces/sm-octopus/lib

run-verbose:
	uv run update-deps /Users/bborbe/Documents/workspaces/sm-octopus/lib --verbose

clean:
	rm -rf .pytest_cache
	rm -rf .venv
	rm -rf updater/__pycache__
	rm -rf tests/__pycache__
	find . -type d -name "*.egg-info" -exec rm -rf {} +
	find . -type d -name "__pycache__" -exec rm -rf {} +
