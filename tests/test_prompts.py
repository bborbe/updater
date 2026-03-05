"""Tests for prompt functions with YES_MODE support."""

import pytest

from updater import config
from updater.prompts import prompt_skip_or_retry, prompt_yes_no


@pytest.fixture(autouse=True)
def reset_yes_mode():
    """Reset YES_MODE after each test."""
    original = config.YES_MODE
    yield
    config.YES_MODE = original


class TestPromptYesNoYesMode:
    """Tests for prompt_yes_no() when YES_MODE is enabled."""

    def test_returns_default_yes_when_yes_mode_true(self, capsys):
        config.YES_MODE = True
        result = prompt_yes_no("Continue anyway?", default_yes=True)
        assert result is True

    def test_returns_default_no_when_yes_mode_true(self, capsys):
        config.YES_MODE = True
        result = prompt_yes_no("Are you sure?", default_yes=False)
        assert result is False

    def test_logs_auto_accepted_yes(self, capsys):
        config.YES_MODE = True
        prompt_yes_no("Continue anyway?", default_yes=True)
        captured = capsys.readouterr()
        assert "auto-accepted" in captured.out
        assert "yes" in captured.out

    def test_logs_auto_accepted_no(self, capsys):
        config.YES_MODE = True
        prompt_yes_no("Are you sure?", default_yes=False)
        captured = capsys.readouterr()
        assert "auto-accepted" in captured.out
        assert "no" in captured.out

    def test_does_not_call_input_when_yes_mode(self, monkeypatch):
        config.YES_MODE = True
        monkeypatch.setattr(
            "builtins.input", lambda _: (_ for _ in ()).throw(RuntimeError("input() called"))
        )
        # Should not raise
        result = prompt_yes_no("Continue?", default_yes=True)
        assert result is True


class TestPromptSkipOrRetryYesMode:
    """Tests for prompt_skip_or_retry() when YES_MODE is enabled."""

    def test_returns_retry_when_yes_mode_true(self, capsys):
        config.YES_MODE = True
        result = prompt_skip_or_retry()
        assert result == "retry"

    def test_logs_auto_accepted_retry(self, capsys):
        config.YES_MODE = True
        prompt_skip_or_retry()
        captured = capsys.readouterr()
        assert "auto-accepted" in captured.out
        assert "retry" in captured.out

    def test_does_not_call_input_when_yes_mode(self, monkeypatch):
        config.YES_MODE = True
        monkeypatch.setattr(
            "builtins.input", lambda _: (_ for _ in ()).throw(RuntimeError("input() called"))
        )
        result = prompt_skip_or_retry("Skip or Retry?")
        assert result == "retry"


class TestPromptYesNoInteractive:
    """Tests for prompt_yes_no() interactive behavior (YES_MODE=False)."""

    def test_default_yes_on_empty_input(self, monkeypatch):
        config.YES_MODE = False
        monkeypatch.setattr("updater.prompts.play_interaction_sound", lambda: None)
        monkeypatch.setattr("builtins.input", lambda _: "")
        result = prompt_yes_no("Continue?", default_yes=True)
        assert result is True

    def test_yes_mode_false_does_not_auto_accept(self, monkeypatch):
        config.YES_MODE = False
        # input returns 'n' — result should be False
        monkeypatch.setattr("updater.prompts.play_interaction_sound", lambda: None)
        monkeypatch.setattr("builtins.input", lambda _: "n")
        result = prompt_yes_no("Continue?", default_yes=True)
        assert result is False


class TestPromptSkipOrRetryInteractive:
    """Tests for prompt_skip_or_retry() interactive behavior (YES_MODE=False)."""

    def test_yes_mode_false_skip_response(self, monkeypatch):
        config.YES_MODE = False
        monkeypatch.setattr("updater.prompts.play_interaction_sound", lambda: None)
        monkeypatch.setattr("builtins.input", lambda _: "s")
        result = prompt_skip_or_retry()
        assert result == "skip"

    def test_yes_mode_false_retry_response(self, monkeypatch):
        config.YES_MODE = False
        monkeypatch.setattr("updater.prompts.play_interaction_sound", lambda: None)
        monkeypatch.setattr("builtins.input", lambda _: "r")
        result = prompt_skip_or_retry()
        assert result == "retry"
