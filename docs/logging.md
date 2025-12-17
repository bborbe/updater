# Logging and Output

## Default Behavior

By default, verbose output is saved to `.update-logs/{timestamp}.log` in each module:

```
lib/
  alert/
    .gitignore            # Automatically updated to ignore temporary files
    .update-logs/
      2025-12-17-143022.log  # Full output from this run
      2025-12-18-091505.log
```

- **Default mode**: Clean console output, full details in log files
- **`--verbose` flag**: Show all output in console (no log files created)
- Keeps last 5 logs per module automatically

## Auto-Gitignore

Automatically adds to each module's .gitignore:
- `/.update-logs/` - log directory
- `/.claude/` - Claude Code temporary files
- `/CLAUDE.md` - Claude Code local config
- `/.mcp-*` - MCP server cache/state files

## Verbose Mode

```bash
# Show all output in console
uvx github.com/bborbe/updater update-deps lib/alert --verbose
```

## Log Cleanup

Old logs are automatically cleaned up, keeping only the 5 most recent logs per module.
