---
status: draft
---

## Summary

- The updater has no per-project configuration — all behavior is controlled by CLI flags
- Some projects need to skip certain update phases (e.g. skip Python version update when 3.14 breaks packages)
- Introduce `.updater.yaml` config file in each project/module root
- Config allows disabling specific update phases
- Missing config = current behavior unchanged

## Problem

The updater always updates all runtimes to latest. Some projects cannot use the latest version:

- `build-python` must stay on Python 3.13 because many packages lack 3.14 wheels
- Some Go modules may need to stay on an older Go version for compatibility

Currently the only workaround is manual revert after `update-all` runs, which defeats the purpose of automation. This happens regularly across multi-module monorepos with 30+ modules.

## Goal

After this work, projects can place a `.updater.yaml` in their root to disable specific update phases. The updater reads this config before each module update and skips disabled phases. Projects without a config file behave exactly as today.

## Non-goals

- Version pinning (cap at specific version instead of skip entirely) — future work
- Per-project model/backend override — future work
- Global config file (~/.updater.yaml)
- Config inheritance (parent dir config applies to subdirs)
- Config file generation/scaffolding command

## Assumptions

- Each module has a single root directory where `.updater.yaml` can live
- YAML is already a project dependency (pyyaml) — no new dependencies needed
- The set of update phases is stable and well-defined
- Users prefer skipping an entire phase over pinning to a specific version as a first iteration

## Desired Behavior

1. A project that cannot use the latest Python can opt out of Python version updates without manual reverts
2. A project that needs a specific Go version can opt out of Go version updates
3. A project can opt out of dependency updates (go get -u / go mod tidy)
4. A project can opt out of LLM-based analysis and use a generic commit message instead
5. Projects without a config file are unaffected — identical behavior to today
6. Invalid or malformed config produces a warning but does not block the update
7. The updater logs which phases are disabled so the user understands what was skipped

## Config File Contract

`.updater.yaml` in the module/project root. All fields optional. Empty or missing file = update everything.

Valid `disable` values:

| Value | Phase skipped |
|-------|---------------|
| `python-version` | Python version updates (Dockerfile, pyproject.toml, .python-version) |
| `golang-version` | Go version updates (go.mod, Dockerfile, GitHub workflows) |
| `alpine-version` | Alpine version updates (Dockerfile) |
| `go-dependencies` | `go get -u` / `go mod tidy` |
| `llm-analysis` | LLM-based change analysis (commit with generic message) |

Example:

```yaml
disable:
  - python-version
```

## Constraints

- No new Python package dependencies
- Existing CLI flags must not change behavior or meaning
- Projects without `.updater.yaml` must produce identical behavior to current
- Config loading must not add noticeable latency
- Unknown disable values produce warnings, not errors
- The `disable` value must be a YAML list — scalar values are rejected with a warning

## Failure Modes

| Trigger | Expected behavior | Recovery |
|---------|-------------------|----------|
| Malformed YAML (syntax error) | Warning + ignore config (use defaults) | User fixes YAML syntax |
| Unknown disable value (e.g. `node-version`) | Warning + ignore unknown value | User corrects value |
| `disable` is scalar instead of list | Warning + ignore config (use defaults) | User wraps in list |
| Config file is empty | Same as no config file (all defaults) | N/A |
| Config file not readable (permissions) | Warning + ignore config (use defaults) | User fixes permissions |
| Config file is unexpectedly large | Read with size limit, warn if exceeded | User fixes file |

## Security / Abuse Cases

- Config file path is deterministic (module root + `.updater.yaml`) — no user-controlled path traversal
- `yaml.safe_load` prevents code execution from YAML content
- File size should be bounded before reading (reject files > 64KB with warning)
- Symlinks are followed (standard Python Path behavior) — acceptable since the user controls the project directory

## Acceptance Criteria

- [ ] `.updater.yaml` with `disable: [python-version]` skips Python version phase
- [ ] `.updater.yaml` with `disable: [golang-version]` skips Go version phase
- [ ] `.updater.yaml` with `disable: [alpine-version]` skips Alpine version phase
- [ ] `.updater.yaml` with `disable: [go-dependencies]` skips dependency updates
- [ ] `.updater.yaml` with `disable: [llm-analysis]` commits with generic message
- [ ] Missing `.updater.yaml` produces identical behavior to current (no config)
- [ ] Malformed `.updater.yaml` logs warning and continues with defaults
- [ ] Unknown disable values log warning and are ignored
- [ ] Disabled phases are logged at start of module processing
- [ ] All existing tests pass without modification
- [ ] New tests for config loading and disable logic

## Verification

```
make precommit
```

## Do-Nothing Option

Keep no per-project config. Manually revert unwanted updates after `update-all`. Works but wastes time and creates noise commits on every run across affected modules.
