"""
Tests for Task 1.2: Orchestration configuration loading, approved fixed shares,
deadlines, retry policies, and validation of invalid splits and unsafe timeouts.
"""

from pathlib import Path
import pytest
from pydantic import ValidationError

from tracker.config import (
    load_orchestration_config,
    load_tracker_config,
    OrchestrationConfig,
    BudgetsConfig,
    DeadlinesConfig,
    RetriesConfig,
    ClaimsConfig,
)
from shared.contracts import ResourceBudget


def test_load_default_orchestration_config():
    """Verify that default config.yaml loads approved fixed shares, deadlines, and retries."""
    orch = load_orchestration_config()
    assert isinstance(orch, OrchestrationConfig)

    # Approved fixed shares
    assert orch.budgets.total.max_steps == 30
    assert orch.budgets.total.max_fetches == 40
    assert orch.budgets.total.max_tokens == 100000

    assert orch.budgets.researcher.max_steps == 18
    assert orch.budgets.researcher.max_fetches == 20
    assert orch.budgets.researcher.max_tokens == 60000

    assert orch.budgets.verifier.max_steps == 12
    assert orch.budgets.verifier.max_fetches == 20
    assert orch.budgets.verifier.max_tokens == 40000

    # Deadlines
    assert orch.deadlines.worker_timeout_seconds == 120
    assert orch.deadlines.attempt_timeout_seconds == 210
    assert orch.deadlines.run_timeout_seconds == 900
    assert orch.deadlines.attempt_timeout_seconds > orch.deadlines.worker_timeout_seconds

    # Retries
    assert orch.retries.max_attempts == 3
    assert orch.retries.backoff_initial_seconds == 2.0
    assert orch.retries.backoff_factor == 2.0

    # Claims
    assert orch.claims.max_per_development == 4


def test_tracker_config_includes_orchestration():
    """Verify that main load_tracker_config() also exposes validated orchestration config."""
    cfg = load_tracker_config()
    assert hasattr(cfg, "orchestration")
    assert cfg.orchestration.budgets.total.max_steps == 30
    assert cfg.orchestration.claims.max_per_development == 4


def test_invalid_step_split_fails_validation():
    """Verify that worker step sum exceeding total fails validation."""
    with pytest.raises((ValueError, ValidationError), match="Worker step allocations exceed total"):
        BudgetsConfig(
            total=ResourceBudget(max_steps=30, max_fetches=40, max_tokens=100000),
            researcher=ResourceBudget(max_steps=18, max_fetches=20, max_tokens=60000),
            verifier=ResourceBudget(max_steps=13, max_fetches=20, max_tokens=40000),  # 18 + 13 = 31 > 30!
        )


def test_invalid_fetch_split_fails_validation():
    """Verify that worker fetch sum exceeding total fails validation."""
    with pytest.raises((ValueError, ValidationError), match="Worker fetch allocations exceed total"):
        BudgetsConfig(
            total=ResourceBudget(max_steps=30, max_fetches=40, max_tokens=100000),
            researcher=ResourceBudget(max_steps=18, max_fetches=21, max_tokens=60000),  # 21 + 20 = 41 > 40!
            verifier=ResourceBudget(max_steps=12, max_fetches=20, max_tokens=40000),
        )


def test_invalid_token_split_fails_validation():
    """Verify that worker token sum exceeding total fails validation."""
    with pytest.raises((ValueError, ValidationError), match="Worker token allocations exceed total"):
        BudgetsConfig(
            total=ResourceBudget(max_steps=30, max_fetches=40, max_tokens=100000),
            researcher=ResourceBudget(max_steps=18, max_fetches=20, max_tokens=60001),  # 60001 + 40000 = 100001!
            verifier=ResourceBudget(max_steps=12, max_fetches=20, max_tokens=40000),
        )


def test_unsafe_timeout_attempt_not_exceeding_worker_deadline():
    """
    Attempt timeout must strictly exceed worker execution deadline
    to accommodate network latency and Render wake-up margin.
    """
    # attempt_timeout == worker_timeout (unsafe)
    with pytest.raises((ValueError, ValidationError), match="attempt_timeout_seconds must exceed worker_timeout_seconds"):
        DeadlinesConfig(
            worker_timeout_seconds=120,
            attempt_timeout_seconds=120,
            run_timeout_seconds=900,
        )

    # attempt_timeout < worker_timeout (unsafe)
    with pytest.raises((ValueError, ValidationError), match="attempt_timeout_seconds must exceed worker_timeout_seconds"):
        DeadlinesConfig(
            worker_timeout_seconds=120,
            attempt_timeout_seconds=100,
            run_timeout_seconds=900,
        )


def test_unsafe_timeout_run_deadline_not_exceeding_attempt_timeout():
    """Run execution deadline must exceed individual attempt timeout."""
    with pytest.raises((ValueError, ValidationError), match="run_timeout_seconds must exceed attempt_timeout_seconds"):
        DeadlinesConfig(
            worker_timeout_seconds=120,
            attempt_timeout_seconds=210,
            run_timeout_seconds=200,
        )


def test_claim_maximum_bounds_validation():
    """Claims per development must be at least 1."""
    with pytest.raises((ValueError, ValidationError)):
        ClaimsConfig(max_per_development=0)

    cfg = ClaimsConfig(max_per_development=4)
    assert cfg.max_per_development == 4


def test_unsafe_timeout_attempt_cannot_exceed_available_dispatch_window():
    """Attempt timeout cannot exceed run execution deadline minus finalization reserve."""
    with pytest.raises((ValueError, ValidationError), match="cannot exceed available dispatch window"):
        DeadlinesConfig(
            worker_timeout_seconds=120,
            attempt_timeout_seconds=890,
            run_timeout_seconds=900,
            finalization_reserve_seconds=30,  # 900 - 30 = 870s dispatch window, 890 > 870!
        )


def test_forbidden_terminal_status_codes_in_retries():
    """Terminal status codes (200, 400, 401, 409, 500) must not be configured as retryable."""
    with pytest.raises((ValueError, ValidationError), match="is terminal and cannot be configured as retryable"):
        RetriesConfig(retryable_status_codes=[503, 500])

    with pytest.raises((ValueError, ValidationError), match="is terminal and cannot be configured as retryable"):
        RetriesConfig(retryable_status_codes=[401])

    with pytest.raises((ValueError, ValidationError), match="is terminal and cannot be configured as retryable"):
        RetriesConfig(retryable_status_codes=[200])


def test_retries_bounds_validation():
    """Retries configuration validation."""
    with pytest.raises((ValueError, ValidationError)):
        RetriesConfig(max_attempts=0, backoff_initial_seconds=2.0, backoff_factor=2.0)

    with pytest.raises((ValueError, ValidationError)):
        RetriesConfig(max_attempts=3, backoff_initial_seconds=0.0, backoff_factor=2.0)

    with pytest.raises((ValueError, ValidationError)):
        RetriesConfig(max_attempts=3, backoff_initial_seconds=2.0, backoff_factor=0.5)
