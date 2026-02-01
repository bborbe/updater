"""Claude integration for analyzing changes."""

import asyncio
import json
import os
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

from claude_code_sdk import (
    AssistantMessage,
    ClaudeCodeOptions,
    ClaudeSDKClient,
    TextBlock,
)

from . import config
from .exceptions import ClaudeError
from .log_manager import log_message

# Limits to prevent buffer overflow in Claude SDK (1MB limit)
MAX_DIFF_PER_FILE = 50_000  # 50KB per file
MAX_TOTAL_DIFF = 200_000  # 200KB total


def _run_git_command(args: list[str], cwd: Path) -> str:
    """Run a git command and return output, empty string on error."""
    try:
        result = subprocess.run(
            ["git"] + args,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=30,
        )
        return result.stdout.strip()
    except (subprocess.TimeoutExpired, subprocess.SubprocessError):
        return ""


def _truncate_diff(diff: str, max_size: int, label: str = "") -> str:
    """Truncate diff to max_size with indicator."""
    if len(diff) <= max_size:
        return diff
    truncated = diff[:max_size]
    # Try to end at a newline for cleaner output
    last_newline = truncated.rfind("\n")
    if last_newline > max_size * 0.8:
        truncated = truncated[:last_newline]
    suffix = f"\n... [truncated {label}, {len(diff) - len(truncated)} bytes omitted]"
    return truncated + suffix


def _get_diff_base(cwd: Path) -> str:
    """Get the comparison base (latest tag or empty for uncommitted)."""
    tag = _run_git_command(["describe", "--tags", "--abbrev=0"], cwd)
    return tag if tag else ""


def _collect_diffs(module_path: Path) -> dict[str, str]:
    """Pre-collect and truncate all diffs for analysis."""
    base = _get_diff_base(module_path)
    base_args = [base] if base else []

    diffs: dict[str, str] = {}
    total_size = 0

    # Dependency files to check
    dep_files = ["go.mod", "go.sum", "package.json", "pyproject.toml", "Dockerfile"]

    for dep_file in dep_files:
        if (module_path / dep_file).exists() or dep_file in ["go.mod", "go.sum"]:
            diff = _run_git_command(
                ["diff", "--no-color"] + base_args + ["--", dep_file], module_path
            )
            if diff:
                diff = _truncate_diff(diff, MAX_DIFF_PER_FILE, dep_file)
                diffs[dep_file] = diff
                total_size += len(diff)

    # General code diff (excluding vendor/node_modules and large generated files)
    remaining_budget = MAX_TOTAL_DIFF - total_size
    if remaining_budget > 10000:  # Only if we have reasonable budget left
        code_diff = _run_git_command(
            ["diff", "--no-color"]
            + base_args
            + [
                "--",
                ".",
                ":(exclude)node_modules/**",
                ":(exclude)vendor/**",
                ":(exclude)**/mocks/**",
                ":(exclude)**/*_mock.go",
                ":(exclude)**/*.gen.go",
            ],
            module_path,
        )
        if code_diff:
            code_diff = _truncate_diff(code_diff, remaining_budget, "code changes")
            diffs["code_changes"] = code_diff

    return diffs


def _get_clean_config_dir() -> Path:
    """Get or create the clean config directory for Claude.

    Returns:
        Path to the clean config directory
    """
    clean_config_dir = Path.home() / ".claude-clean"
    clean_config_dir.mkdir(exist_ok=True)

    # Create minimal settings.json without hooks
    settings_path = clean_config_dir / "settings.json"
    if not settings_path.exists():
        settings_path.write_text(json.dumps({"permissions": {"allowedCommands": []}}))

    return clean_config_dir


async def verify_claude_auth() -> tuple[bool, str]:
    """Verify Claude authentication is working.

    Returns:
        Tuple of (success: bool, error_message: str)
    """
    clean_config_dir = _get_clean_config_dir()

    env = os.environ.copy()
    env["CLAUDE_CONFIG_DIR"] = str(clean_config_dir)

    options = ClaudeCodeOptions(
        model=config.MODEL,
        env=env,
    )

    try:
        async with ClaudeSDKClient(options=options) as client:
            await client.query("Reply with exactly: ok")

            async for message in client.receive_response():
                if isinstance(message, AssistantMessage):
                    for block in message.content:
                        if isinstance(block, TextBlock):
                            # Got a response, auth works
                            return True, ""

        return True, ""
    except Exception as e:
        error_str = str(e)
        if "Invalid API key" in error_str or "login" in error_str.lower():
            return False, (
                "Claude authentication failed for clean config directory.\n\n"
                "Fix with ONE of these options:\n"
                f"  1. Login:   CLAUDE_CONFIG_DIR={clean_config_dir} claude login\n"
                f"  2. Symlink: ln -sf ~/.claude/.credentials.json {clean_config_dir}/.credentials.json"
            )
        return False, f"Claude check failed: {error_str}"


async def analyze_changes_with_claude(
    module_path: Path, log_func: Callable[..., None] = log_message
) -> dict[str, Any]:
    """Ask Claude to analyze changes and suggest version bump + changelog bullets.

    Creates a new Claude session for each module to ensure clean analysis.

    Args:
        module_path: Path to the module
        log_func: Logging function to use

    Returns:
        Dict with keys: version_bump, changelog, commit_message

    Raises:
        ClaudeError: If Claude analysis fails
    """
    log_func("\n=== Phase 3: Analyze Changes with Claude ===", to_console=True)
    log_func("→ Collecting diffs...", to_console=config.VERBOSE_MODE)

    # Pre-collect diffs to avoid Claude SDK buffer overflow
    diffs = _collect_diffs(module_path)
    base = _get_diff_base(module_path)
    base_info = f"Comparing against tag: {base}" if base else "Comparing uncommitted changes"

    # Build diff section for prompt
    diff_sections = []
    for name, diff in diffs.items():
        diff_sections.append(f"=== {name} ===\n{diff}")
    all_diffs = "\n\n".join(diff_sections) if diff_sections else "(no changes detected)"

    log_func("→ Analyzing changes...", to_console=config.VERBOSE_MODE)

    prompt = f"""Analyze these git changes and determine the appropriate version bump.

Module: {module_path.name}
{base_info}

Version Bump Decision Rules:
1. **DEPENDENCY CHANGES = AT LEAST PATCH**
   - If go.mod, go.sum, package.json, pyproject.toml, or Dockerfile have version updates → PATCH minimum

2. **CODE CHANGES:**
   - **MAJOR**: Breaking API changes
   - **MINOR**: New features (backwards-compatible)
   - **PATCH**: Bug fixes or small improvements

3. **NONE**: ONLY when there are ZERO dependency updates AND ZERO code changes
   - Examples: .gitignore, README.md, Makefile, docs/

Here are the diffs (truncated if large, generated files excluded):

{all_diffs}

Task:
1. Determine version bump based on the diffs above
2. Create 2-5 concise changelog bullet points
3. Suggest a brief commit message (max 50 chars)

Return ONLY this JSON format (no markdown, no code blocks):
{{
  "version_bump": "patch|minor|major|none",
  "changelog": ["bullet 1", "bullet 2"],
  "commit_message": "short message"
}}"""

    try:
        clean_config_dir = _get_clean_config_dir()
        env = os.environ.copy()
        env["CLAUDE_CONFIG_DIR"] = str(clean_config_dir)

        options = ClaudeCodeOptions(
            model=config.MODEL,
            env=env,
        )

        response_text = ""

        # Create new client for clean session per module
        async with ClaudeSDKClient(options=options) as client:
            await client.query(prompt)

            async for message in client.receive_response():
                if isinstance(message, AssistantMessage):
                    for block in message.content:
                        if isinstance(block, TextBlock):
                            response_text += block.text

        # Parse JSON response
        # Extract JSON from response (handle markdown code blocks and plain text)
        if "```json" in response_text:
            start = response_text.find("```json") + 7
            end = response_text.find("```", start)
            response_text = response_text[start:end].strip()
        elif "```" in response_text:
            start = response_text.find("```") + 3
            end = response_text.find("```", start)
            response_text = response_text[start:end].strip()
        else:
            # No code blocks - find JSON by braces
            start = response_text.find("{")
            end = response_text.rfind("}") + 1
            if start != -1 and end > start:
                response_text = response_text[start:end].strip()

        try:
            analysis = json.loads(response_text)
        except json.JSONDecodeError as e:
            raise ClaudeError(
                f"Failed to parse Claude response as JSON: {e}\nResponse: {response_text}"
            ) from e

        return {
            "version_bump": analysis.get("version_bump", "patch"),
            "changelog": analysis.get("changelog", ["go mod update"]),
            "commit_message": analysis.get("commit_message", "update dependencies"),
        }
    finally:
        # Small delay to allow cleanup between sessions
        await asyncio.sleep(config.CLAUDE_SESSION_DELAY)
