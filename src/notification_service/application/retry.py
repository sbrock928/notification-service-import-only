"""Deterministic, bounded retry configuration."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True, kw_only=True)
class RetryPolicy:
    max_attempts: int = 2
    total_timeout_seconds: float = 120.0
    base_delay_seconds: float = 0.5
    max_delay_seconds: float = 5.0
    max_retry_after_seconds: float = 30.0

    def __post_init__(self) -> None:
        if not 1 <= self.max_attempts <= 3:
            raise ValueError("max_attempts must be between 1 and 3")
        if self.total_timeout_seconds <= 0:
            raise ValueError("total_timeout_seconds must be positive")
        if self.base_delay_seconds < 0 or self.max_delay_seconds < self.base_delay_seconds:
            raise ValueError("retry delay bounds are invalid")
        if self.max_retry_after_seconds < 0:
            raise ValueError("max_retry_after_seconds cannot be negative")

    def delay(self, attempt: int, random_fraction: float, retry_after: float | None) -> float:
        if retry_after is not None:
            return min(retry_after, self.max_retry_after_seconds)
        ceiling = min(
            self.max_delay_seconds,
            self.base_delay_seconds * float(2 ** (attempt - 1)),
        )
        return ceiling * min(1.0, max(0.0, random_fraction))
