"""
Unit tests for Task 3.5: Researcher Request-Local Resource Accounting and Runtime Execution.
Verifies pre-call token reservations, conservative unknown-usage charges,
redirect/discovery fetch counting, and graceful partial return on tiny budgets.
"""

from uuid import uuid4
import pytest
from unittest.mock import MagicMock

from shared.contracts import (
    ResearchRequest,
    ResearchPayload,
    ResourceBudget,
    ResearchResponse,
    WorkerResponseEnvelope,
)
from services.researcher.runtime import RequestTracker, execute_research


def test_tracker_pre_call_token_reservation():
    """Model call must be rejected before invocation if token bound does not fit in remaining budget."""
    tracker = RequestTracker(
        budget=ResourceBudget(max_steps=5, max_fetches=5, max_tokens=1000),
        time_budget_ms=10000,
    )
    # 800 tokens fits
    can_call, _ = tracker.can_call_model(conservative_token_bound=800)
    assert can_call is True

    # 1200 tokens does NOT fit in 1000 max_tokens
    can_call_big, reason = tracker.can_call_model(conservative_token_bound=1200)
    assert can_call_big is False
    assert "token" in str(reason).lower()


def test_tracker_records_actual_or_conservative_tokens():
    """If actual tokens returned, charge actual; if None (failed/unknown), charge reserved bound."""
    tracker = RequestTracker(
        budget=ResourceBudget(max_steps=5, max_fetches=5, max_tokens=10000),
        time_budget_ms=10000,
    )
    # Call 1: measured tokens returned
    tracker.record_model_call(reserved_tokens=2000, actual_tokens=1450)
    assert tracker.steps == 1
    assert tracker.tokens == 1450

    # Call 2: failed/unknown usage -> retains conservative reservation
    tracker.record_model_call(reserved_tokens=3000, actual_tokens=None)
    assert tracker.steps == 2
    assert tracker.tokens == 4450  # 1450 + 3000


def test_tracker_fetch_and_redirect_counting():
    """Each redirect hop counts as an additional fetch; blocked calls count 0."""
    tracker = RequestTracker(
        budget=ResourceBudget(max_steps=5, max_fetches=10, max_tokens=10000),
        time_budget_ms=10000,
    )
    # Search API call counts as 1 fetch
    tracker.record_discovery_call()
    assert tracker.fetches == 1

    # Fetch with 2 redirects counts as 1 initial + 2 hops = 3
    tracker.record_page_fetch(redirect_hops=2)
    assert tracker.fetches == 4

    # Blocked pre-flight call consumes 0 fetches
    tracker.record_blocked_fetch()
    assert tracker.fetches == 4


def test_execute_research_stops_with_partial_when_budget_tiny():
    """Execution with tiny budget stops before exhaustion and returns valid partial response."""
    req = ResearchRequest(
        request_id=uuid4(),
        run_id=uuid4(),
        time_budget_ms=1,  # 1ms deadline!
        budget=ResourceBudget(max_steps=18, max_fetches=20, max_tokens=60000),
        payload=ResearchPayload(topic="AI Engineer", k=5),
    )

    resp = execute_research(req)
    assert isinstance(resp, WorkerResponseEnvelope)
    assert resp.request_id == req.request_id
    assert resp.run_id == req.run_id
    assert resp.status == "partial"
    assert resp.error is not None
    assert resp.error.retryable is False
    assert "exhausted" in resp.error.code.lower() or "timeout" in resp.error.code.lower()
    assert resp.result is not None


def test_execute_research_step_limit_partial():
    """Execution stops when max_steps=0 is supplied."""
    req = ResearchRequest(
        request_id=uuid4(),
        run_id=uuid4(),
        time_budget_ms=60000,
        budget=ResourceBudget(max_steps=0, max_fetches=20, max_tokens=60000),  # 0 steps!
        payload=ResearchPayload(topic="AI Engineer", k=5),
    )

    resp = execute_research(req)
    assert resp.status == "partial"
    assert resp.error is not None
    assert resp.usage.steps <= req.budget.max_steps
