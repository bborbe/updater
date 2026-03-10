"""Per-module configuration loaded from .updater.yaml."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .log_manager import log_message

VALID_DISABLE_VALUES = {
    "python-version",
    "golang-version",
    "alpine-version",
    "go-dependencies",
    "llm-analysis",
}

_MAX_CONFIG_SIZE = 64 * 1024  # 64 KB


@dataclass
class ModuleConfig:
    """Per-module updater configuration."""

    disable: list[str] = field(default_factory=list)


def load_module_config(module_path: Path) -> ModuleConfig:
    """Load .updater.yaml from module_path.

    Returns default ModuleConfig if file is missing, empty, or malformed.
    Warns for unknown disable values but still processes known ones.

    Args:
        module_path: Path to the module directory.

    Returns:
        ModuleConfig with validated settings.
    """
    config_path = module_path / ".updater.yaml"

    if not config_path.exists():
        return ModuleConfig()

    # Reject files larger than 64 KB
    if config_path.stat().st_size > _MAX_CONFIG_SIZE:
        log_message("  ⚠ .updater.yaml exceeds 64 KB — ignoring config", to_console=True)
        return ModuleConfig()

    content = config_path.read_text()
    if not content.strip():
        return ModuleConfig()

    try:
        data = yaml.safe_load(content)
    except yaml.YAMLError as exc:
        log_message(f"  ⚠ .updater.yaml is malformed ({exc}) — ignoring config", to_console=True)
        return ModuleConfig()

    if not isinstance(data, dict):
        return ModuleConfig()

    raw_disable = data.get("disable")
    if raw_disable is None:
        return ModuleConfig()

    if not isinstance(raw_disable, list):
        log_message(
            "  ⚠ .updater.yaml: 'disable' must be a list — ignoring config",
            to_console=True,
        )
        return ModuleConfig()

    known: list[str] = []
    for value in raw_disable:
        if value in VALID_DISABLE_VALUES:
            known.append(value)
        else:
            log_message(
                f"  ⚠ .updater.yaml: unknown disable value '{value}' — ignoring",
                to_console=True,
            )

    return ModuleConfig(disable=known)


def is_disabled(config: ModuleConfig, phase: str) -> bool:
    """Return True if the given phase is disabled in the config.

    Args:
        config: The module config to check.
        phase: Phase name (e.g. "golang-version", "llm-analysis").

    Returns:
        True if the phase is in config.disable.
    """
    return phase in config.disable
