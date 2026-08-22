# Changelog

All notable changes to this project will be documented in this file.

## v0.24.0

- feat: Add infra-tier claude-yolo handler (updater claude-yolo) and the shared patch-and-PR helper reused by the other infra-tier handlers
- feat: Add infra-tier dark-factory handler (updater dark-factory) — bumps DefaultContainerImage from claude-yolo's latest release tag
- feat: Add infra-tier BundleWrap handler (updater bundlewrap) — bumps default_golang_version
- feat: Add infra-tier trading handler (updater trading) — replicates update-go-version.sh's walk (go.mod `go`/`toolchain`, Dockerfile `FROM golang:`, workflow `go-version:`) in a feature worktree

## v0.23.4

- fix: stop injecting `exclude cloud.google.com/go v0.26.0` into every go.mod (empty `STANDARD_EXCLUDES`) — it broke `go install <module>@latest` fleet-wide; existing excludes are left untouched (not added to `OBSOLETE_EXCLUDES_PREFIXES`, so nothing is actively stripped).

## v0.23.3

- fix: Add `cloud.google.com/go@v0.26.0` to `STANDARD_EXCLUDES` and drop it from `OBSOLETE_EXCLUDES_PREFIXES` — the pre-split monorepo version still bundles the `cloud.google.com/go/compute/metadata` package, which now ships as its own module. When both land in the build graph (e.g. via `golang.org/x/oauth2/google`), `go mod tidy` fails with `ambiguous import`. The exclude forces MVS to drop the stale version so only the split-out module provides the package. `go mod tidy` preserves the exclude, so the fix is durable.

## v0.23.2

- feat: Empty `STANDARD_REPLACES` — the four tools.go-pollution workarounds (cellbuf, go-header, go-diskfs, ginkgolinter/types) are no longer auto-added since they break `go install` / `go run pkg@version`
- feat: Add `TOOLS_GO_OBSOLETE_REPLACES` — when a project no longer has `tools.go` (migrated to `tools.env` + Makefile `@version` pattern), updater actively removes these four obsolete replaces
- Un-migrated projects (with `tools.go`) keep their replaces unchanged so migration can proceed at a per-repo pace

## v0.23.1

- fix: Drop `anthropic-sdk-go` v1.26.0 replace pin from STANDARD_REPLACES and mark it obsolete so existing projects get the stale replace stripped automatically

## v0.23.0

- feat: Cap version bumps at MINOR — updater never bumps MAJOR; breaking API changes are classified as MINOR
- feat: Merge existing `## Unreleased` CHANGELOG bullets into new version section on release, then drain the Unreleased header to prevent orphaned entries
- fix: `analyze_unreleased_for_release` no longer returns "major" — defensive guard coerces to "minor"
- refactor: Add `drain_unreleased_section` helper to `changelog.py` for removing unreleased header after merge
- refactor: `ChangelogStep` reads pre-existing unreleased entries and passes them to Claude via new `existing_unreleased` parameter on `analyze_changes_with_claude`
- docs: Update `docs/version-bumping.md` — remove MAJOR row, cap breaking changes at MINOR

## v0.22.0

- feat: Add `--no-git` mode to skip all git operations in environments without `.git` access (e.g. dark-factory hideGit containers)
- feat: Auto-detect missing git and enable `--no-git` mode automatically
- Add `is_git_available()` helper to `git_operations.py`
- Guard all git-dependent pipeline steps (`GitSyncStep`, `CheckChangesStep`, `ChangelogStep`, `GitCommitStep`, `GitPushStep`, `CommitUncommittedStep`, `ReleaseStep`, `DockerCommitStep`) with `config.NO_GIT` checks

## v0.21.0

- feat: Add `CommitUncommittedStep` to `updater release` pipeline so manually edited files are committed before the release check, preventing silent "Nothing to release" when uncommitted changes exist

## v0.20.7

- fix: Handle optional registry prefix (e.g. `${DOCKER_REGISTRY}/`, `docker.io/library/`) in Dockerfile golang and alpine version update regexes, preserving prefix in replacement

## v0.20.6

- pin auth check to sonnet model
- default `_run_claude` model to sonnet when unset

## v0.20.5

- add anthropic-sdk-go and diskfs replaces to STANDARD_REPLACES
- remove obsolete runtime-spec replace
- sort STANDARD_REPLACES alphabetically

## v0.20.4

- fix: Run `GoExcludesStep` before `GoCleanIndirectStep` in fix pipeline so replaces are applied before `go mod tidy`

## v0.20.3

- add ginkgolinter/types replace to STANDARD_REPLACES
- fix cellbuf replace missing from idempotent tests
- audit and improve scanner-ignores prompt

## v0.20.2

- fix: Run `GoCleanIndirectStep` before `GoExcludesStep` in `updater fix` pipeline to avoid stale go.sum failures
- fix: Call `go mod download` after `apply_gomod_excludes_and_replaces` modifies go.mod to keep go.sum in sync

Please choose versions by [Semantic Versioning](http://semver.org/).

* MAJOR version when you make incompatible API changes,
* MINOR version when you add functionality in a backwards-compatible manner, and
* PATCH version when you make backwards-compatible bug fixes.

## v0.20.1

- rename package from `dependency-updater` to `updater`

## v0.20.0

- feat: Add `GoCleanIndirectStep` to `updater fix` pipeline to remove stale indirect deps from go.mod and re-add via `go mod tidy`

## v0.19.1

- test: Add regression tests for `main_updater_async` covering subcommand dispatch, global flag propagation, and error cases

## v0.19.0

- feat: Replace 8 separate CLI entry points with a single `updater <subcommand>` binary; global flags (`--verbose`, `--model`, `--yes`, `--check-command`, `--require-commit-confirm`) defined once on root parser

## v0.18.0

- feat: Add `fix-only` CLI entry point that applies go.mod standard excludes/replaces and OSV fixes without updating Go version or dependencies

## v0.17.24

- add standard replaces for go-header v0.5.0 and runtime-spec v1.2.0 (fix golangci-lint v2 compilation)

## v0.17.23

- refactor: Remove `go mod vendor` calls from `update_go_dependencies` and `fix_osv_vulnerabilities`; vendor generation is handled by `make precommit` when needed

## v0.17.22

- remove all remaining STANDARD_EXCLUDES (cloud.google.com/go, go-logr, go.yaml.in, golang.org/x/tools) — excludes break `go install`
- add all former excludes to OBSOLETE_EXCLUDES_PREFIXES for active cleanup
- fix tests for empty STANDARD_EXCLUDES

## v0.17.21

- refactor: Remove k8s-related excludes and kube-openapi replace from `STANDARD_EXCLUDES`/`STANDARD_REPLACES`; add `OBSOLETE_EXCLUDES_PREFIXES` and `OBSOLETE_REPLACES` so updater actively cleans up these stale workarounds from projects it updates

## v0.17.20

- Add per-project `.updater.yaml` config file support so projects can disable specific update phases (`python-version`, `golang-version`, `alpine-version`, `go-dependencies`, `llm-analysis`) via a `disable` list; invalid config produces warnings and falls back to defaults without blocking updates

## v0.17.19

- Fix intermittent stuck prompt after Claude CLI timeout by setting `stdin=DEVNULL` on subprocess

## v0.17.18

- Add tests for `process_single_python_module()`, `process_release_module()`, `process_release_with_retry()`, docker project type in `process_module_with_retry()`, auth failure, `--skip-git-update`, git status error, multi-module summary, and explicit entry points (`main_go_async`, `main_go_only_async`, `main_go_with_deps_async`, `main_python_async`, `main_docker_async`, `main_release_async`) in `cli.py`, raising coverage from 39% to 94%

## v0.17.17

- Add tests for `_get_clean_config_dir()`, `_verify_claude_auth_impl()`, `analyze_unreleased_for_release()`, and `generate_changelog_from_commits()` in `claude_analyzer.py`, raising coverage from 65% to 85%

## v0.17.16

- Add tests for `update_git_branch()`, `git_commit()`, and `git_tag_from_changelog()` in `git_operations.py`, raising coverage from 61% to at least 80%

## v0.17.15

- Add tests for `add_to_unreleased()` and `update_changelog_with_suggestions()` in `changelog.py`, raising coverage from 49% to 100%

## v0.17.14

- Add tests for `GoDepSkipStep`, `PythonVersionUpdateStep`, `PythonDepUpdateStep`, `DockerUpdateStep`, `GitPushStep`, and `GitCommitStep` (tag_only path), raising `pipeline.py` coverage from 78% to 85%

## v0.17.13

- Add mocked tests for `get_latest_python_version()` (valid response, HTTP error, timeout, malformed JSON) and `update_python_versions()` failure path, raising `python_version_updater.py` coverage from 76% to 100%

## v0.17.12

- Fix syntax error in `version_updater.py` (missing parentheses in `except` clauses) and add mocked tests for `get_latest_golang_version()`, `get_latest_alpine_version()`, and `update_versions()`, raising coverage from 73% to 97%

## v0.17.11

- Add test coverage for `log_manager.py` (`run_command`, `cleanup_old_logs`, `setup_module_logging`, `close_module_logging`, `log_message`) raising coverage from 68% to 100%

## v0.17.10

- Replace `print()` calls in `ReleaseStep.run()` with `log_message(..., to_console=True)` so the release summary is captured in the per-module log file

## v0.17.9

- Always write error tracebacks to module log file (not just in verbose mode)

## v0.17.8

- Kill subprocess on timeout in `_run_claude()` to prevent orphaned processes

## v0.17.7

- Consolidate triplicated JSON extraction logic into `_extract_json_from_response` helper

## v0.17.6

- Replace claude-code-sdk with direct CLI subprocess calls (fixes rate_limit_event crashes)

## v0.17.5

- Refactor Claude analysis to use built-in tools instead of embedding diffs in prompt

## v0.17.4

- Handle unknown SDK message types (e.g. rate_limit_event) without crashing

## v0.17.3

- Add Claude API call metrics (call count, rate limits, durations) printed in run summary

## v0.17.2

- fix: retry rate_limit_event errors with longer backoff (30/60/90s)

## v0.17.1

- fix: improve auth check error messages (show config dir, actionable fix hint, handle empty TimeoutError)

## v0.17.0

- feat: Sync with origin/master before updating (git fetch -p + merge) for all go/python update commands

## v0.16.0

- feat: Add `--check-command` flag to override validation command (e.g. `make ensure test` for faster bulk updates)

## v0.15.1

- use hatch-vcs for dynamic versioning from git tags

## v0.15.0

- feat: Add --version flag to all 7 CLI entry points using importlib.metadata for runtime version lookup

## v0.14.5

- fix: Add 30-second hard timeout to Claude auth verification via asyncio.wait_for to prevent indefinite hangs
- fix: Move setup_module_logging before verify_claude_auth in main_async so a log file always exists if auth hangs or fails

## v0.14.4

- migrate dark-factory config to nested format, rename prompts/queue to prompts/in-progress

## v0.14.3

- 003-max-retries-yes-mode

## v0.14.2

- Fix nested Claude invocation by removing CLAUDECODE from os.environ directly (not just from copy) using _without_claudecode() context manager
- Add tests for _without_claudecode context manager

## v0.14.1

- Disable project-level MCP server loading in Claude SDK calls

## v0.14.0

- Add `--yes` / `-y` flag for non-interactive mode (auto-accepts all prompts)

## v0.13.1

- Fix nested session error when running update-all inside Claude Code by unsetting CLAUDECODE env var before ClaudeSDKClient calls

## v0.13.0

- Add OSV vulnerability auto-fix: run `make osv-scanner` before precommit, parse vulnerable Go packages, and update them with `go get -u`

## v0.12.7

- Remove auto-installed plugins and MCP configs from ~/.claude-clean on each use

## v0.12.6

- Add k8s v0.34.5 and v0.35.2 to go.mod excludes

## v0.12.5

- Skip git pull on branches without a remote tracking branch

## v0.12.4

- Release update

## v0.12.3

- Fix release-only workflow to ensure .gitignore entries for .update-logs/
- Fix GitHub workflow updater to skip workflows using go-version-file
- Add test coverage for go-version-file preservation

## v0.12.2

- Auto-generate changelog entries from git commits when ## Unreleased is missing
- Check commits since last tag to detect unreleased changes
- Use Claude to create user-friendly changelog entries from commit messages
- Detect and create missing tags when CHANGELOG version exists but tag doesn't

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
