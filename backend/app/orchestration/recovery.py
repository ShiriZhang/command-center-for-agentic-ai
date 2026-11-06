"""
Startup Interruption Recovery.
Recovers running runs on backend startup without automatic redispatch,
charging unresolved reservations conservatively and preventing baseline replacement.
CSCI-GA.2630 Assignment 2
"""

from typing import Any, Optional
from sqlalchemy.orm import Session

from shared.config import BudgetsConfig, load_orchestration_config
from backend.app.models import TrackerClaim, TrackerRun


def recover_interrupted_runs(
    db: Session,
    budgets: Optional[BudgetsConfig] = None,
) -> int:
    """
    Recovers runs left in 'running' state after a server restart or crash:
    - Sets run status to 'partial'
    - Ensures is_baseline_eligible = False (never replaces the baseline)
    - Marks incomplete worker statuses as 'interrupted'
    - Charges unresolved worker allocations conservatively
    - Leaves already committed progress intact
    - Marks any unverified claims as 'unverified'
    - Does NOT automatically redispatch
    Returns the number of recovered runs.
    """
    resolved_budgets = budgets or load_orchestration_config().budgets
    running_runs = db.query(TrackerRun).filter(TrackerRun.status == "running").all()
    if not running_runs:
        return 0

    for run in running_runs:
        r: Any = run
        r.status = "partial"
        r.is_baseline_eligible = False

        # Recover researcher stage if interrupted
        if r.researcher_status not in ("complete", "partial", "failed"):
            r.researcher_status = "interrupted"
            r.researcher_error = "Server restarted during execution"
            if r.researcher_request_id:
                r.charged_steps = int(r.charged_steps or 0) + resolved_budgets.researcher.max_steps
                r.charged_fetches = int(r.charged_fetches or 0) + resolved_budgets.researcher.max_fetches
                r.charged_tokens = int(r.charged_tokens or 0) + resolved_budgets.researcher.max_tokens

        # Recover verifier stage if interrupted
        if r.verifier_status not in ("complete", "partial", "failed", "skipped"):
            if r.verifier_request_id:
                r.verifier_status = "interrupted"
                r.verifier_error = "Server restarted during execution"
                r.charged_steps = int(r.charged_steps or 0) + resolved_budgets.verifier.max_steps
                r.charged_fetches = int(r.charged_fetches or 0) + resolved_budgets.verifier.max_fetches
                r.charged_tokens = int(r.charged_tokens or 0) + resolved_budgets.verifier.max_tokens
            else:
                r.verifier_status = "skipped"

        # Mark all pending claims as unverified
        unverified_claims = (
            db.query(TrackerClaim)
            .filter(TrackerClaim.run_id == run.id, TrackerClaim.verdict.is_(None))
            .all()
        )
        for claim in unverified_claims:
            r_c: Any = claim
            r_c.verdict = "unverified"
            r_c.evidence = None

        # Synchronize legacy columns
        r.step_count = r.charged_steps
        r.fetch_count = r.charged_fetches
        r.tokens_spent = r.charged_tokens

    db.commit()
    return len(running_runs)
