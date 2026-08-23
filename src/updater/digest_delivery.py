"""Weekly digest delivery, idempotency, and scheduling.

Delivers the rendered digest over the configured channel (email by default
via `gog gmail send`, Slack webhook when DIGEST_SLACK_WEBHOOK is set), records
one delivery marker per week so re-running the same week sends exactly one
message, and installs the weekly cron entry idempotently.
"""

import json
import os
import shlex
import subprocess
import tempfile
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

import httpx

from . import config
from .log_manager import log_message, run_command


class DeliveryError(Exception):
    """A named delivery failure, carrying the channel that failed.

    The digest renders to stdout with this note and exits non-zero naming the
    channel — re-running retries because no delivery marker was written.
    """

    def __init__(self, channel: str, message: str) -> None:
        self.channel = channel
        super().__init__(f"{channel}: {message}")


class EmailDeliverer:
    """Deliver via `gog gmail send` (the operator's ambient gog auth)."""

    name = "email"

    def __init__(
        self,
        *,
        to: str,
        from_address: str | None = None,
        log_func: Callable[..., None] = log_message,
    ) -> None:
        """Store recipient/from/log_func; validate nothing here (deliver validates).

        Args:
            to: Email recipient for the digest
            from_address: Send-as account override; None lets gog auto-select
            log_func: Logging function to use
        """
        self._to = to
        self._from_address = from_address
        self._log_func = log_func

    def deliver(self, subject: str, body: str) -> None:
        """Send subject/body as email. Raises DeliveryError("email", ...) on failure.

        Args:
            subject: Email subject
            body: Email body

        Raises:
            DeliveryError: If no recipient is configured, or gog gmail send
                fails (a misconfigured channel fails loudly, never a silent
                non-delivery)
        """
        if not self._to:
            raise DeliveryError("email", "no recipient — set config.DIGEST_EMAIL_TO")

        # Deliver the body via a temp file so the multi-line repo metadata is
        # never interpolated into the shell command.
        fd, path = tempfile.mkstemp(suffix=".txt", prefix="digest-")
        try:
            with os.fdopen(fd, "w") as handle:
                handle.write(body)
            # The fdopen handle is closed/flushed above — gog reads the file
            # via --body-file after this write.
            cmd = (
                f"gog gmail send --to {shlex.quote(self._to)} "
                f"--subject {shlex.quote(subject)} --body-file {shlex.quote(path)}"
            )
            try:
                run_command(cmd, log_func=self._log_func)
            except RuntimeError as e:
                raise DeliveryError("email", str(e)) from None
        finally:
            os.unlink(path)


class SlackDeliverer:
    """Deliver via a Slack incoming-webhook POST."""

    name = "slack"

    def __init__(
        self,
        *,
        webhook: str,
        log_func: Callable[..., None] = log_message,
    ) -> None:
        """Store the webhook URL.

        Args:
            webhook: Slack incoming-webhook URL
            log_func: Logging function to use
        """
        self._webhook = webhook
        self._log_func = log_func

    def deliver(self, subject: str, body: str) -> None:
        """POST subject/body to the webhook. Raises DeliveryError("slack", ...) on failure.

        Args:
            subject: Message heading
            body: Message body

        Raises:
            DeliveryError: If the POST fails (network/HTTP error) or returns a
                non-2xx status
        """
        try:
            response = httpx.post(self._webhook, json={"text": f"{subject}\n\n{body}"}, timeout=30)
        except httpx.HTTPError as e:
            raise DeliveryError("slack", str(e)) from None
        if response.status_code >= 300:
            raise DeliveryError("slack", f"HTTP {response.status_code}")


class DigestDelivery:
    """Deliver the digest once per week, recording a marker after a successful send."""

    def __init__(
        self,
        *,
        since: str,
        until: str,
        delivery_log_dir: Path,
        email_to: str = "",
        slack_webhook: str | None = None,
        log_func: Callable[..., None] = log_message,
    ) -> None:
        """Store config; channel = "slack" when slack_webhook is set else "email".

        Args:
            since: Inclusive window start (YYYY-MM-DD) — part of the week key
            until: Inclusive window end (YYYY-MM-DD) — part of the week key
            delivery_log_dir: Directory for per-week delivery markers
            email_to: Email recipient (used when the channel is email)
            slack_webhook: Slack webhook URL; when set the channel is slack
            log_func: Logging function to use
        """
        self._since = since
        self._until = until
        self._delivery_log_dir = delivery_log_dir
        self._email_to = email_to
        self._slack_webhook = slack_webhook
        self._log_func = log_func
        self.channel = "slack" if slack_webhook else "email"

    def _marker_path(self) -> Path:
        """Return the per-week delivery marker path (the week key since..until)."""
        return self._delivery_log_dir / f"{self._since}..{self._until}.json"

    def already_delivered(self) -> bool:
        """Return whether a delivery marker exists for this week (idempotency gate)."""
        return self._marker_path().exists()

    def deliver(self, subject: str, body: str) -> None:
        """Dispatch subject/body over the configured channel.

        Failures propagate as DeliveryError — a failed send leaves no marker
        so a re-run retries.

        Args:
            subject: Message subject/heading
            body: Message body

        Raises:
            DeliveryError: If the configured channel fails to send
        """
        if self.channel == "slack":
            assert self._slack_webhook is not None
            SlackDeliverer(webhook=self._slack_webhook, log_func=self._log_func).deliver(
                subject, body
            )
        else:
            EmailDeliverer(to=self._email_to, log_func=self._log_func).deliver(subject, body)

    def record_delivery(self) -> None:
        """Write the delivery marker, recording the week and channel.

        Called only after a successful deliver — a failed send leaves no
        marker so a re-run retries.
        """
        self._delivery_log_dir.mkdir(parents=True, exist_ok=True)
        marker = {
            "since": self._since,
            "until": self._until,
            "channel": self.channel,
            "delivered_at": datetime.now().isoformat(),
        }
        self._marker_path().write_text(json.dumps(marker))


def weekly_cron_line(cron_schedule: str, command: str, log_path: str) -> str:
    """Build the cron line: "<schedule> <command> >> <log_path> 2>&1".

    Args:
        cron_schedule: Cron schedule field (e.g. "0 9 * * 1")
        command: Command cron runs
        log_path: Path stdout/stderr is appended to

    Returns:
        The full cron line
    """
    return f"{cron_schedule} {command} >> {log_path} 2>&1"


def install_weekly_schedule(
    *,
    cron_schedule: str = config.DIGEST_WEEKLY_CRON,
    command: str,
    log_path: str,
    log_func: Callable[..., None] = log_message,
) -> bool:
    """Install the weekly cron entry idempotently; True when present/installed.

    Runs on the operator's host where cron exists. `crontab -l` exits 1 with
    empty output when no crontab exists — that is NORMAL control flow here,
    so this uses the chain-style direct subprocess carve-out rather than
    run_command (which would raise on that exit).

    Args:
        cron_schedule: Cron schedule field (default config.DIGEST_WEEKLY_CRON)
        command: Command cron runs
        log_path: Path the cron line appends stdout/stderr to
        log_func: Logging function to use

    Returns:
        True if the entry was already present or installed; False on failure
    """
    probe = subprocess.run("crontab -l", shell=True, capture_output=True, text=True)
    existing = (probe.stdout or "").strip()
    line = weekly_cron_line(cron_schedule, command, log_path)

    if line in existing:
        log_func(f"weekly digest schedule already installed: {line}", to_console=True)
        return True

    new_crontab = (existing + "\n" + line).strip() + "\n"
    install = subprocess.run(
        "crontab -", shell=True, input=new_crontab, capture_output=True, text=True
    )
    if install.returncode != 0:
        log_func(
            f"✗ failed to install weekly digest schedule: {install.stderr}",
            to_console=True,
        )
        return False
    log_func(f"installed weekly digest schedule: {line}", to_console=True)
    return True
