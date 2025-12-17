"""Claude integration for analyzing changes."""

import asyncio
import json
import os
from pathlib import Path
from typing import Callable, Dict

from claude_code_sdk import (
    AssistantMessage,
    ClaudeCodeOptions,
    ClaudeSDKClient,
    TextBlock,
)

from . import config
from .exceptions import ClaudeError
from .log_manager import log_message


async def analyze_changes_with_claude(
    module_path: Path,
    log_func: Callable = log_message
) -> Dict[str, any]:
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
    log_func("→ Analyzing changes...", to_console=config.VERBOSE_MODE)

    prompt = f"""Analyze the git changes in this module and determine the appropriate version bump.

Current directory: {module_path}

Version Bump Decision Rules (check in this order):
1. **DEPENDENCY CHANGES = AT LEAST PATCH**
   - If go.mod, go.sum, package.json, pyproject.toml, or Dockerfile have version updates → PATCH minimum
   - Dependency updates affect the library's behavior and require a version bump

2. **CODE CHANGES:**
   - **MAJOR** ("major"): Breaking API changes that require users to modify their code
   - **MINOR** ("minor"): New features or enhancements (backwards-compatible)
   - **PATCH** ("patch"): Bug fixes or small improvements

3. **NONE** ("none"): ONLY when there are ZERO dependency updates AND ZERO code changes
   - Examples: .gitignore, .github/workflows, README.md, CLAUDE.md, Makefile, docs/, CI configs
   - If there are dependency updates AND infrastructure changes, use PATCH (not NONE)

Task:
1. **Determine comparison base** (what to compare against):
   Run: git describe --tags --abbrev=0
   - If successful, use that tag as base: git diff <tag>
   - If no tag exists, compare uncommitted changes: git diff

2. **FIRST: Check for dependency changes** (this is most important):
   Use the comparison base from step 1:
   - git diff --no-color <base> go.mod
   - git diff --no-color <base> go.sum
   - git diff --no-color <base> package.json (if exists)
   - git diff --no-color <base> pyproject.toml (if exists)
   - git diff --no-color <base> Dockerfile (if exists)

3. Then check code changes (excluding vendor/node_modules):
   git diff --no-color <base> -- . ':(exclude)node_modules/**' ':(exclude)vendor/**'

4. Determine version bump:
   - If ANY dependency file changed → minimum PATCH
   - If no dependencies changed but code changed → MAJOR/MINOR/PATCH based on change type
   - If ONLY infrastructure files changed → NONE

5. Create 2-5 concise changelog bullet points:
   - Focus on dependency updates (which packages/versions)
   - Include runtime version updates (golang, python, node, alpine, etc.)
   - Keep each bullet short and specific
   - Format: "update X to Y" or "update X dependencies"

6. Suggest a brief commit message (max 50 chars)

Return ONLY this JSON format (no markdown, no code blocks, no explanations):

Example 1 - Dependency updates (always at least PATCH):
{{
  "version_bump": "patch",
  "changelog": [
    "update golang to 1.23.4",
    "update github.com/foo/bar to v2.1.0"
  ],
  "commit_message": "update dependencies"
}}

Example 2 - Dependencies + infrastructure (still PATCH, not NONE):
{{
  "version_bump": "patch",
  "changelog": [
    "update lib-core to v0.6.4",
    "update lib-bolt to v0.2.4",
    "add .gitignore file"
  ],
  "commit_message": "update dependencies"
}}

Example 3 - ONLY infrastructure changes (no dependencies, no code):
{{
  "version_bump": "none",
  "changelog": [
    "add .gitignore file"
  ],
  "commit_message": "add .gitignore"
}}"""

    # Change to module directory so Claude runs commands there
    original_dir = os.getcwd()
    os.chdir(module_path)

    try:
        options = ClaudeCodeOptions(
            model=config.MODEL,
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
            raise ClaudeError(f"Failed to parse Claude response as JSON: {e}\nResponse: {response_text}")

        return {
            "version_bump": analysis.get("version_bump", "patch"),
            "changelog": analysis.get("changelog", ["go mod update"]),
            "commit_message": analysis.get("commit_message", "update dependencies")
        }
    finally:
        # Restore original directory
        os.chdir(original_dir)

        # Small delay to allow cleanup between sessions
        await asyncio.sleep(config.CLAUDE_SESSION_DELAY)
