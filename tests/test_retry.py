"""Unit tests for RetryBudget and bounded loop policies."""

import pytest
from app.core.retry import RetryBudget


def test_budget_starts_with_all_attempts_available():
    budget = RetryBudget(max_attempts=3)
    assert budget.remaining == 3
    assert budget.attempts_used == 0
    assert budget.exhausted is False


def test_budget_decreases_after_each_attempt():
    budget = RetryBudget(max_attempts=3)
    budget.consume()
    assert budget.remaining == 2
    assert budget.attempts_used == 1
    assert budget.exhausted is False


def test_budget_stops_after_maximum_attempts():
    budget = RetryBudget(max_attempts=3)
    budget.consume()
    budget.consume()
    budget.consume()
    assert budget.exhausted is True
    assert budget.remaining == 0
    with pytest.raises(RuntimeError, match="Retry budget exhausted"):
        budget.consume()


def test_invalid_budget_is_rejected():
    with pytest.raises(ValueError, match="max_attempts must be at least 1"):
        RetryBudget(max_attempts=0)
    with pytest.raises(ValueError, match="max_identical_errors must be at least 1"):
        RetryBudget(max_attempts=3, max_identical_errors=0)


def test_identical_error_loop_detection():
    budget = RetryBudget(max_attempts=5, max_identical_errors=2)
    budget.record_error("TypeError: cannot unpack non-iterable NoneType object")
    assert budget.exhausted is False

    budget.record_error("TypeError: cannot unpack non-iterable NoneType object")
    assert budget.exhausted is True

    with pytest.raises(RuntimeError, match="identical error repeated"):
        budget.consume()


def test_different_errors_do_not_trigger_identical_loop_halt():
    budget = RetryBudget(max_attempts=5, max_identical_errors=2)
    budget.record_error("SyntaxError: invalid syntax")
    budget.record_error("TypeError: unsupported operand")
    budget.record_error("AssertionError: expected 42 got 0")
    assert budget.exhausted is False
