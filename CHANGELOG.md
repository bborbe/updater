# Changelog

All notable changes to this project will be documented in this file.

Please choose versions by [Semantic Versioning](http://semver.org/).

* MAJOR version when you make incompatible API changes,
* MINOR version when you add functionality in a backwards-compatible manner, and
* PATCH version when you make backwards-compatible bug fixes.

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
