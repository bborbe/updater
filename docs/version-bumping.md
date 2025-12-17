# Version Bump Behavior

Claude analyzes **all changes since the last git tag** (or uncommitted changes if no tag exists) and determines the appropriate version bump.

## Priority Order

### 1. Dependency Changes = At Least PATCH

- Any changes to `go.mod`, `go.sum`, `package.json`, `pyproject.toml`, or `Dockerfile` → minimum **PATCH**
- Dependency updates affect the library's behavior and always require a version bump
- Example: `.gitignore` added + dependencies updated → **PATCH** (not NONE)

### 2. Code Changes

- **MAJOR**: Breaking API changes
- **MINOR**: New features (backwards-compatible)
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
| Remove exported function | MAJOR | Breaking change |
| Update README.md only | NONE | Infrastructure only, no code/deps |
| Update .gitignore + go.mod | PATCH | Has dependency changes |

## CHANGELOG Behavior

- **Version bump (MAJOR/MINOR/PATCH)**: Updates CHANGELOG.md with new version and creates git tag
- **No version bump (NONE)**: Commits without CHANGELOG update or git tag
