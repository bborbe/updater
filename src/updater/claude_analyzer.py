"""Claude integration for analyzing changes."""

import asyncio
import json
import os
import shutil
import subprocess
import time
from collections.abc import Callable, Generator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from . import config
from .claude_metrics import metrics
from .exceptions import ClaudeError
from .log_manager import log_message


def _extract_json_from_response(response_text: str) -> dict[str, Any]:
    """Extract and parse JSON from a Claude response, handling markdown code blocks.

    Raises:
        ClaudeError: If the response cannot be parsed as JSON.
    """
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
        return json.loads(response_text)
    except json.JSONDecodeError as e:
        raise ClaudeError(
            f"Failed to parse Claude response as JSON: {e}\nResponse: {response_text}"
        ) from e


def _short_path(p: Path) -> str:
    """Replace home directory prefix with ~ for shorter display."""
    try:
        return "~/" + str(p.relative_to(Path.home()))
    except ValueError:
        return str(p)


@contextmanager
def _without_claudecode() -> Generator[None]:
    """Temporarily remove CLAUDECODE from os.environ to allow nested Claude invocation."""
    value = os.environ.pop("CLAUDECODE", None)
    try:
        yield
    finally:
        if value is not None:
            os.environ["CLAUDECODE"] = value


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


def _get_clean_config_dir() -> Path | None:
    """Get the clean config directory for Claude if it exists.

    Only uses ~/.claude-clean if it was explicitly created by the user.
    Falls back to default Claude config otherwise.
    Actively removes plugins and MCP configs that Claude may auto-install.

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

    # Remove plugins dir if auto-installed (contains MCP servers that trigger login)
    plugins_dir = clean_config_dir / "plugins"
    if plugins_dir.exists():
        shutil.rmtree(plugins_dir)

    # Remove any .mcp.json files
    for mcp_file in clean_config_dir.glob(".mcp*.json"):
        mcp_file.unlink()

    return clean_config_dir


async def _run_claude(
    prompt: str,
    model: str | None = None,
    cwd: Path | None = None,
    timeout: int = 120,
) -> str:
    """Run claude --print -p and return stdout text.

    Args:
        prompt: The prompt to send
        model: Model name (sonnet, haiku, opus). Uses config.MODEL if None.
        cwd: Working directory for Claude. None = current directory.
        timeout: Timeout in seconds.

    Returns:
        Claude's text response (stdout).

    Raises:
        ClaudeError: If Claude exits non-zero or times out.
    """
    cmd: list[str] = ["claude", "--print", "-p", prompt, "--output-format", "text"]
    effective_model = model or config.MODEL or "sonnet"
    cmd.extend(["--model", effective_model])
    if config.VERBOSE_MODE:
        cmd.append("--verbose")

    clean_config_dir = _get_clean_config_dir()

    with _without_claudecode():
        env = os.environ.copy()
        if clean_config_dir is not None:
            env["CLAUDE_CONFIG_DIR"] = str(clean_config_dir)

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
            env=env,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except TimeoutError:
            proc.kill()
            await proc.wait()
            raise ClaudeError(f"Claude timed out after {timeout}s") from None

    if proc.returncode != 0:
        raise ClaudeError(f"Claude exited with code {proc.returncode}: {stderr.decode().strip()}")

    return stdout.decode().strip()


async def verify_claude_auth() -> tuple[bool, str]:
    """Verify Claude authentication is working.

    Retries up to 3 times on timeout errors with exponential backoff.

    Returns:
        Tuple of (success: bool, error_message: str)
    """
    return await _verify_claude_auth_impl()


async def _verify_claude_auth_impl() -> tuple[bool, str]:
    """Implementation of Claude authentication verification."""
    clean_config_dir = _get_clean_config_dir()

    # Retry logic for timeout errors
    max_retries = 3
    retry_delays = [2, 5, 10]
    rate_limit_delays = [30, 60, 90]

    for attempt in range(max_retries):
        call_start = time.monotonic()
        try:
            await _run_claude("Reply with exactly: ok", model="sonnet", timeout=30)

            metrics.record_call(
                "auth_check", time.monotonic() - call_start, success=True, rate_limited=False
            )
            return True, ""
        except Exception as e:
            error_str = str(e) or type(e).__name__
            config_info = _short_path(clean_config_dir) if clean_config_dir else "~/.claude"
            fix_hint = f"Fix: Run 'CLAUDE_CONFIG_DIR={config_info} claude' and use /login"

            # Check for auth errors (non-retryable)
            if "Invalid API key" in error_str or "login" in error_str.lower():
                metrics.record_call(
                    "auth_check", time.monotonic() - call_start, success=False, rate_limited=False
                )
                return False, (
                    f"Claude authentication failed (config: {config_info})\n\n{fix_hint}"
                )

            # Check if it's a timeout or connection error worth retrying
            is_retryable = isinstance(e, asyncio.TimeoutError) or any(
                keyword in error_str.lower()
                for keyword in [
                    "timeout",
                    "control request",
                    "connection",
                    "initialize",
                    "rate_limit",
                ]
            )

            is_rate_limit = "rate_limit" in error_str
            metrics.record_call(
                "auth_check",
                time.monotonic() - call_start,
                success=False,
                rate_limited=is_rate_limit,
            )

            if is_retryable and attempt < max_retries - 1:
                delays = rate_limit_delays if is_rate_limit else retry_delays
                delay = delays[attempt]
                if is_rate_limit:
                    metrics.record_rate_limit_wait(delay)
                await asyncio.sleep(delay)
                continue
            else:
                # Build detailed error message
                if isinstance(e, asyncio.TimeoutError):
                    return False, (
                        f"Claude timed out after {attempt + 1} attempts (30s each).\n"
                        f"Config: {config_info}\n\n"
                        f"{fix_hint}"
                    )
                return False, (
                    f"Claude check failed after {attempt + 1} attempts: {error_str}\n"
                    f"Config: {config_info}\n\n"
                    f"{fix_hint}"
                )

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
    log_func("→ Analyzing changes...", to_console=config.VERBOSE_MODE)

    prompt = f"""You are in {module_path}. Analyze the git changes in this module and determine the appropriate version bump.

Steps:
1. Find the latest git tag: git describe --tags --abbrev=0
2. Run git diff against that tag to see what changed (exclude go.sum, vendor/, node_modules/, mocks/, *_mock.go, *.gen.go)
3. Focus on go.mod for dependency changes and source code for logic changes
4. Determine version bump and generate changelog

Version Bump Decision Rules:
1. **DEPENDENCY CHANGES = AT LEAST PATCH**
   - If go.mod, go.sum, package.json, pyproject.toml, or Dockerfile have version updates → PATCH minimum

2. **CODE CHANGES:**
   - **MAJOR**: Breaking API changes
   - **MINOR**: New features (backwards-compatible)
   - **PATCH**: Bug fixes or small improvements

3. **NONE**: ONLY when there are ZERO dependency updates AND ZERO code changes
   - Examples: .gitignore, README.md, Makefile, docs/

Task:
1. Determine version bump based on the changes
2. Create 2-5 concise changelog bullet points
3. Suggest a brief commit message (max 50 chars)

Return ONLY this JSON format (no markdown, no code blocks):
{{"version_bump": "patch|minor|major|none", "changelog": ["bullet 1", "bullet 2"], "commit_message": "short message"}}"""

    # Retry logic for timeout errors
    max_retries = 3
    retry_delays = [2, 5, 10]
    rate_limit_delays = [30, 60, 90]

    last_error = None
    for attempt in range(max_retries):
        call_start = time.monotonic()
        try:
            response_text = await _run_claude(prompt, cwd=module_path, timeout=120)

            # Parse JSON response
            analysis = _extract_json_from_response(response_text)

            metrics.record_call(
                "analyze_changes", time.monotonic() - call_start, success=True, rate_limited=False
            )
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
                for keyword in [
                    "timeout",
                    "control request",
                    "connection",
                    "initialize",
                    "rate_limit",
                    "overloaded",
                ]
            )

            is_rate_limit = "rate_limit" in error_str
            metrics.record_call(
                "analyze_changes",
                time.monotonic() - call_start,
                success=False,
                rate_limited=is_rate_limit,
            )

            if is_retryable and attempt < max_retries - 1:
                delays = rate_limit_delays if is_rate_limit else retry_delays
                delay = delays[attempt]
                label = "Rate limited" if is_rate_limit else "Retryable error"
                log_func(
                    f"→ {label} (attempt {attempt + 1}/{max_retries}), retrying in {delay}s...",
                    to_console=True,
                )
                if is_rate_limit:
                    metrics.record_rate_limit_wait(delay)
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
    rate_limit_delays = [30, 60, 90]

    last_error = None
    for attempt in range(max_retries):
        call_start = time.monotonic()
        try:
            response_text = await _run_claude(prompt, timeout=60)

            # Parse JSON response
            analysis = _extract_json_from_response(response_text)

            version_bump = analysis.get("version_bump", "patch")
            metrics.record_call(
                "analyze_unreleased",
                time.monotonic() - call_start,
                success=True,
                rate_limited=False,
            )
            return {
                "version_bump": version_bump,
            }

        except Exception as e:
            error_str = str(e).lower()
            is_retryable = any(
                keyword in error_str
                for keyword in [
                    "timeout",
                    "control request",
                    "connection",
                    "initialize",
                    "rate_limit",
                    "overloaded",
                ]
            )

            is_rate_limit = "rate_limit" in error_str
            metrics.record_call(
                "analyze_unreleased",
                time.monotonic() - call_start,
                success=False,
                rate_limited=is_rate_limit,
            )

            if is_retryable and attempt < max_retries - 1:
                delays = rate_limit_delays if is_rate_limit else retry_delays
                delay = delays[attempt]
                label = "Rate limited" if is_rate_limit else "Retryable error"
                log_func(
                    f"→ {label} (attempt {attempt + 1}/{max_retries}), retrying in {delay}s...",
                    to_console=True,
                )
                if is_rate_limit:
                    metrics.record_rate_limit_wait(delay)
                await asyncio.sleep(delay)
                last_error = e
                continue
            else:
                raise ClaudeError(f"Claude analysis failed: {e}") from e

        finally:
            await asyncio.sleep(config.CLAUDE_SESSION_DELAY)

    raise ClaudeError(f"Claude analysis failed after {max_retries} attempts") from last_error


async def generate_changelog_from_commits(
    commits: list[dict[str, str]], module_name: str, log_func: Callable[..., None] = log_message
) -> list[str]:
    """Generate changelog entries from git commits using Claude.

    Args:
        commits: List of dicts with 'hash', 'subject', 'body' keys
        module_name: Name of the module
        log_func: Logging function to use

    Returns:
        List of changelog entry strings (without leading "- ")

    Raises:
        ClaudeError: If Claude analysis fails
    """
    log_func("\n=== Generate Changelog from Commits ===", to_console=True)

    # Format commits for the prompt
    commit_text = "\n".join(
        f"- {c['subject']}" + (f"\n  {c['body']}" if c["body"] else "") for c in commits
    )

    prompt = f"""Generate CHANGELOG entries from these git commits.

Module: {module_name}

Commits since last release:
{commit_text}

Rules:
- Create clear, user-facing changelog entries
- Group related commits into single entries when appropriate
- Use past tense (e.g., "Added", "Fixed", "Updated")
- Focus on WHAT changed, not HOW
- Omit merge commits and trivial changes (typos, formatting)
- Each entry should be a complete sentence fragment

Return ONLY this JSON format (no markdown, no code blocks):
{{
  "entries": [
    "Add REST server mode for HTTP clients",
    "Fix race condition in connection pool",
    "Update Go to 1.26.0"
  ]
}}"""

    max_retries = 3
    retry_delays = [2, 5, 10]
    rate_limit_delays = [30, 60, 90]

    last_error = None
    for attempt in range(max_retries):
        call_start = time.monotonic()
        try:
            response_text = await _run_claude(prompt, timeout=60)

            # Parse JSON response
            analysis = _extract_json_from_response(response_text)

            entries = analysis.get("entries", [])
            log_func(f"  Generated {len(entries)} changelog entries", to_console=True)
            metrics.record_call(
                "generate_changelog",
                time.monotonic() - call_start,
                success=True,
                rate_limited=False,
            )
            return entries

        except Exception as e:
            error_str = str(e).lower()
            is_retryable = any(
                keyword in error_str
                for keyword in [
                    "timeout",
                    "control request",
                    "connection",
                    "initialize",
                    "rate_limit",
                    "overloaded",
                ]
            )

            is_rate_limit = "rate_limit" in error_str
            metrics.record_call(
                "generate_changelog",
                time.monotonic() - call_start,
                success=False,
                rate_limited=is_rate_limit,
            )

            if is_retryable and attempt < max_retries - 1:
                delays = rate_limit_delays if is_rate_limit else retry_delays
                delay = delays[attempt]
                label = "Rate limited" if is_rate_limit else "Retryable error"
                log_func(
                    f"→ {label} (attempt {attempt + 1}/{max_retries}), retrying in {delay}s...",
                    to_console=True,
                )
                if is_rate_limit:
                    metrics.record_rate_limit_wait(delay)
                await asyncio.sleep(delay)
                last_error = e
                continue
            else:
                raise ClaudeError(f"Changelog generation failed: {e}") from e

        finally:
            await asyncio.sleep(config.CLAUDE_SESSION_DELAY)

    raise ClaudeError(f"Changelog generation failed after {max_retries} attempts") from last_error
