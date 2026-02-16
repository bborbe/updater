.PHONY: help
help:
	@echo "Available targets:"
	@echo "  install       - Install dependencies (alias for sync)"
	@echo "  sync          - Sync dependencies with uv"
	@echo "  test          - Run tests"
	@echo "  test-verbose  - Run tests with verbose output"
	@echo "  precommit     - Run all precommit checks (sync, format, test, check)"
	@echo "  format        - Format code with ruff"
	@echo "  lint          - Lint code with ruff"
	@echo "  typecheck     - Type check with mypy"
	@echo "  check         - Run lint and typecheck"
	@echo "  clean         - Remove build artifacts and cache"

.PHONY: install
install: sync

.PHONY: sync
sync:
	@uv sync --all-extras

.PHONY: test
test: sync
	uv run pytest

.PHONY: test-verbose
test-verbose:
	uv run pytest -v

.PHONY: precommit
# Run all precommit checks
precommit: sync format test check
	@echo "✅ All precommit checks passed"

.PHONY: format
# Format code with ruff
format:
	@echo "Formatting Python files..."
	@uv run ruff format .
	@uv run ruff check --fix . || true
	@echo "✅ Format complete"

.PHONY: lint
# Lint code with ruff
lint:
	@echo "Running ruff..."
	@uv run ruff check .

.PHONY: typecheck
# Type check with mypy
typecheck:
	@echo "Running mypy..."
	@uv run mypy src/updater/ --no-error-summary

.PHONY: check
# Run lint and typecheck
check: lint typecheck
	@echo "✅ All checks passed"

.PHONY: clean
clean:
	rm -rf .pytest_cache .mypy_cache .ruff_cache
	rm -rf .venv dist *.egg-info
	rm -rf src/updater/__pycache__
	rm -rf tests/__pycache__
	find . -type d -name "*.egg-info" -exec rm -rf {} +
	find . -type d -name "__pycache__" -exec rm -rf {} +
