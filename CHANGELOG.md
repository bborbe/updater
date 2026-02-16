# Changelog

All notable changes to this project will be documented in this file.

Please choose versions by [Semantic Versioning](http://semver.org/).

* MAJOR version when you make incompatible API changes,
* MINOR version when you add functionality in a backwards-compatible manner, and
* PATCH version when you make backwards-compatible bug fixes.

## Unreleased

- Auto-generate changelog entries from git commits when ## Unreleased is missing
- Check commits since last tag to detect unreleased changes
- Use Claude to create user-friendly changelog entries from commit messages

## v0.12.1

- Improve version bump prompt with clearer semver guidance
- Add examples and keywords to help Claude distinguish minor vs patch changes
- Lean toward MINOR when any new functionality is present

## v0.12.0
- Add universal CI workflow for automated testing

## v0.11.0
- Change git update behavior to stay on current branch and merge origin/master (instead of forcing checkout master)
- Add --no-tag flag to add changes to ## Unreleased instead of creating version/tag (useful for PR workflows)

## v0.10.0
- Add --skip-git-update flag to skip git branch checkout and pull (useful for worktree conflicts)
- Fix Python syntax error in exception handling (old Python 2 syntax)
- Mock network calls in tests to avoid flaky failures from python.org rate limiting

## v0.9.1
- Show base path in summary output for multi-module updates

## v0.9.0
- Add categorized summary output (Updated, Already up to date, Skipped, Failed)
- Change module processing return types to include status information
- Add type annotation for module discovery iterator

## v0.8.0
- Add Docker project support to update-all command with auto-commit
- Optimize module discovery performance (skip vendor/node_modules during walk)
- Add k8s.io v0.34.4 and v0.35.1 to dependency excludes
- Add comprehensive tests for Docker discovery and vendor filtering

## v0.7.1
- Make ~/.claude-clean config optional (only use if pre-created by user)
- Add retry with exponential backoff for Claude SDK timeout errors
- Add pytest-timeout (30s default) to prevent hanging tests

## v0.7.0
- Add update-go-only command for Go version updates without dependency changes
- Add update-go-with-deps command (explicit name for version + dependencies)
- Add update_deps parameter to process_single_go_module() for conditional dependency updates
- Update README documentation with new entry points

## v0.6.1

- Upgrade Python requirement from 3.12 to 3.14
- Update dependencies: anyio, certifi, cryptography, jsonschema, librt, mcp, packaging, pathspec, pycparser, pyjwt, python-multipart, pyyaml, ruff, sse-starlette, starlette, uvicorn
- Fix exception tuple syntax (remove parentheses) for Python 3.14 compatibility

## v0.6.0
- Add Python project support with uv-based dependency updates
- Add entry points: update-all (alias), update-go, update-python, update-docker
- Add Python version updates (.python-version, pyproject.toml, Dockerfile)
- Add Dockerfile base image updater (standalone mode)
- Add legacy Python project detection with migration warning
- Add ensure_changelog_tag for automatic tag creation from CHANGELOG
- Refactor commit summary to helper function
- Add log_func parameter to update_git_branch for consistency

## v0.5.3
- Fix Claude SDK buffer overflow by pre-collecting and truncating diffs
- Exclude generated files (mocks, *_mock.go, *.gen.go) from diff analysis

## v0.5.2
- Add Claude auth verification before processing modules
- Show helpful login hints when authentication fails

## v0.5.1
- Add build-system configuration for uvx GitHub installation support
- Fix hatchling package discovery with explicit src/updater path
- Update README with correct uvx syntax (--from git+https://...)

## v0.5.0
- Add comprehensive test suite (75 new tests covering CLI, Claude analyzer, Go updater, module discovery)
- Restructure project to src/ layout for better packaging
- Improve type hints and exception handling throughout codebase
- Expand development documentation with testing guidelines
- Exclude .claude directory from version control

## v0.4.1
- Fix summary header to show correct path or count for multiple input paths
- Fix module list in summary to display full paths instead of just names
- Hide Python tracebacks in error output unless verbose mode is enabled

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
