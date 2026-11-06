"""
Orchestration Accounting and Resource Reservation Settlement.
Tracks immutable reservations before dispatch and settles measured vs. conservative charges.
CSCI-GA.2630 Assignment 2
"""

from typing import Any, Optional
from uuid import UUID

from shared.contracts import ResourceBudget, ResourceUsage
from backend.app.models import TrackerRun


def _record_reservation(
    run: TrackerRun,
    req_id: UUID,
    budget: ResourceBudget,
    is_researcher: bool,
) -> None:
    run_obj: Any = run
    if is_researcher:
        run_obj.researcher_request_id = str(req_id)
    else:
        run_obj.verifier_request_id = str(req_id)

    run_obj.reserved_steps = int(run_obj.reserved_steps or 0) + budget.max_steps
    run_obj.reserved_fetches = int(run_obj.reserved_fetches or 0) + budget.max_fetches
    run_obj.reserved_tokens = int(run_obj.reserved_tokens or 0) + budget.max_tokens

    run_obj.measured_steps = int(run_obj.measured_steps or 0)
    run_obj.measured_fetches = int(run_obj.measured_fetches or 0)
    run_obj.measured_tokens = int(run_obj.measured_tokens or 0)
    run_obj.charged_steps = int(run_obj.charged_steps or 0)
    run_obj.charged_fetches = int(run_obj.charged_fetches or 0)
    run_obj.charged_tokens = int(run_obj.charged_tokens or 0)


def record_researcher_reservation(
    run: TrackerRun,
    req_id: UUID,
    budget: ResourceBudget,
) -> None:
    """Records immutable Researcher request ID and reserves its fixed share."""
    _record_reservation(run, req_id, budget, is_researcher=True)


def record_verifier_reservation(
    run: TrackerRun,
    req_id: UUID,
    budget: ResourceBudget,
) -> None:
    """Records immutable Verifier request ID and reserves its fixed share."""
    _record_reservation(run, req_id, budget, is_researcher=False)


def _settle_charge(
    run: TrackerRun,
    usage: Optional[ResourceUsage],
    budget: ResourceBudget,
    success: bool,
) -> None:
    run_obj: Any = run
    run_obj.measured_steps = int(run_obj.measured_steps or 0)
    run_obj.measured_fetches = int(run_obj.measured_fetches or 0)
    run_obj.measured_tokens = int(run_obj.measured_tokens or 0)

    run_obj.charged_steps = int(run_obj.charged_steps or 0)
    run_obj.charged_fetches = int(run_obj.charged_fetches or 0)
    run_obj.charged_tokens = int(run_obj.charged_tokens or 0)

    if success and usage is not None:
        run_obj.measured_steps += usage.steps
        run_obj.measured_fetches += usage.fetches
        run_obj.measured_tokens += usage.tokens

        run_obj.charged_steps += usage.steps
        run_obj.charged_fetches += usage.fetches
        run_obj.charged_tokens += usage.tokens
    else:
        # Conservative charge of full reserved share; measured is NOT incremented
        run_obj.charged_steps += budget.max_steps
        run_obj.charged_fetches += budget.max_fetches
        run_obj.charged_tokens += budget.max_tokens

    # Mirror to legacy counter columns for backward compatibility
    run_obj.step_count = run_obj.charged_steps
    run_obj.fetch_count = run_obj.charged_fetches
    run_obj.tokens_spent = run_obj.charged_tokens


def settle_researcher_charge(
    run: TrackerRun,
    usage: Optional[ResourceUsage],
    budget: ResourceBudget,
    success: bool,
) -> None:
    """Settles Researcher resource consumption."""
    _settle_charge(run, usage, budget, success)


def settle_verifier_charge(
    run: TrackerRun,
    usage: Optional[ResourceUsage],
    budget: ResourceBudget,
    success: bool,
) -> None:
    """Settles Verifier resource consumption."""
    _settle_charge(run, usage, budget, success)
