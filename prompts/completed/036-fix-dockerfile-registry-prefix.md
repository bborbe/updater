---
status: completed
summary: Fixed Dockerfile golang and alpine version update regexes to handle optional registry prefixes (e.g. ${DOCKER_REGISTRY}/, docker.io/library/) while preserving the prefix in replacements, with new tests covering registry prefix cases.
container: updater-036-fix-dockerfile-registry-prefix
dark-factory-version: v0.108.0-dirty
created: "2026-04-12T07:49:58Z"
queued: "2026-04-12T07:49:58Z"
started: "2026-04-12T07:50:20Z"
completed: "2026-04-12T07:51:43Z"
---
<summary>
- `update_dockerfile_golang` and `update_dockerfile_alpine` regexes only match `FROM golang:` / `FROM alpine:` literally
- Dockerfiles using `FROM ${DOCKER_REGISTRY}/golang:` or any registry prefix are silently skipped
- This causes `updater all` to report "Runtime versions are up to date" while Dockerfile is stale
- go.mod gets updated but Dockerfile does not — version drift between go.mod and Dockerfile
- Fix: add optional registry prefix capture group to both regexes, preserve prefix in replacement
</summary>

<objective>
Fix the Dockerfile version update regexes in `update_dockerfile_golang` and `update_dockerfile_alpine` to handle an optional registry prefix (e.g. `${DOCKER_REGISTRY}/`, `docker.io/library/`, or any `registry.example.com/`). The prefix must be preserved in the replacement.
</objective>

<context>
Read `src/updater/version_updater.py`:
- `update_dockerfile_golang` (line 73): regex at line 95 is `r"FROM golang:(\d+\.\d+\.\d+)([-\w.]*)(\s+AS\s+\w+)?"`
- `update_dockerfile_alpine` (line 112): regex at line 133 is `r"FROM alpine:(\d+\.\d+(?:\.\d+)?)(\s+AS\s+\w+)?"`

Real-world Dockerfile that fails (from jira-task-creator):
```dockerfile
ARG DOCKER_REGISTRY=docker.quant.benjamin-borbe.de:443
FROM ${DOCKER_REGISTRY}/golang:1.26.1 AS build
FROM ${DOCKER_REGISTRY}/alpine:3.23 AS alpine
```

Read `tests/test_version_updater.py` — existing tests only cover the bare `FROM golang:` / `FROM alpine:` forms.
Read `CLAUDE.md` for project conventions and test patterns.
</context>

<requirements>
1. In `update_dockerfile_golang` (line 95 of `src/updater/version_updater.py`), add an optional capture group for the registry prefix before `golang:`. Example transformation:
   - Old: `r"FROM golang:(\d+\.\d+\.\d+)([-\w.]*)(\s+AS\s+\w+)?"`
   - New: `r"FROM (\S+/)?golang:(\d+\.\d+\.\d+)([-\w.]*)(\s+AS\s+\w+)?"`
   The `(\S+/)?` group captures any non-whitespace prefix ending with `/`. The `replace_version` closure must be updated to reference the shifted group indices (group 1 = prefix, group 2 = version, group 3 = suffix, group 4 = AS clause) and preserve the prefix in the output.

2. In `update_dockerfile_alpine` (line 133 of `src/updater/version_updater.py`), apply the same fix. Example transformation:
   - Old: `r"FROM alpine:(\d+\.\d+(?:\.\d+)?)(\s+AS\s+\w+)?"`
   - New: `r"FROM (\S+/)?alpine:(\d+\.\d+(?:\.\d+)?)(\s+AS\s+\w+)?"`
   Same group shift applies: update `replace_version` closure to use group 1 = prefix, group 2 = version, group 3 = AS clause.

3. Add tests in `tests/test_version_updater.py` for `update_dockerfile_golang`:
   - `FROM ${DOCKER_REGISTRY}/golang:1.23.4 AS build` → updated to new version, prefix preserved
   - `FROM docker.io/library/golang:1.23.4` → updated, prefix preserved
   - Existing bare `FROM golang:` tests must still pass

4. Add tests in `tests/test_version_updater.py` for `update_dockerfile_alpine`:
   - `FROM ${DOCKER_REGISTRY}/alpine:3.19 AS alpine` → updated to new version, prefix preserved
   - `FROM docker.io/library/alpine:3.19` → updated, prefix preserved
   - Existing bare `FROM alpine:` tests must still pass

5. Add a test for `update_versions` with a Dockerfile that uses `${DOCKER_REGISTRY}/` prefix for both golang and alpine — assert both get updated.
</requirements>

<constraints>
- Do NOT commit or push changes
- Do NOT modify any function signatures
- Only change the two regex patterns and their corresponding `replace_version` closures
- Existing tests must still pass unchanged
</constraints>

<verification>
Run `make precommit` — must pass.
</verification>
