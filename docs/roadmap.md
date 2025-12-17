# Roadmap

## Phases 0-2: Core Go Module Support (Completed ✅)
- ✅ Iterative go dependency updates
- ✅ Standard go.mod excludes and replaces
- ✅ Golang and Alpine version updates (Dockerfile, go.mod, CI)
- ✅ Claude CHANGELOG generation
- ✅ Claude commit messages
- ✅ Git tagging
- ✅ Idempotency (skip if no updates)
- ✅ Multi-module discovery and processing
- ✅ Monorepo support with smart lib/-first ordering
- ✅ Retry/skip workflow for failed modules
- ✅ Per-module logging with cleanup
- ✅ Git pre-flight checks (branch switching, uncommitted changes)
- ✅ Independent Claude sessions per module

## Phase 3: Version Updates (Future)
- Add NPM dependency updates (package.json)
- Add dry-run mode

## Phase 4: Multi-Language Support (Future)
- Add Python dependency updates (pip, poetry, uv)
- Add Node.js dependency updates (npm, yarn, pnpm)
- Language detection and multi-language monorepos

## Phase 5: Advanced Features (Future)
- Parallel module processing for speed
- Interactive mode for review before each commit
- Rollback functionality if errors occur
- Custom CHANGELOG templates
- Jira integration
