---
status: completed
spec: [005-digest-weekly]
summary: Added weekly digest delivery and cadence — email (gog) by default / Slack webhook when configured, one-message-per-week idempotency via a delivery-log marker, and an idempotent --schedule cron installer
execution_id: updater-exec-048-spec-005-digest-cadence-delivery
dark-factory-version: dev
created: "2026-08-23T16:35:00Z"
queued: "2026-08-23T14:49:19Z"
started: "2026-08-23T15:00:26Z"
completed: "2026-08-23T15:05:07Z"
---

# Weekly digest cadence and delivery

<summary>
- `updater digest` now delivers the rendered digest through a configured channel — email by default (via the operator's `gog gmail send`), Slack webhook when a webhook URL is configured — instead of only printing it
- Running the same week twice produces exactly one message: a delivery-log marker for the week is written only after a successful send, and a second run detects the marker and skips (the AC "channel inbox count is 1 after two runs" behavior)
- A failed send degrades gracefully: the digest is still printed to stdout with a send-failure note naming the channel, and the command exits non-zero — re-running retries because no marker was written
- A misconfigured channel (no recipient) fails loudly as a named delivery error, never a silent non-delivery
- Email is the default channel with Slack as the configured alternative — the spec's "channel is a prompt decision with a default of email"
- A `--schedule` flag installs the weekly cron entry (default Monday 09:00) idempotently — an existing identical entry is not duplicated; the real weekly delivery observation stays on the operator rung of the spec's verification ladder
- Delivery is read-only reporting: it sends the digest text and never mutates repos or opens/closes PRs
- The whole delivery path is integration-tested in-container with mocked query functions and a mocked send boundary — no real gog, no real Slack, no real cron
</summary>

<objective>
Add delivery, idempotency, and weekly scheduling to `updater digest` so the digest is generated unattended on a weekly cadence and the operator gets exactly one message per week (email default, Slack if configured) — completing spec 005's delivery path on top of the prompt-1 digest module.
</objective>

<context>
Read `/workspace/CLAUDE.md` for project conventions (Python, uv + hatchling, pytest, dark-factory flow, changelog rules). Read `/workspace/docs/dod.md` — the DoD's `run_command()` rule and the documented carve-out for direct `subprocess.run` (already precedented in `chain.py` and the digest's `_run_query`).

Read these files fully before editing:
- `/workspace/src/updater/digest.py` (created by the previous prompt) — the `Digest` class with `render() -> str` and `run() -> int` (currently prints in both modes), `_run_query`, `RATE_LIMIT_RE`, the query functions. This prompt modifies `Digest.__init__` (adds delivery params) and `Digest.run()` (branches on `dry_run` for delivery).
- `/workspace/src/updater/chain.py` — the `_run_probe` direct-`subprocess.run` carve-out precedent, reused here for `crontab` probing (where a non-zero exit is normal control flow).
- `/workspace/src/updater/config.py` — the constants pattern the new delivery constants follow.
- `/workspace/src/updater/log_manager.py` — `log_message(message: str, to_console: bool = True)`; `run_command(cmd, cwd=None, capture_output=False, quiet=False, log_func=log_message) -> subprocess.CompletedProcess` which RAISES `RuntimeError` on non-zero exit (the email deliverer catches it and converts to `DeliveryError`).
- `/workspace/src/updater/version_updater.py` — the repo's httpx pattern: `httpx.get(..., timeout=10)` with `except httpx.HTTPError` (the Slack deliverer follows the same shape with `httpx.post`).
- `/workspace/src/updater/cli.py` — the `digest` subparser and dispatch added by the previous prompt (add `--schedule` and the schedule branch; do NOT add kwargs to the normal-path `Digest(...)` constructor call — its delivery params default from config).
- `/workspace/tests/test_digest.py` (created by the previous prompt) — the mocking conventions (`patch("updater.<module>.<name>")`, tmp_path, no real sleep). `/workspace/tests/test_chain_integration.py` — the integration-harness pattern (drive the REAL `.run()` end-to-end with the external boundaries patched) this prompt's `tests/test_digest_delivery.py` follows. `/workspace/tests/test_cli.py` — the `TestMainUpdaterDigest` class to append to.

Reference docs (in-container paths — the executor container runs from `/home/node`):
- `/home/node/.claude/plugins/marketplaces/coding/docs/python-cli-arguments-guide.md` — CLI flag conventions
- `/home/node/.claude/plugins/marketplaces/coding/docs/python-logging-guide.md` — `log_message`/`run_command` conventions
- `/home/node/.claude/plugins/marketplaces/coding/docs/python-project-structure.md` — `src/` layout
</context>

<requirements>

## 1. Add delivery configuration constants to `src/updater/config.py`

Append after the digest-query constants from the previous prompt:

```python
# Weekly digest delivery configuration
DIGEST_EMAIL_TO: str = ""                 # recipient for the weekly digest email (gog gmail send --to; gog auto-selects the send-as account)
DIGEST_SLACK_WEBHOOK: str | None = None   # when set, digest delivers to Slack instead of email
DIGEST_DELIVERY_LOG_DIR: Path | None = None  # delivery markers; default <workdir>/.update-logs/digest
DIGEST_WEEKLY_CRON: str = "0 9 * * 1"     # Monday 09:00
```

Import `Path` from `pathlib` (prompt 1 adds it to `config.py`; don't rely on it already being there). The channel decision lives here: `DIGEST_SLACK_WEBHOOK` set → Slack, else email (the spec's "Slack if configured; default email").

## 2. Create `src/updater/digest_delivery.py` — delivery, idempotency, and scheduling

Module docstring (Google-style) explaining this delivers the weekly digest over the configured channel (email default via `gog gmail send`, Slack webhook when configured), with one-message-per-week idempotency via a delivery log and an idempotent weekly cron installer.

```python
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
```

### 2.1 `DeliveryError`

```python
class DeliveryError(Exception):
    """A named delivery failure, carrying the channel that failed.

    The digest renders to stdout with this note and exits non-zero naming the
    channel — re-running retries because no delivery marker was written.
    """

    def __init__(self, channel: str, message: str) -> None:
        self.channel = channel
        super().__init__(f"{channel}: {message}")
```

### 2.2 Deliverers

```python
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
        """Store recipient/from/log_func; validate nothing here (deliver validates)."""

    def deliver(self, subject: str, body: str) -> None:
        """Send subject/body as email. Raises DeliveryError("email", ...) on failure."""
```

- `deliver`: if `self._to` is empty → `raise DeliveryError("email", "no recipient — set config.DIGEST_EMAIL_TO")` (a misconfigured channel fails loudly, never a silent non-delivery).
- Write the body to a temp file (no shell interpolation risk for multi-line repo metadata): `fd, path = tempfile.mkstemp(suffix=".txt", prefix="digest-")`; write `body`; `os.fdopen(fd, "w")`; **close/flush the fdopen handle before running the command** (gog reads the file via `--body-file` after the write — an unflushed handle can send an empty body); `os.unlink(path)` in a `finally`.
- Build and run the command via `run_command` (the standard non-probe shell boundary — NOT `_run_query`):
  ```python
  cmd = f"gog gmail send --to {shlex.quote(self._to)} --subject {shlex.quote(subject)} --body-file {shlex.quote(path)}"
  ```
  `shlex.quote` guards the recipient and subject (subject contains only the window dates, but quote anyway — no user-supplied string is ever interpolated unquoted).
- Run the send with a bounded timeout — `run_command` has none, so wrap the command in its own `subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=120)` under the chain-style carve-out, converting `subprocess.TimeoutExpired` to `DeliveryError("email", "gog gmail send timed out")` and non-zero exit to `DeliveryError("email", ...)`. `finally: os.unlink(path)` (clean up the temp file even on failure).

```python
class SlackDeliverer:
    """Deliver via a Slack incoming-webhook POST."""

    name = "slack"

    def __init__(
        self,
        *,
        webhook: str,
        log_func: Callable[..., None] = log_message,
    ) -> None:
        """Store the webhook URL."""

    def deliver(self, subject: str, body: str) -> None:
        """POST subject/body to the webhook. Raises DeliveryError("slack", ...) on failure."""
```

- `deliver`: `try: response = httpx.post(self._webhook, json={"text": f"{subject}\n\n{body}"}, timeout=30)` — `except httpx.HTTPError as e: raise DeliveryError("slack", str(e)) from None` (follow the `version_updater.py` httpx pattern); then `if response.status_code >= 300: raise DeliveryError("slack", f"HTTP {response.status_code}")`.

### 2.3 `DigestDelivery` — orchestration + idempotency

```python
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
        """Store config; channel = "slack" when slack_webhook is set else "email"."""
```

- Store `self._since`, `self._until`, `self._delivery_log_dir`, `self._email_to`, `self._slack_webhook`, `self._log_func`. Set `self.channel = "slack" if slack_webhook else "email"` (exposed so callers log which channel delivered).
- `def _marker_path(self) -> Path` — return `self._delivery_log_dir / f"{self._since}..{self._until}.json"`.
- `def already_delivered(self) -> bool` — return `self._marker_path().exists()`.
- `def deliver(self, subject: str, body: str) -> None` — dispatch on `self.channel`: `SlackDeliverer(webhook=self._slack_webhook, log_func=self._log_func).deliver(subject, body)` when slack; else `EmailDeliverer(to=self._email_to, log_func=self._log_func).deliver(subject, body)` (gog auto-selects the send-as account). Failures propagate as `DeliveryError` (do NOT write a marker).
- `def record_delivery(self) -> None` — `self._delivery_log_dir.mkdir(parents=True, exist_ok=True)`; write the marker JSON `{"since": ..., "until": ..., "channel": ..., "delivered_at": <ISO datetime>}` via `self._marker_path().write_text(json.dumps(...))`. The marker is written ONLY after a successful `deliver` — a failed send leaves no marker so a re-run retries (the "delivery retried after partial failure" failure mode).

### 2.4 Weekly scheduling

```python
def weekly_cron_line(cron_schedule: str, command: str, log_path: str) -> str:
    """Build the cron line: "<schedule> <command> >> <log_path> 2>&1"."""


def install_weekly_schedule(
    *,
    cron_schedule: str = config.DIGEST_WEEKLY_CRON,
    command: str,
    log_path: str,
    log_func: Callable[..., None] = log_message,
) -> bool:
    """Install the weekly cron entry idempotently; True when present/installed."""
```

- `weekly_cron_line`: `return f"{cron_schedule} {command} >> {log_path} 2>&1"`.
- `install_weekly_schedule`: read the existing crontab with `subprocess.run("crontab -l", shell=True, capture_output=True, text=True)` directly (the chain-style carve-out: `crontab -l` exits 1 with empty output when no crontab exists — NORMAL, not an error; do NOT use `run_command` here). Build `line = weekly_cron_line(...)`.
  - If the line is already present in the existing crontab output: log `f"weekly digest schedule already installed: {line}"` via `log_func(..., to_console=True)` and return True (idempotent — no duplicate).
  - Otherwise: `new_crontab = (existing + "\n" + line).strip() + "\n"`; install via `subprocess.run("crontab -", shell=True, input=new_crontab, capture_output=True, text=True)`; if its returncode != 0, log `f"✗ failed to install weekly digest schedule: {stderr}"` via `log_func(..., to_console=True)` and return False; else log `f"installed weekly digest schedule: {line}"` via `log_func(..., to_console=True)` and return True.
  - This runs on the operator's host where cron exists; the container only unit-tests it with the subprocess boundary mocked.

## 3. Wire delivery into `src/updater/digest.py`

Modify the `Digest` class (created by the previous prompt):

- `__init__` gains four delivery params, each defaulting from config so the CLI's existing `Digest(...)` call (which passes only `since`, `until`, `dry_run`, `workdir`) continues to work unchanged:
  ```python
  def __init__(
      self,
      *,
      since: str,
      until: str,
      repos: list[str] | None = None,
      dry_run: bool = False,
      workdir: Path | None = None,
      park_list_dir: Path | None = None,
      human_review_dirs: list[Path] | None = None,
      email_to: str | None = None,
      slack_webhook: str | None = None,
      delivery_log_dir: Path | None = None,
  ) -> None:
  ```
  - Store `self._email_to = config.DIGEST_EMAIL_TO if email_to is None else email_to`; same for `_slack_webhook`. Store `self._delivery_log_dir = (config.DIGEST_DELIVERY_LOG_DIR or self._workdir / config.LOG_DIR_NAME / "digest") if delivery_log_dir is None else delivery_log_dir`.
- Add the import at the top of `digest.py`: `from .digest_delivery import DeliveryError, DigestDelivery`.
- Rewrite `run()` so the non-dry-run path delivers, keeping the date validation and empty-fleet guards from the previous prompt:
  1. `if not validate_date(self._since) or not validate_date(self._until):` log the invalid-range message and return 1 (unchanged).
  2. `if not self._repos:` log the empty-fleet message and return 1 (unchanged).
  3. `text = self.render()`.
  4. If `self._dry_run`: `log_message(text, to_console=True)` and return 0 (no delivery — the AC "dry-run shows the full digest text and sends nothing").
  5. Build `delivery = DigestDelivery(since=self._since, until=self._until, delivery_log_dir=self._delivery_log_dir, email_to=self._email_to, slack_webhook=self._slack_webhook)`.
  6. If `delivery.already_delivered()`: `log_message(f"digest already delivered for week {self._since}..{self._until} — skipping (idempotent)", to_console=True)` and return 0 (the AC "running twice for the same week produces exactly one message").
  7. `subject = f"Weekly Go Update Digest {self._since}..{self._until}"`; `try: delivery.deliver(subject, text); delivery.record_delivery()` then log `f"digest delivered via {delivery.channel}"` via `log_message(..., to_console=True)` and return 0. `except DeliveryError as e:` print the digest to stdout with a send-failure note naming the channel: `log_message(text, to_console=True)` then `log_message(f"✗ digest delivery failed ({e.channel}): {e} — digest printed above; fix the channel config and re-run", to_console=True)` and return 1 (the send-failure failure mode; no marker was written so a re-run retries).

## 4. Add `--schedule` to the CLI in `src/updater/cli.py`

In `main_updater_async`, in the `digest` subparser (added by the previous prompt), after `--dry-run`:
```python
sub.add_argument(
    "--schedule",
    action="store_true",
    help="Install the weekly cron entry (default Monday 09:00) idempotently and exit",
)
```
In the dispatch chain, in the `elif args.subcommand == "digest":` branch, BEFORE the normal render path:
```python
if args.schedule:
    log_dir = config.DIGEST_DELIVERY_LOG_DIR or Path.cwd() / config.LOG_DIR_NAME / "digest"
    ok = install_weekly_schedule(
        cron_schedule=config.DIGEST_WEEKLY_CRON,
        command="updater digest",
        log_path=str(log_dir / "digest-cron.log"),
    )
    return 0 if ok else 1
```
Add the import at the top with the digest import: `from .digest_delivery import install_weekly_schedule`. Do NOT add any kwargs to the normal-path `Digest(...)` constructor call (its delivery params default from config — this keeps the previous prompt's CLI dispatch tests passing).

## 5. CHANGELOG

Add to the `## Unreleased` section (below the previous prompt's digest bullet):
`- feat: Add weekly digest delivery and cadence — email via gog by default (Slack webhook if configured), one-message-per-week idempotency via a delivery log, --schedule installs the weekly cron entry`

## 6. Tests

Use pytest with the conventions from `tests/test_digest.py` / `tests/test_chain_integration.py` (pytest, `unittest.mock.patch` on the name imported into the module under test, `tmp_path`, no real network, no real sleep, no real gog/Slack/cron — every external boundary is patched). The digest is synchronous — plain `def test_...`.

### `tests/test_digest_delivery.py` (new file)

Unit tests:

1. `test_email_deliverer_command_boundary` — patch `updater.digest_delivery.run_command` with a spy; `EmailDeliverer(to="a@example.com", log_func=log_message).deliver("Weekly Go Update Digest 2026-08-14..2026-08-21", "body")`; assert the command passed to `run_command` is `gog gmail send --to a@example.com --subject Weekly\ Go\ Update\ Digest\ 2026-08-14..2026-08-21 --body-file <tmp>` with the subject and temp path `shlex.quote`-escaped, and that no temp file remains on disk after the call.
2. `test_email_deliverer_no_recipient` — `to=""` → `pytest.raises(DeliveryError)` whose message contains `email` and `DIGEST_EMAIL_TO`.
3. `test_email_deliverer_run_command_failure` — `run_command` raises `RuntimeError("gog: auth failed")` → `pytest.raises(DeliveryError)` whose message contains `email`.
4. `test_slack_deliverer_posts` — `patch("updater.digest_delivery.httpx.post")` returning a fake 200 response → `SlackDeliverer(webhook="https://hooks.slack.com/services/x").deliver("subject", "body")` does not raise; assert `httpx.post` called with the webhook URL and `json={"text": "subject\n\nbody"}`.
5. `test_slack_deliverer_http_error` — `httpx.post` raises `httpx.HTTPError` → `DeliveryError` whose message contains `slack`.
6. `test_slack_deliverer_non_2xx` — fake 500 response → `DeliveryError("slack", "HTTP 500")`.
7. `test_digest_delivery_channel_selection` — with `slack_webhook` set, `DigestDelivery(...).channel == "slack"`; without, `"email"`.
8. `test_delivery_marker_idempotency` — `DigestDelivery(since="2026-08-14", until="2026-08-21", delivery_log_dir=tmp_path, ...)`: `already_delivered()` False; `record_delivery()` writes `<tmp>/2026-08-14..2026-08-21.json`; `already_delivered()` True; the marker JSON contains `since`, `until`, `channel`.
9. `test_delivery_dispatch_dispatches` — patch `updater.digest_delivery.SlackDeliverer` (with `.return_value.deliver` a Mock) and `EmailDeliverer`; a slack-configured `DigestDelivery.deliver("s", "b")` calls the SlackDeliverer (and NOT EmailDeliverer); an email-configured one calls EmailDeliverer.
10. `test_weekly_cron_line` — `weekly_cron_line("0 9 * * 1", "updater digest", "/home/op/.update-logs/digest/digest-cron.log")` == `"0 9 * * 1 updater digest >> /home/op/.update-logs/digest/digest-cron.log 2>&1"`.
11. `test_install_weekly_schedule_installs_once` — patch `updater.digest_delivery.subprocess.run`: first call (`crontab -l`) returns empty stdout (no crontab), second call (`crontab -`) returns returncode 0 → returns True; assert the second call's `input` contains exactly one occurrence of the cron line.
12. `test_install_weekly_schedule_idempotent` — `crontab -l` returns a crontab already containing the line → returns True and `crontab -` is NOT called (no duplicate).
13. `test_install_weekly_schedule_failure` — `crontab -` returns returncode 1 → returns False.

Integration tests — drive the REAL `Digest.run()` + REAL `DigestDelivery` end-to-end with the query functions and the send boundary patched (no network, no real gog/Slack; the one-message-per-week semantics are asserted via the deliverer's call count):

14. `test_run_delivers_once_two_runs` — `Digest(since="2026-08-14", until="2026-08-21", repos=["bborbe/a"], workdir=tmp_path, delivery_log_dir=tmp_path / "digest", email_to="a@example.com")` with all query functions patched to deterministic data and `updater.digest_delivery.EmailDeliverer` patched with a `Mock` returning a successful deliver (its `.return_value.deliver` a Mock). Call `run()` twice for the same week: the first returns 0 and delivers (EmailDeliverer.deliver called once); the second returns 0 and does NOT deliver again (call count still 1) — the AC "running twice for the same week produces exactly one message". Assert the second run's captured `log_message` output contains `already delivered`.
15. `test_run_dry_run_sends_nothing` — same setup with `dry_run=True`: `run()` returns 0, the deliverer is NEVER called, and the captured output contains the full digest text.
16. `test_run_send_failure_prints_and_nonzero` — `EmailDeliverer.deliver` raises `DeliveryError("email", "auth failed")` → `run()` returns 1, the captured output contains the digest text AND a send-failure note naming `email`, and NO marker file exists (a re-run retries).
17. `test_run_delivery_marker_boundary` — after a successful `run()`, the marker file `<delivery_log_dir>/2026-08-14..2026-08-21.json` exists (the idempotency boundary — the week key `since..until` flows into the marker filename).

### `tests/test_cli.py` (append to `TestMainUpdaterDigest`)

18. `test_digest_subcommand_schedule` — `patch("sys.argv", ["updater", "digest", "--schedule"])`; `patch("updater.cli.install_weekly_schedule", return_value=True)` as `mock_install`; `patch("updater.cli.Digest")`; assert exit 0 and `mock_install` called once with `command="updater digest"` and `cron_schedule="0 9 * * 1"`; assert `Digest` NOT constructed (schedule mode does not render).

Coverage: new module must have ≥80% statement coverage — verify with `uv run --with pytest-cov pytest --cov=updater.digest_delivery --cov-report=term-missing tests/test_digest_delivery.py tests/test_cli.py tests/test_digest.py`.
</requirements>

<constraints>
- Lives in `src/updater/` as modules; CLI wiring in `cli.py`; reuses `config.py`, `log_manager.py` (`run_command`/`log_message`) — NO changes to `chain.py`, `git_operations.py`, `infra_tier.py`, or the four handler modules.
- Delivery is READ-ONLY reporting: the digest never mutates repos, opens/closes PRs, or changes state — it only queries, renders, and sends (spec constraint).
- Idempotent: re-running the same week produces exactly ONE message — the delivery marker is written only after a successful send, and a second run detects it and skips (spec failure mode).
- Send failure degrades gracefully: the digest renders to stdout with a send-failure note naming the channel; exit non-zero; no marker written so a re-run retries (spec failure mode). A misconfigured channel (no recipient) fails loudly as a named `DeliveryError`, never a silent non-delivery.
- Channel: email by default (via `gog gmail send`, the operator's ambient auth); Slack webhook when `DIGEST_SLACK_WEBHOOK` is configured. No credentials handled by the digest itself; no secrets written to logs; Slack webhook URLs are config values, never logged.
- No shell injection: the email recipient and subject are `shlex.quote`-escaped; the body is delivered via a temp file (never interpolated into a shell command); repo metadata never reaches a shell outside the existing `_run_query`/`run_command` boundaries.
- `--dry-run` prints the full digest and sends nothing (spec AC); `--schedule` installs the weekly cron entry idempotently and exits without rendering.
- The weekly cadence default is Monday 09:00 (`DIGEST_WEEKLY_CRON = "0 9 * * 1"`); the observed real weekly delivery stays on the operator rung of the spec's verification ladder (recorded deferral — never a silently installed, untested schedule).
- Follow project Python conventions (pytest, type hints, uv, Google-style docstrings); no `print` — use `log_message()`; no new dependencies beyond pyproject.toml's declared `httpx` and `pyyaml`.
- `make precommit` stays green; existing tests unchanged (including the previous prompt's `test_digest.py` and `test_cli.py` digest dispatch tests — the normal-path `Digest(...)` call in `cli.py` is NOT changed).
- `## Unreleased` CHANGELOG bullet (autoRelease repo).
- Do NOT commit — dark-factory handles git.
</constraints>

<verification>
Run `make precommit` — must exit 0 (sync + format + test + lint + typecheck).

Confirm the delivery module and wiring exist:
```
grep -nE 'class (DigestDelivery|EmailDeliverer|SlackDeliverer|DeliveryError)|def (weekly_cron_line|install_weekly_schedule)' src/updater/digest_delivery.py
grep -n 'DigestDelivery\|install_weekly_schedule\|--schedule' src/updater/digest.py src/updater/cli.py
```

Confirm no production file outside the allowed set changed:
```
git diff --stat -- src/updater/chain.py src/updater/git_operations.py src/updater/infra_tier.py src/updater/claude_yolo_handler.py src/updater/dark_factory_handler.py src/updater/bundlewrap_handler.py src/updater/trading_handler.py
```
(Expected: empty.)

Run the new unit + integration tests:
```
uv run pytest tests/test_digest_delivery.py tests/test_digest.py tests/test_cli.py -q
```

Coverage check for the new module (≥80%):
```
uv run --with pytest-cov pytest --cov=updater.digest_delivery --cov-report=term-missing tests/test_digest_delivery.py tests/test_cli.py tests/test_digest.py
```

Manual dry-run still sends nothing (the AC #5 negative evidence — no network, no send):
```
uv run updater digest --dry-run --since 2026-08-14 --until 2026-08-21
```
The output must be the full digest text (sections with the query functions failing against the container's no-network environment is NOT expected — if live queries fail, the `## Query errors` section names them and the command still exits 0; no delivery attempt occurs because `--dry-run` is set).
</verification>
