"""Tests for Claude API call metrics tracking."""

from src.updater.claude_metrics import ClaudeMetrics


def test_record_call():
    m = ClaudeMetrics()
    m.record_call("analyze_changes", 1.5, success=True, rate_limited=False)
    assert m.total_calls == 1


def test_rate_limit_tracking():
    m = ClaudeMetrics()
    m.record_call("analyze_changes", 2.0, success=False, rate_limited=True)
    m.record_rate_limit_wait(30.0)
    assert m.rate_limited_calls == 1
    assert m.rate_limit_wait_s == 30.0


def test_format_summary_empty():
    m = ClaudeMetrics()
    assert m.format_summary() == ""


def test_format_summary():
    m = ClaudeMetrics()
    m.record_call("analyze_changes", 2.0, success=True, rate_limited=False)
    m.record_call("analyze_changes", 1.0, success=False, rate_limited=True)
    m.record_call("analyze_changes", 0.5, success=False, rate_limited=False)
    m.record_rate_limit_wait(30.0)
    summary = m.format_summary()
    assert "Claude API Metrics:" in summary
    assert "3" in summary  # total calls
    assert "1 ok" in summary
    assert "1 rate-limited" in summary
    assert "1 failed" in summary
    assert "Rate limit wait:" in summary
    assert "30s" in summary


def test_reset():
    m = ClaudeMetrics()
    m.record_call("analyze_changes", 1.0, success=True, rate_limited=False)
    m.record_rate_limit_wait(30.0)
    m.reset()
    assert m.total_calls == 0
    assert m.rate_limit_wait_s == 0.0
