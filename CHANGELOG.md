# Changelog

All notable changes to this project will be documented in this file.

Please choose versions by [Semantic Versioning](http://semver.org/).

* MAJOR version when you make incompatible API changes,
* MINOR version when you add functionality in a backwards-compatible manner, and
* PATCH version when you make backwards-compatible bug fixes.

## v0.4.0
- Add support for multiple module paths as CLI arguments
- Add automatic deduplication of discovered modules
- Improve module display to show full paths instead of names
- Update documentation with multiple module usage examples

## v0.3.0
- Add sound notifications for user interaction, completion, and errors
- Add `--require-commit-confirm` CLI flag for manual commit approval
- Add clean Claude config directory to bypass global hooks
- Add MCP semantic-search server integration
- Improve error messages with full module paths instead of names
- Update summary header to show full module path

## v0.2.2
- Add k8s.io v0.35.0 to standard go.mod excludes
- Update .gitignore to exclude .mcp.json and .claude/

## v0.2.1

**Workflow Changes:**
- Add authorization checks to GitHub Actions workflows (restrict Claude triggers to trusted users)
- Enable author filtering in code review workflow (bborbe and collaborators only)
- Add structured authorization validation with separate check-auth job

## v0.2.0

**New Features:**
- Add golang version updates (Dockerfile, go.mod, GitHub workflows)
- Add alpine version updates (Dockerfile)
- Add standard go.mod excludes and replaces for problematic versions
- Add recursive module discovery (finds deeply nested modules)

**Bug Fixes:**
- Fix git status to filter by module path only (no unrelated directories shown)
- Fix git status to exclude vendor/ files
- Fix go.mod version updates to write full version (1.25.5) for idempotency
- Fix confusing output when CHANGELOG.md doesn't exist (now shows clear "no tag" message)

**Documentation:**
- Reorganize README.md for clarity
- Add docs/ directory with detailed guides (monorepo-mode, version-bumping, logging, development, roadmap)

**Workflow Changes:**
- Phase 1a: Update versions (golang, alpine)
- Phase 1b: Apply standard excludes/replaces
- Phase 1c: Update dependencies (renamed from Phase 1)
- Phase 1d: Check git status (renamed from Phase 1)

## v0.1.1
- Add BSD 2-Clause LICENSE file
- Remove development-specific Makefile targets (run, run-verbose)

## v0.1.0

Initial release of multi-language dependency updater with AI-powered automation.

**Core Features:**
- Automated Go module dependency updates with iterative resolution
- Claude-powered CHANGELOG generation from git diff analysis
- Claude-powered commit message suggestions
- Automatic semantic versioning (MAJOR/MINOR/PATCH bump detection)
- Git tag creation from CHANGELOG versions
- Multi-module discovery and batch processing
- Retry/skip workflow for handling failures gracefully

**Workflow:**
- Phase 1: Update dependencies (go mod update, tidy, vendor)
- Phase 2: Run precommit validation (tests, linters, formatting)
- Phase 3: AI analysis of changes with Claude
- Phase 4: CHANGELOG update with version bump
- Phase 5: Git commit and tag creation

**Quality Features:**
- Per-module logging with automatic cleanup (keeps last 5 logs)
- Clean console output with condensed vendor file display
- Git pre-flight checks (branch updates, uncommitted changes detection)
- Idempotency (skips modules already up-to-date)
- Independent Claude sessions per module for clean analysis
- Automatic .gitignore updates for temporary files

**User Experience:**
- Interactive prompts for commit confirmation
- Infinite retry attempts on failure with skip option
- Progress tracking for multi-module batches
- Verbose mode option for debugging
- Model selection (sonnet/haiku)
- Summary reports showing successful/skipped modules
