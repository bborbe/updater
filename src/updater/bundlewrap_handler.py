"""Infra-tier handler for BundleWrap's default_golang_version constant."""

import re
from pathlib import Path

from .infra_tier import process_infra_target, validate_go_version
from .log_manager import log_message

BUNDLEWRAP_REPO = "bw2/BundleWrap"
BUNDLEWRAP_FILE = "bundles/golang/items.py"
BUNDLEWRAP_PATTERN = re.compile(r"^default_golang_version = '(\d+\.\d+\.\d+)'$", re.MULTILINE)


class BundleWrapHandler:
    """Bump default_golang_version in BundleWrap's bundles/golang/items.py and open a PR."""

    def run(self, checkout: Path, *, dry_run: bool, go_version: str) -> int:
        if not validate_go_version(go_version):
            log_message(f"✗ Invalid Go version: {go_version!r} (expected X.Y.Z)", to_console=True)
            return 1
        return process_infra_target(
            checkout,
            repo=BUNDLEWRAP_REPO,
            target_file=BUNDLEWRAP_FILE,
            pattern=BUNDLEWRAP_PATTERN,
            new_value=go_version,
            branch_name=f"updater/bundlewrap-{go_version}",
            title=f"chore: bump default_golang_version to {go_version}",
            body=f"Bump default_golang_version to {go_version}.",
            changelog_bullet=f"chore: bump default_golang_version to {go_version}",
            dry_run=dry_run,
        )
