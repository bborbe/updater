# Version Bump Behavior

> **Note:** This tool never bumps the major version. Breaking changes are capped at MINOR.

Claude analyzes **all changes since the last git tag** (or uncommitted changes if no tag exists) and determines the appropriate version bump.

## Priority Order

### 1. Dependency Changes = At Least PATCH

- Any changes to `go.mod`, `go.sum`, `package.json`, `pyproject.toml`, or `Dockerfile` → minimum **PATCH**
- Dependency updates affect the library's behavior and always require a version bump
- Example: `.gitignore` added + dependencies updated → **PATCH** (not NONE)
- Dependency updates are always patch or minor — never major

### 2. Code Changes

- **MINOR**: New features OR breaking API changes (backwards-compatible OR not)
- **PATCH**: Bug fixes or small improvements

### 3. Infrastructure Only = NONE

- **NONE**: ONLY when there are ZERO dependency updates AND ZERO code changes
- Examples: `.gitignore`, `.github/workflows`, `README.md`, `CLAUDE.md`, `Makefile`, `docs/`, CI configs
- Changes are committed without updating CHANGELOG or creating a git tag

## Examples

| Changes | Version Bump | Reasoning |
|---------|--------------|-----------|
| Update go.mod + go.sum | PATCH | Dependency changes always bump version |
| Add new exported function | MINOR | New feature, backwards-compatible |
| Fix bug in existing function | PATCH | Bug fix |
| Remove exported function | MINOR | Breaking change (updater caps at minor) |
| Update README.md only | NONE | Infrastructure only, no code/deps |
| Update .gitignore + go.mod | PATCH | Has dependency changes |

## CHANGELOG Behavior

- **Version bump (MINOR/PATCH)**: Updates CHANGELOG.md with new version and creates git tag
- **No version bump (NONE)**: Commits without CHANGELOG update or git tag

## Merging Existing Unreleased Entries

When `updater all` runs in versioned mode (without `--no-tag`), any pre-existing `## Unreleased`
section in `CHANGELOG.md` is merged into the new version section by Claude and then drained.
This prevents orphaned bullets above the new release header after a previous `--no-tag` run.
