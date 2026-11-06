"""
Tests for Task 5.3: Orchestration Accounting and Reservation Settlement.
CSCI-GA.2630 Assignment 2
"""

from uuid import uuid4
import pytest

from shared.config import BudgetsConfig
from shared.contracts import ResourceBudget, ResourceUsage
from backend.app.models import TrackerRun
from backend.app.orchestration.accounting import (
    record_researcher_reservation,
    record_verifier_reservation,
    settle_researcher_charge,
    settle_verifier_charge,
)


def test_researcher_reservation_before_dispatch():
    """Spec Requirement 5.3: Persists reservation before dispatch."""
    run = TrackerRun(topic="AI", target_k=5)
    req_id = uuid4()
    budget = ResourceBudget(max_steps=18, max_fetches=20, max_tokens=60000)

    record_researcher_reservation(run, req_id=req_id, budget=budget)

    assert run.researcher_request_id == str(req_id)
    assert run.reserved_steps == 18
    assert run.reserved_fetches == 20
    assert run.reserved_tokens == 60000
    assert run.measured_steps == 0
    assert run.charged_steps == 0


def test_verifier_reservation_accumulates_without_exceeding_total():
    """Spec Requirement 5.3: Total reserved bounded by config; unused shares not transferred."""
    run = TrackerRun(topic="AI", target_k=5)
    res_req_id = uuid4()
    ver_req_id = uuid4()
    budgets = BudgetsConfig()

    record_researcher_reservation(run, req_id=res_req_id, budget=budgets.researcher)
    record_verifier_reservation(run, req_id=ver_req_id, budget=budgets.verifier)

    assert run.researcher_request_id == str(res_req_id)
    assert run.verifier_request_id == str(ver_req_id)
    assert run.reserved_steps == budgets.total.max_steps
    assert run.reserved_fetches == budgets.total.max_fetches
    assert run.reserved_tokens == budgets.total.max_tokens


def test_settle_valid_response_charges_measured_usage():
    """Spec Requirement 5.3: On valid response, records measured usage and charges measured usage."""
    run = TrackerRun(topic="AI", target_k=5)
    budgets = BudgetsConfig()
    record_researcher_reservation(run, req_id=uuid4(), budget=budgets.researcher)

    # Worker returned valid response with actual usage
    usage = ResourceUsage(steps=5, fetches=8, tokens=15000)
    settle_researcher_charge(run, usage=usage, budget=budgets.researcher, success=True)

    assert run.measured_steps == 5
    assert run.measured_fetches == 8
    assert run.measured_tokens == 15000
    assert run.charged_steps == 5
    assert run.charged_fetches == 8
    assert run.charged_tokens == 15000


def test_settle_failed_or_invalid_response_charges_full_reservation():
    """Spec Requirement 5.3: Missing/malformed/failed response charges full reserved share."""
    run = TrackerRun(topic="AI", target_k=5)
    budgets = BudgetsConfig()
    record_researcher_reservation(run, req_id=uuid4(), budget=budgets.researcher)

    # Worker failed / invalid payload: usage is None or discarded
    settle_researcher_charge(run, usage=None, budget=budgets.researcher, success=False)

    # Measured remains 0 (estimates are never labeled measured)
    assert run.measured_steps == 0
    assert run.measured_fetches == 0
    assert run.measured_tokens == 0

    # Full reserved share is charged
    assert run.charged_steps == budgets.researcher.max_steps
    assert run.charged_fetches == budgets.researcher.max_fetches
    assert run.charged_tokens == budgets.researcher.max_tokens


def test_unused_shares_are_never_transferred():
    """Spec Requirement 5.3: Unused researcher shares are not transferred to verifier."""
    run = TrackerRun(topic="AI", target_k=5)
    budgets = BudgetsConfig()

    record_researcher_reservation(run, req_id=uuid4(), budget=budgets.researcher)
    # Researcher used only 2 steps (out of 18)
    settle_researcher_charge(
        run,
        usage=ResourceUsage(steps=2, fetches=3, tokens=5000),
        budget=budgets.researcher,
        success=True,
    )

    # Verifier still reserves exactly its own fixed share (12), NOT 12 + 16 = 28
    record_verifier_reservation(run, req_id=uuid4(), budget=budgets.verifier)
    assert run.reserved_steps == budgets.researcher.max_steps + budgets.verifier.max_steps

    settle_verifier_charge(
        run,
        usage=ResourceUsage(steps=4, fetches=5, tokens=10000),
        budget=budgets.verifier,
        success=True,
    )

    assert run.measured_steps == 6
    assert run.charged_steps == 6
    assert run.charged_steps <= budgets.total.max_steps
