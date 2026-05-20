# CLAUDE.md

Dependency updater — batch-updates Go modules, Python packages, Docker images, and Go versions across all bborbe repos.

## Dark Factory Workflow

**Never code directly.** All code changes go through the dark-factory pipeline.

### Complete Flow

**Spec-based (multi-prompt features):**

1. Create spec → `/dark-factory:create-spec`
2. Audit spec → `/dark-factory:audit-spec`
3. User confirms → `dark-factory spec approve <name>`
4. dark-factory auto-generates prompts from spec
5. Audit prompts → `/dark-factory:audit-prompt`
6. User confirms → `dark-factory prompt approve <name>`
7. Start daemon → `dark-factory daemon` (use Bash `run_in_background: true`)
8. dark-factory executes prompts automatically

**Standalone prompts (simple changes):**

1. Create prompt → `/dark-factory:create-prompt`
2. Audit prompt → `/dark-factory:audit-prompt`
3. User confirms → `dark-factory prompt approve <name>`
4. Start daemon → `dark-factory daemon` (use Bash `run_in_background: true`)
5. dark-factory executes prompt automatically

### Assess the change size

| Change | Action |
|--------|--------|
| Simple fix, config change, 1-2 files | Write a prompt → `/dark-factory:create-prompt` |
| Multi-prompt feature, unclear edges, shared interfaces | Write a spec first → `/dark-factory:create-spec` |

### Read the relevant guide before starting — every time, not from memory

- Writing a spec → read [[Dark Factory - Write Spec]] and [[Dark Factory Guide#Specs What Makes a Good Spec]]
- Writing prompts → read [[Dark Factory - Write Prompts]] and [[Dark Factory Guide#Prompts What Makes a Good Prompt]]
- Running prompts → read [[Dark Factory - Run Prompt]]

### Claude Code Commands

| Command | Purpose |
|---------|---------|
| `/dark-factory:create-spec` | Create a spec file interactively |
| `/dark-factory:create-prompt` | Create a prompt file from spec or task description |
| `/dark-factory:audit-spec` | Audit spec against preflight checklist |
| `/dark-factory:audit-prompt` | Audit prompt against Definition of Done |

### CLI Commands

| Command | Purpose |
|---------|---------|
| `dark-factory spec approve <name>` | Approve spec (inbox → queue, triggers prompt generation) |
| `dark-factory prompt approve <name>` | Approve prompt (inbox → queue) |
| `dark-factory daemon` | Start daemon (watches queue, executes prompts) |
| `dark-factory run` | One-shot mode (process all queued, then exit) |
| `dark-factory status` | Show combined status of prompts and specs |
| `dark-factory prompt list` | List all prompts with status |
| `dark-factory spec list` | List all specs with status |
| `dark-factory prompt retry` | Re-queue failed prompts for retry |

### Key rules

- Prompts go to **`prompts/`** (inbox) — never to `prompts/in-progress/` or `prompts/completed/`
- Specs go to **`specs/`** (inbox) — never to `specs/in-progress/` or `specs/completed/`
- Never number filenames — dark-factory assigns numbers on approve
- Never manually edit frontmatter status — use CLI commands above
- Always audit before approving (`/dark-factory:audit-prompt`, `/dark-factory:audit-spec`)
- **BLOCKING: Never run `dark-factory prompt approve`, `dark-factory spec approve`, or `dark-factory daemon` without explicit user confirmation.** Write the prompt/spec, then STOP and ask the user to approve
- **Before starting daemon** — run `dark-factory status` first to check if one is already running
- **Start daemon in background** — use Bash tool with `run_in_background: true`

## Development Standards

### Toolchain

- Python project using `uv` and `hatchling`
- Source at `src/updater/`
- `make precommit` — format + test + lint + typecheck
- `make test` — tests only

### Test conventions

- pytest test framework
- Tests in `tests/`

## Architecture

### CLI Entry Points → Pipelines

Each CLI command maps to a pipeline in `cli.py`. Pipelines are composed of reusable steps from `pipeline.py`.

| Command | Function | Pipeline Steps |
|---------|----------|----------------|
| `updater all` | `main_async` | GitSync → GoVersion → Excludes → Deps → Osv → Precommit → Changelog → Commit |
| `updater go` | `main_go_async` | Same as above, Go modules only |
| `updater go-only` | `main_go_only_async` | Same but GoDepSkipStep instead of GoDepUpdateStep |
| `updater go-with-deps` | `main_go_with_deps_async` | Same as updater all, Go modules only, deps included |
| `updater python` | `main_python_async` | GitSync → PyVersion → PyDeps → Precommit → Changelog → Commit |
| `updater docker` | `main_docker_async` | DockerUpdate → DockerCommit |
| `updater release` | `main_release_async` | CommitUncommitted → Release → GitCommit → GitPush |
| `updater fix` | `main_go_fix_async` | GitSync → Excludes → GoCleanIndirect → Osv → Precommit → Changelog → Commit |

### Adding a new pipeline

1. Add `process_single_*` function in `cli.py` — compose steps from `pipeline.py`
2. Add `main_*_async` + `main_*` entry points in `cli.py` (copy arg parser pattern from existing)
3. Add `project_type` branch in `process_module_with_retry` if needed
4. Register entry point in `pyproject.toml` under `[project.scripts]`
5. Add tests in `tests/test_cli.py`

### Key source files

- `cli.py` — all entry points, arg parsing, module processing with retry
- `pipeline.py` — step definitions (GitSyncStep, GoExcludesStep, PrecommitStep, etc.)
- `gomod_excludes.py` — `STANDARD_REPLACES`, `OBSOLETE_EXCLUDES_PREFIXES` lists + `go mod edit` calls
- `go_updater.py` — `go get`/`go mod tidy` loops
- `version_updater.py` — Go version updates across go.mod/Dockerfile/CI
- `changelog.py` — CHANGELOG.md management
- `claude_analyzer.py` — Claude-powered analysis of changes for changelog/commit messages
- `module_discovery.py` — finds Go/Python modules in workspace
- `git_operations.py` — git commit, push, branch ops
- `config.py` — global config (VERBOSE_MODE, MODEL, YES_MODE, etc.)

## Key Design Decisions

- **Pipeline processes modules sequentially** — one module at a time, fail-fast on errors
- **Excludes/replaces are declarative** — `STANDARD_EXCLUDES` defines what to add, `OBSOLETE_EXCLUDES_PREFIXES` defines what to remove
- **`run_command()` for all shell operations** — centralized execution with logging
- **No direct file editing of go.mod** — always use `go mod edit` commands
