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
    except subprocess.TimeoutExpired, subprocess.SubprocessError:
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


def _get_clean_config_dir() -> Path | None:
    """Get the clean config directory for Claude if it exists.

    Only uses ~/.claude-clean if it was explicitly created by the user.
    Falls back to default Claude config otherwise.

    Returns:
        Path to the clean config directory, or None to use default
    """
    clean_config_dir = Path.home() / ".claude-clean"
    if not clean_config_dir.exists():
        return None

    # Ensure minimal settings.json without hooks
    settings_path = clean_config_dir / "settings.json"
    if not settings_path.exists():
        settings_path.write_text(json.dumps({"permissions": {"allowedCommands": []}}))

    return clean_config_dir


async def verify_claude_auth() -> tuple[bool, str]:
    """Verify Claude authentication is working.

    Retries up to 3 times on timeout errors with exponential backoff.

    Returns:
        Tuple of (success: bool, error_message: str)
    """
    clean_config_dir = _get_clean_config_dir()

    env = os.environ.copy()
    if clean_config_dir is not None:
        env["CLAUDE_CONFIG_DIR"] = str(clean_config_dir)

    options = ClaudeCodeOptions(
        model=config.MODEL,
        env=env,
    )

    # Retry logic for timeout errors
    max_retries = 3
    retry_delays = [2, 5, 10]  # seconds - exponential backoff

    for attempt in range(max_retries):
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

            # Check for auth errors (non-retryable)
            if "Invalid API key" in error_str or "login" in error_str.lower():
                config_info = str(clean_config_dir) if clean_config_dir else "~/.claude"
                return False, (
                    f"Claude authentication failed for config directory: {config_info}\n\n"
                    "Fix: Run 'claude login' to authenticate."
                )

            # Check if it's a timeout or connection error worth retrying
            is_retryable = any(
                keyword in error_str.lower()
                for keyword in ["timeout", "control request", "connection", "initialize"]
            )

            if is_retryable and attempt < max_retries - 1:
                delay = retry_delays[attempt]
                # Note: No logging here since this is called during startup
                await asyncio.sleep(delay)
                continue
            else:
                # Non-retryable error or final attempt
                return False, f"Claude check failed after {attempt + 1} attempts: {error_str}"

    return False, "Claude check failed after all retries"


async def analyze_changes_with_claude(
    module_path: Path, log_func: Callable[..., None] = log_message
) -> dict[str, Any]:
    """Ask Claude to analyze changes and suggest version bump + changelog bullets.

    Creates a new Claude session for each module to ensure clean analysis.
    Retries up to 3 times on timeout errors with exponential backoff.

    Args:
        module_path: Path to the module
        log_func: Logging function to use

    Returns:
        Dict with keys: version_bump, changelog, commit_message

    Raises:
        ClaudeError: If Claude analysis fails after all retries
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

    # Retry logic for timeout errors
    max_retries = 3
    retry_delays = [2, 5, 10]  # seconds - exponential backoff

    last_error = None
    for attempt in range(max_retries):
        try:
            clean_config_dir = _get_clean_config_dir()
            env = os.environ.copy()
            if clean_config_dir is not None:
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

        except Exception as e:
            error_str = str(e).lower()
            # Check if it's a timeout or connection error worth retrying
            is_retryable = any(
                keyword in error_str
                for keyword in ["timeout", "control request", "connection", "initialize"]
            )

            if is_retryable and attempt < max_retries - 1:
                delay = retry_delays[attempt]
                log_func(
                    f"→ Timeout error (attempt {attempt + 1}/{max_retries}), "
                    f"retrying in {delay}s...",
                    to_console=True,
                )
                await asyncio.sleep(delay)
                last_error = e
                continue
            else:
                # Non-retryable error or final attempt - raise
                raise ClaudeError(f"Claude analysis failed: {e}") from e

        finally:
            # Small delay to allow cleanup between sessions
            await asyncio.sleep(config.CLAUDE_SESSION_DELAY)

    # Should never reach here, but just in case
    raise ClaudeError(f"Claude analysis failed after {max_retries} attempts") from last_error


async def analyze_unreleased_for_release(
    entries: list[str], module_name: str, log_func: Callable[..., None] = log_message
) -> dict[str, Any]:
    """Ask Claude to determine version bump from unreleased changelog entries.

    Args:
        entries: List of bullet point strings from ## Unreleased section
        module_name: Name of the module being released
        log_func: Logging function to use

    Returns:
        Dict with keys: version_bump, commit_message

    Raises:
        ClaudeError: If Claude analysis fails after all retries
    """
    log_func("\n=== Analyze Unreleased Entries with Claude ===", to_console=True)

    bullets = "\n".join(entries)

    prompt = f"""Analyze these unreleased CHANGELOG entries and determine the appropriate version bump.

Module: {module_name}

Unreleased entries:
{bullets}

Version Bump Rules (Semantic Versioning):

**MAJOR** - Breaking changes that require user action:
- Removed/renamed public APIs, functions, or CLI flags
- Changed behavior that breaks existing usage
- Incompatible configuration changes

**MINOR** - New functionality (backwards-compatible):
- New features, commands, endpoints, or modes
- New CLI flags or configuration options
- New public APIs or functions
- Significant capability additions
- Keywords: "add", "new", "support", "implement", "introduce"

**PATCH** - Bug fixes and maintenance:
- Bug fixes
- Documentation updates (README, comments)
- Dependency updates (unless they add features)
- CI/CD changes, workflow updates
- Performance improvements (no new features)
- Refactoring (no behavior change)

IMPORTANT: Lean toward MINOR if any entry adds NEW functionality, even if mixed with patches.
Example: "Add REST server mode" + "Update README" = MINOR (new feature present)

Return ONLY this JSON format (no markdown, no code blocks):
{{
  "version_bump": "patch|minor|major"
}}"""

    max_retries = 3
    retry_delays = [2, 5, 10]

    last_error = None
    for attempt in range(max_retries):
        try:
            clean_config_dir = _get_clean_config_dir()
            env = os.environ.copy()
            if clean_config_dir is not None:
                env["CLAUDE_CONFIG_DIR"] = str(clean_config_dir)

            options = ClaudeCodeOptions(
                model=config.MODEL,
                env=env,
            )

            response_text = ""

            async with ClaudeSDKClient(options=options) as client:
                await client.query(prompt)

                async for message in client.receive_response():
                    if isinstance(message, AssistantMessage):
                        for block in message.content:
                            if isinstance(block, TextBlock):
                                response_text += block.text

            # Parse JSON response
            if "```json" in response_text:
                start = response_text.find("```json") + 7
                end = response_text.find("```", start)
                response_text = response_text[start:end].strip()
            elif "```" in response_text:
                start = response_text.find("```") + 3
                end = response_text.find("```", start)
                response_text = response_text[start:end].strip()
            else:
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

            version_bump = analysis.get("version_bump", "patch")
            return {
                "version_bump": version_bump,
            }

        except Exception as e:
            error_str = str(e).lower()
            is_retryable = any(
                keyword in error_str
                for keyword in ["timeout", "control request", "connection", "initialize"]
            )

            if is_retryable and attempt < max_retries - 1:
                delay = retry_delays[attempt]
                log_func(
                    f"→ Timeout error (attempt {attempt + 1}/{max_retries}), "
                    f"retrying in {delay}s...",
                    to_console=True,
                )
                await asyncio.sleep(delay)
                last_error = e
                continue
            else:
                raise ClaudeError(f"Claude analysis failed: {e}") from e

        finally:
            await asyncio.sleep(config.CLAUDE_SESSION_DELAY)

    raise ClaudeError(f"Claude analysis failed after {max_retries} attempts") from last_error
