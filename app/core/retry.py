"""Retry budget and loop termination policies for CodePilot agent."""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class RetryBudget:
    """Enforces deterministic bounds on agent repair attempts."""

    max_attempts: int = 3
    attempts_used: int = 0
    max_identical_errors: int = 2
    last_error_signature: Optional[str] = None
    identical_error_count: int = 0

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        if self.max_identical_errors < 1:
            raise ValueError("max_identical_errors must be at least 1")

    @property
    def remaining(self) -> int:
        """Returns the number of remaining attempts."""
        return max(0, self.max_attempts - self.attempts_used)

    @property
    def exhausted(self) -> bool:
        """Returns True if the budget has been completely exhausted or loop detected."""
        return self.attempts_used >= self.max_attempts or self.identical_error_count >= self.max_identical_errors

    def consume(self) -> None:
        """Consumes one attempt from the budget, raising RuntimeError if already exhausted."""
        if self.exhausted:
            if self.identical_error_count >= self.max_identical_errors:
                raise RuntimeError("Retry budget halted: identical error repeated")
            raise RuntimeError("Retry budget exhausted")
        self.attempts_used += 1

    def record_error(self, error_signature: str) -> None:
        """Tracks consecutive identical errors to prevent repetitive stuck loops."""
        clean_sig = error_signature.strip()
        if self.last_error_signature == clean_sig:
            self.identical_error_count += 1
        else:
            self.last_error_signature = clean_sig
            self.identical_error_count = 1
