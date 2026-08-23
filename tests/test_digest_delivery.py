"""Tests for weekly digest delivery, idempotency, and scheduling.

Unit tests cover the deliverers, the delivery-marker idempotency gate, and the
cron installer with every external boundary patched (no gog, no Slack, no real
cron). Integration tests drive the REAL ``Digest.run()`` + ``DigestDelivery``
end-to-end with the query functions and the send boundary patched, asserting
the one-message-per-week semantics via the deliverer's call count.
"""

import json
import shlex
import subprocess
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import Mock, patch

import httpx
import pytest

from updater.digest import Digest
from updater.digest_delivery import (
    DeliveryError,
    DigestDelivery,
    EmailDeliverer,
    SlackDeliverer,
    install_weekly_schedule,
    weekly_cron_line,
)
from updater.log_manager import log_message

SINCE = "2026-08-14"
UNTIL = "2026-08-21"


def _capture_messages() -> tuple[list[str], object]:
    """Return a message list and a log side-effect that fills it."""
    messages: list[str] = []

    def _log(message: str, *args, **kwargs) -> None:
        messages.append(message)

    return messages, _log


def _completed(returncode: int, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess:
    """Build a CompletedProcess with the given result for use as a subprocess result."""
    return subprocess.CompletedProcess(
        args=["probe"], returncode=returncode, stdout=stdout, stderr=stderr
    )


def _query_patches() -> list[object]:
    """Return the query patches yielding deterministic empty-source data."""
    return [
        patch("updater.digest.query_tags", return_value=["v1.25.2"]),
        patch("updater.digest.query_pull_requests", return_value=[]),
        patch("updater.digest.query_failed_builds", return_value=[]),
        patch("updater.digest.query_parked_advisories", return_value=[]),
        patch("updater.digest.query_human_review_tasks", return_value=[]),
        patch("updater.digest.query_chain_aborts", return_value=[]),
    ]


def _enter_digest_queries(stack: ExitStack) -> None:
    """Enter the digest query patches onto an ExitStack."""
    for query_patch in _query_patches():
        stack.enter_context(query_patch)


def test_email_deliverer_command_boundary():
    """Test deliver builds the exact shlex-quoted gog gmail send invocation."""
    with patch("updater.digest_delivery.run_command") as mock_run:
        EmailDeliverer(to="a@example.com", log_func=log_message).deliver(
            "Weekly Go Update Digest 2026-08-14..2026-08-21", "body"
        )
    assert mock_run.call_count == 1
    cmd = mock_run.call_args.args[0]
    parts = shlex.split(cmd)
    assert parts[:4] == ["gog", "gmail", "send", "--to"]
    assert parts[4] == "a@example.com"
    assert parts[5:7] == ["--subject", "Weekly Go Update Digest 2026-08-14..2026-08-21"]
    assert parts[7] == "--body-file"
    body_file = Path(parts[8])
    assert cmd == (
        "gog gmail send --to a@example.com --subject "
        f"{shlex.quote('Weekly Go Update Digest 2026-08-14..2026-08-21')} "
        f"--body-file {shlex.quote(str(body_file))}"
    )
    assert not body_file.exists()


def test_email_deliverer_no_recipient():
    """Test an empty recipient fails loudly as a named DeliveryError."""
    with pytest.raises(DeliveryError) as exc_info:
        EmailDeliverer(to="", log_func=log_message).deliver("subject", "body")
    assert "email" in str(exc_info.value)
    assert "DIGEST_EMAIL_TO" in str(exc_info.value)


def test_email_deliverer_run_command_failure():
    """Test a gog failure converts to a named DeliveryError naming email."""
    with (
        patch(
            "updater.digest_delivery.run_command",
            side_effect=RuntimeError("gog: auth failed"),
        ),
        pytest.raises(DeliveryError) as exc_info,
    ):
        EmailDeliverer(to="a@example.com", log_func=log_message).deliver("subject", "body")
    assert "email" in str(exc_info.value)


def test_slack_deliverer_posts():
    """Test the Slack deliverer POSTs subject/body JSON to the webhook."""
    response = Mock()
    response.status_code = 200
    with patch("updater.digest_delivery.httpx.post", return_value=response) as mock_post:
        SlackDeliverer(webhook="https://hooks.slack.com/services/x", log_func=log_message).deliver(
            "subject", "body"
        )
    mock_post.assert_called_once_with(
        "https://hooks.slack.com/services/x",
        json={"text": "subject\n\nbody"},
        timeout=30,
    )


def test_slack_deliverer_http_error():
    """Test an httpx failure converts to a named DeliveryError naming slack."""
    with (
        patch("updater.digest_delivery.httpx.post", side_effect=httpx.HTTPError("boom")),
        pytest.raises(DeliveryError) as exc_info,
    ):
        SlackDeliverer(webhook="https://hooks.slack.com/services/x", log_func=log_message).deliver(
            "subject", "body"
        )
    assert "slack" in str(exc_info.value)


def test_slack_deliverer_non_2xx():
    """Test a non-2xx response raises DeliveryError naming the HTTP status."""
    response = Mock()
    response.status_code = 500
    with (
        patch("updater.digest_delivery.httpx.post", return_value=response),
        pytest.raises(DeliveryError) as exc_info,
    ):
        SlackDeliverer(webhook="https://hooks.slack.com/services/x", log_func=log_message).deliver(
            "subject", "body"
        )
    assert str(exc_info.value) == "slack: HTTP 500"


def test_digest_delivery_channel_selection(tmp_path):
    """Test the channel is slack when a webhook is set, email otherwise."""
    slack = DigestDelivery(
        since=SINCE,
        until=UNTIL,
        delivery_log_dir=tmp_path,
        slack_webhook="https://hooks.slack.com/x",
    )
    assert slack.channel == "slack"
    email = DigestDelivery(since=SINCE, until=UNTIL, delivery_log_dir=tmp_path)
    assert email.channel == "email"


def test_delivery_marker_idempotency(tmp_path):
    """Test record_delivery writes the marker once and already_delivered flips."""
    delivery = DigestDelivery(since=SINCE, until=UNTIL, delivery_log_dir=tmp_path)
    assert not delivery.already_delivered()
    delivery.record_delivery()
    marker = tmp_path / f"{SINCE}..{UNTIL}.json"
    assert marker.exists()
    assert delivery.already_delivered()
    data = json.loads(marker.read_text())
    assert data["since"] == SINCE
    assert data["until"] == UNTIL
    assert "channel" in data


def test_delivery_dispatch_dispatches(tmp_path):
    """Test deliver dispatches to Slack when configured, email otherwise."""
    with (
        patch("updater.digest_delivery.SlackDeliverer") as mock_slack,
        patch("updater.digest_delivery.EmailDeliverer") as mock_email,
    ):
        slack_delivery = DigestDelivery(
            since=SINCE,
            until=UNTIL,
            delivery_log_dir=tmp_path,
            slack_webhook="https://hooks.slack.com/x",
        )
        slack_delivery.deliver("s", "b")
        mock_slack.assert_called_once_with(
            webhook="https://hooks.slack.com/x", log_func=log_message
        )
        mock_slack.return_value.deliver.assert_called_once_with("s", "b")
        mock_email.assert_not_called()

        email_delivery = DigestDelivery(since=SINCE, until=UNTIL, delivery_log_dir=tmp_path)
        email_delivery.deliver("s", "b")
        mock_email.assert_called_once_with(to="", log_func=log_message)
        mock_email.return_value.deliver.assert_called_once_with("s", "b")
        mock_slack.return_value.deliver.assert_called_once()


def test_weekly_cron_line():
    """Test the cron line is "<schedule> <command> >> <log_path> 2>&1"."""
    assert weekly_cron_line(
        "0 9 * * 1", "updater digest", "/home/op/.update-logs/digest/digest-cron.log"
    ) == ("0 9 * * 1 updater digest >> /home/op/.update-logs/digest/digest-cron.log 2>&1")


def test_install_weekly_schedule_installs_once():
    """Test a missing crontab installs the entry exactly once."""
    calls: list[tuple[str, dict]] = []

    def _run(cmd: str, **kwargs):
        calls.append((cmd, kwargs))
        if cmd == "crontab -l":
            return _completed(1)
        return _completed(0)

    with patch("updater.digest_delivery.subprocess.run", side_effect=_run):
        ok = install_weekly_schedule(command="updater digest", log_path="/tmp/digest-cron.log")
    assert ok is True
    assert len(calls) == 2
    assert calls[0][0] == "crontab -l"
    assert calls[1][0] == "crontab -"
    assert calls[1][1]["input"].count("updater digest") == 1


def test_install_weekly_schedule_idempotent():
    """Test an already-installed entry is detected and never duplicated."""
    line = weekly_cron_line("0 9 * * 1", "updater digest", "/tmp/digest-cron.log")
    with patch("updater.digest_delivery.subprocess.run") as mock_run:
        mock_run.return_value = _completed(0, stdout=line + "\n")
        ok = install_weekly_schedule(command="updater digest", log_path="/tmp/digest-cron.log")
    assert ok is True
    assert mock_run.call_count == 1
    assert mock_run.call_args.args[0] == "crontab -l"


def test_install_weekly_schedule_failure():
    """Test a failed crontab - install returns False."""

    def _run(cmd: str, **kwargs):
        if cmd == "crontab -l":
            return _completed(1)
        return _completed(1, stderr="cannot install crontab")

    with patch("updater.digest_delivery.subprocess.run", side_effect=_run):
        ok = install_weekly_schedule(command="updater digest", log_path="/tmp/digest-cron.log")
    assert ok is False


def test_run_delivers_once_two_runs(tmp_path):
    """Test running twice for the same week delivers exactly one message."""
    messages, log_side_effect = _capture_messages()
    with ExitStack() as stack:
        _enter_digest_queries(stack)
        stack.enter_context(patch("updater.digest.log_message", side_effect=log_side_effect))
        mock_email = stack.enter_context(patch("updater.digest_delivery.EmailDeliverer"))
        digest = Digest(
            since=SINCE,
            until=UNTIL,
            repos=["bborbe/a"],
            workdir=tmp_path,
            delivery_log_dir=tmp_path / "digest",
            email_to="a@example.com",
        )
        rc1 = digest.run()
        rc2 = digest.run()

    assert rc1 == 0
    assert rc2 == 0
    assert mock_email.return_value.deliver.call_count == 1
    assert any("already delivered" in m for m in messages)


def test_run_dry_run_sends_nothing(tmp_path):
    """Test dry-run prints the full digest text and never calls the deliverer."""
    messages, log_side_effect = _capture_messages()
    with ExitStack() as stack:
        _enter_digest_queries(stack)
        stack.enter_context(patch("updater.digest.log_message", side_effect=log_side_effect))
        mock_email = stack.enter_context(patch("updater.digest_delivery.EmailDeliverer"))
        digest = Digest(
            since=SINCE,
            until=UNTIL,
            repos=["bborbe/a"],
            workdir=tmp_path,
            delivery_log_dir=tmp_path / "digest",
            email_to="a@example.com",
            dry_run=True,
        )
        rc = digest.run()

    assert rc == 0
    mock_email.return_value.deliver.assert_not_called()
    assert any("Summary: 0/1 repos updated this week" in m for m in messages)


def test_run_send_failure_prints_and_nonzero(tmp_path):
    """Test a failed send prints the digest + a named note, exits 1, no marker."""
    messages, log_side_effect = _capture_messages()
    with ExitStack() as stack:
        _enter_digest_queries(stack)
        stack.enter_context(patch("updater.digest.log_message", side_effect=log_side_effect))
        mock_email = stack.enter_context(patch("updater.digest_delivery.EmailDeliverer"))
        mock_email.return_value.deliver.side_effect = DeliveryError("email", "auth failed")
        digest = Digest(
            since=SINCE,
            until=UNTIL,
            repos=["bborbe/a"],
            workdir=tmp_path,
            delivery_log_dir=tmp_path / "digest",
            email_to="a@example.com",
        )
        rc = digest.run()

    assert rc == 1
    assert any("Summary: 0/1 repos updated this week" in m for m in messages)
    assert any("digest delivery failed (email)" in m and "auth failed" in m for m in messages)
    assert not (tmp_path / "digest" / f"{SINCE}..{UNTIL}.json").exists()


def test_run_delivery_marker_boundary(tmp_path):
    """Test a successful run writes the week-keyed marker file."""
    with ExitStack() as stack:
        _enter_digest_queries(stack)
        stack.enter_context(patch("updater.digest.log_message"))
        mock_email = stack.enter_context(patch("updater.digest_delivery.EmailDeliverer"))
        digest = Digest(
            since=SINCE,
            until=UNTIL,
            repos=["bborbe/a"],
            workdir=tmp_path,
            delivery_log_dir=tmp_path / "digest",
            email_to="a@example.com",
        )
        rc = digest.run()

    assert rc == 0
    assert mock_email.return_value.deliver.call_count == 1
    assert (tmp_path / "digest" / f"{SINCE}..{UNTIL}.json").exists()
