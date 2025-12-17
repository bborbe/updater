# Multi-Module Discovery

When run on a directory without go.mod, the tool automatically discovers all modules recursively (including deeply nested ones) and processes them in **dependency order**.

## Update Order

The tool uses smart ordering to ensure dependencies are updated before dependents:

1. `lib/**` - Root-level shared libraries/packages (updated first)
2. Root-level services (depend on lib/, not in subdirectories)
3. `{dir}/lib/**` - Shared libraries/packages in each subdirectory
4. `{dir}/**` - Services in that subdirectory (depend on their lib/)

## Example Structure

```
1. lib/*                  ← Base packages (dependencies)
2. service1, service2     ← Services using base packages
3. module-a/lib/*         ← Module-a packages
4. module-a/service*      ← Services using module-a packages
5. module-b/lib/*         ← Module-b packages
6. module-b/service*      ← Services using module-b packages
```

This ensures library packages are updated before the services that depend on them, reducing circular update loops.

## Usage

```bash
# Process entire monorepo
cd /path/to/your-monorepo
uvx github.com/bborbe/updater update-deps .

# Process specific subdirectory
uvx github.com/bborbe/updater update-deps module-a
```

## Discovery Rules

- Searches recursively for `go.mod` files
- Skips `vendor/` directories
- Orders by path depth and naming convention
- Processes each module with independent Claude sessions
