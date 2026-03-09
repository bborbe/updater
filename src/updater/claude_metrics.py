"""Claude API call metrics tracking."""

import time
from dataclasses import dataclass, field


@dataclass
class CallRecord:
    function: str
    timestamp: float
    duration_s: float
    success: bool
    rate_limited: bool


@dataclass
class ClaudeMetrics:
    calls: list[CallRecord] = field(default_factory=list)
    rate_limit_wait_s: float = 0.0

    def record_call(
        self, function: str, duration_s: float, success: bool, rate_limited: bool
    ) -> None:
        self.calls.append(
            CallRecord(
                function=function,
                timestamp=time.time(),
                duration_s=duration_s,
                success=success,
                rate_limited=rate_limited,
            )
        )

    def record_rate_limit_wait(self, seconds: float) -> None:
        self.rate_limit_wait_s += seconds

    @property
    def total_calls(self) -> int:
        return len(self.calls)

    @property
    def successful_calls(self) -> int:
        return sum(1 for c in self.calls if c.success)

    @property
    def rate_limited_calls(self) -> int:
        return sum(1 for c in self.calls if c.rate_limited)

    @property
    def failed_calls(self) -> int:
        return sum(1 for c in self.calls if not c.success and not c.rate_limited)

    @property
    def total_duration_s(self) -> float:
        return sum(c.duration_s for c in self.calls)

    def format_summary(self) -> str:
        if not self.calls:
            return ""
        lines = ["Claude API Metrics:"]
        lines.append(
            f"  Calls: {self.total_calls} ({self.successful_calls} ok, {self.rate_limited_calls} rate-limited, {self.failed_calls} failed)"
        )
        lines.append(
            f"  Call time: {self.total_duration_s:.1f}s (avg {self.total_duration_s / self.total_calls:.1f}s)"
        )
        if self.rate_limit_wait_s > 0:
            lines.append(f"  Rate limit wait: {self.rate_limit_wait_s:.0f}s")
        return "\n".join(lines)

    def reset(self) -> None:
        self.calls.clear()
        self.rate_limit_wait_s = 0.0


# Module-level singleton (same pattern as config.py)
metrics = ClaudeMetrics()
