"""
Tests for Tasks 5.5 & 5.6: Orchestration Lifecycle, Partial Progress, and Baseline Scoping.
CSCI-GA.2630 Assignment 2
"""

from datetime import datetime, timezone
from unittest.mock import MagicMock
from uuid import uuid4
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from shared.config import BudgetsConfig
from shared.contracts import (
    AtomicClaim,
    ClaimVerdict,
    Development,
    ResearchResponse,
    ResearchResult,
    ResourceBudget,
    ResourceUsage,
    VerifyClaimInput,
    VerifyResponse,
    VerifyResult,
    WorkerError,
)
from backend.app.models import Base, TrackerClaim, TrackerDevelopment, TrackerRun, User
from backend.app.orchestration.dispatch import DispatchResult
from backend.app.orchestration.lifecycle import execute_orchestration_lifecycle


@pytest.fixture
def db_session():
    """In-memory SQLite database session fixture."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()

    user = User(id=1, username="alice", email="alice@example.com", hashed_password="pw")
    session.add(user)
    session.commit()

    yield session
    session.close()


def test_complete_research_and_complete_verify(db_session):
    """Spec 5.5: Complete research + complete verify promotes to baseline and marks complete."""
    run = TrackerRun(
        user_id=1,
        run_uuid=str(uuid4()),
        run_number=1,
        topic="AI",
        target_k=1,
        status="running",
        protocol_version=2,
        reset_generation=0,
    )
    db_session.add(run)
    db_session.commit()

    dispatcher = MagicMock()
    dispatcher.budgets = BudgetsConfig()
    req_res_id = uuid4()
    req_ver_id = uuid4()

    res_resp = ResearchResponse(
        request_id=req_res_id,
        run_id=uuid4(),
        status="complete",
        result=ResearchResult(
            developments=[
                Development(
                    id="dev-1",
                    title="Lead AI Engineer",
                    company="Tech Corp",
                    summary="Build agents",
                    claims=[
                        AtomicClaim(
                            claim_id="c1",
                            text="Requires Python",
                            source_url="https://example.com/job1",
                        )
                    ],
                )
            ]
        ),
        usage=ResourceUsage(steps=5, fetches=4, tokens=10000),
        error=None,
    )
    dispatcher.dispatch_research.return_value = DispatchResult(
        success=True,
        response=res_resp,
        status_code=200,
        measured_usage=res_resp.usage,
        request_id=req_res_id,
    )

    ver_resp = VerifyResponse(
        request_id=req_ver_id,
        run_id=uuid4(),
        status="complete",
        result=VerifyResult(
            verdicts=[
                ClaimVerdict(claim_id="c1", verdict="supported", evidence="Requires Python")
            ]
        ),
        usage=ResourceUsage(steps=3, fetches=2, tokens=5000),
        error=None,
    )
    dispatcher.dispatch_verify.return_value = DispatchResult(
        success=True,
        response=ver_resp,
        status_code=200,
        measured_usage=ver_resp.usage,
        request_id=req_ver_id,
    )

    executed_run = execute_orchestration_lifecycle(db=db_session, run_id=run.id, dispatcher=dispatcher)

    assert executed_run.status == "complete"
    assert executed_run.researcher_status == "complete"
    assert executed_run.verifier_status == "complete"
    assert executed_run.is_baseline_eligible is True

    # Check developments & claims
    assert len(executed_run.developments) == 1
    dev = executed_run.developments[0]
    assert dev.title == "Lead AI Engineer"
    assert dev.recrawl_status == "New since last run"

    assert len(dev.claims) == 1
    claim = dev.claims[0]
    assert claim.claim_id == "c1"
    assert claim.verdict == "supported"
    assert claim.evidence == "Requires Python"


def test_verifier_failure_leaves_claims_unverified_and_allows_baseline(db_session):
    """Spec 5.5 & 5.6: Verifier failure leaves claims unverified; complete research still eligible for baseline."""
    run = TrackerRun(
        user_id=1,
        run_uuid=str(uuid4()),
        run_number=1,
        topic="AI",
        target_k=1,
        status="running",
        protocol_version=2,
        reset_generation=0,
    )
    db_session.add(run)
    db_session.commit()

    dispatcher = MagicMock()
    dispatcher.budgets = BudgetsConfig()
    req_res_id = uuid4()

    res_resp = ResearchResponse(
        request_id=req_res_id,
        run_id=uuid4(),
        status="complete",
        result=ResearchResult(
            developments=[
                Development(
                    id="dev-1",
                    title="Researcher Role",
                    company="Lab Corp",
                    summary="Research ML",
                    claims=[
                        AtomicClaim(
                            claim_id="c1",
                            text="Ph.D. preferred",
                            source_url="https://example.com/job",
                        )
                    ],
                )
            ]
        ),
        usage=ResourceUsage(steps=6, fetches=5, tokens=12000),
        error=None,
    )
    dispatcher.dispatch_research.return_value = DispatchResult(
        success=True,
        response=res_resp,
        status_code=200,
        measured_usage=res_resp.usage,
        request_id=req_res_id,
    )

    # Verifier fails (e.g. 500 or timeout)
    dispatcher.dispatch_verify.return_value = DispatchResult(
        success=False,
        response=None,
        status_code=500,
        error_code="http_500",
        error_message="Verifier crashed",
        request_id=uuid4(),
    )

    executed_run = execute_orchestration_lifecycle(db=db_session, run_id=run.id, dispatcher=dispatcher)

    # Verifier failed -> overall status is partial
    assert executed_run.status == "partial"
    assert executed_run.researcher_status == "complete"
    assert executed_run.verifier_status == "failed"
    # Complete researcher -> baseline eligible!
    assert executed_run.is_baseline_eligible is True

    # Claims remain unverified
    assert len(executed_run.developments) == 1
    claim = executed_run.developments[0].claims[0]
    assert claim.verdict == "unverified"
    assert claim.evidence is None


def test_partial_research_not_eligible_for_baseline(db_session):
    """Spec 5.6: Partial research never promotes to baseline and never creates false dropped."""
    run = TrackerRun(
        user_id=1,
        run_uuid=str(uuid4()),
        run_number=1,
        topic="AI",
        target_k=5,
        status="running",
        protocol_version=2,
        reset_generation=0,
    )
    db_session.add(run)
    db_session.commit()

    dispatcher = MagicMock()
    dispatcher.budgets = BudgetsConfig()
    req_res_id = uuid4()

    # Researcher stopped early due to time budget (partial)
    res_resp = ResearchResponse(
        request_id=req_res_id,
        run_id=uuid4(),
        status="partial",
        result=ResearchResult(
            developments=[
                Development(
                    id="dev-1",
                    title="Junior Dev",
                    company="Small Co",
                    summary="Summary",
                    claims=[
                        AtomicClaim(
                            claim_id="c1",
                            text="Entry level",
                            source_url="https://example.com/dev",
                        )
                    ],
                )
            ]
        ),
        usage=ResourceUsage(steps=2, fetches=2, tokens=3000),
        error=WorkerError(code="time_budget_exhausted", message="Timeout", retryable=False),
    )
    dispatcher.dispatch_research.return_value = DispatchResult(
        success=True,
        response=res_resp,
        status_code=200,
        measured_usage=res_resp.usage,
        request_id=req_res_id,
    )

    # Verifier completes verification of partial claims
    dispatcher.dispatch_verify.return_value = DispatchResult(
        success=True,
        response=VerifyResponse(
            request_id=uuid4(),
            run_id=uuid4(),
            status="complete",
            result=VerifyResult(
                verdicts=[
                    ClaimVerdict(claim_id="c1", verdict="unsupported", evidence=None)
                ]
            ),
            usage=ResourceUsage(steps=1, fetches=1, tokens=1000),
            error=None,
        ),
        status_code=200,
        measured_usage=ResourceUsage(steps=1, fetches=1, tokens=1000),
        request_id=uuid4(),
    )

    executed_run = execute_orchestration_lifecycle(db=db_session, run_id=run.id, dispatcher=dispatcher)

    assert executed_run.status == "partial"
    assert executed_run.researcher_status == "partial"
    assert executed_run.verifier_status == "complete"
    # Partial research NEVER promotes to baseline!
    assert executed_run.is_baseline_eligible is False

    # Unsupported claim retains development in rank
    assert len(executed_run.developments) == 1
    assert executed_run.developments[0].claims[0].verdict == "unsupported"


def test_researcher_failure_stale_baseline_fallback(db_session):
    """Spec 5.6: If researcher fails and baseline exists, fallback to stale baseline with original attribution."""
    # First, create a prior baseline run
    baseline_run = TrackerRun(
        user_id=1,
        run_uuid=str(uuid4()),
        run_number=1,
        topic="AI",
        target_k=1,
        status="complete",
        protocol_version=2,
        reset_generation=0,
        is_baseline_eligible=True,
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    db_session.add(baseline_run)
    db_session.flush()

    b_dev = TrackerDevelopment(
        run_id=baseline_run.id,
        rank=1,
        title="Historical Role",
        company="Old Corp",
        primary_url="https://example.com/old",
        fingerprint="Old Corp:Historical Role",
        recrawl_status="New since last run",
    )
    db_session.add(b_dev)
    db_session.flush()

    b_claim = TrackerClaim(
        run_id=baseline_run.id,
        development_id=b_dev.id,
        claim_id="bc1",
        text="Historical claim",
        source_url="https://example.com/old",
        verdict="supported",
        evidence="Historical excerpt",
    )
    db_session.add(b_claim)
    db_session.commit()

    # Now execute Run 2 where researcher completely fails
    run2 = TrackerRun(
        user_id=1,
        run_uuid=str(uuid4()),
        run_number=2,
        topic="AI",
        target_k=1,
        status="running",
        protocol_version=2,
        reset_generation=0,
        created_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
    )
    db_session.add(run2)
    db_session.commit()

    dispatcher = MagicMock()
    dispatcher.budgets = BudgetsConfig()
    dispatcher.dispatch_research.return_value = DispatchResult(
        success=False,
        response=None,
        status_code=500,
        error_code="http_500",
        error_message="Researcher network error",
        request_id=uuid4(),
    )

    executed_run = execute_orchestration_lifecycle(db=db_session, run_id=run2.id, dispatcher=dispatcher)

    assert executed_run.status == "partial"
    assert executed_run.researcher_status == "failed"
    assert executed_run.is_baseline_eligible is False

    # Verifier was skipped because researcher failed
    dispatcher.dispatch_verify.assert_not_called()

    # Stale fallback linked!
    assert executed_run.stale_source_run_id == baseline_run.id
    assert executed_run.stale_source_run_uuid == baseline_run.run_uuid

    # Copied developments have historical attribution preserved
    assert len(executed_run.developments) == 1
    dev = executed_run.developments[0]
    assert dev.title == "Historical Role"
    assert len(dev.claims) == 1
    assert dev.claims[0].verdict == "supported"
    assert dev.claims[0].evidence == "Historical excerpt"


def test_complete_research_generates_dropped_jobs_and_partial_never_drops(db_session):
    """Spec 5.6: Complete research identifies dropped jobs from baseline; partial research never drops."""
    # 1. Baseline Run
    b_run = TrackerRun(
        user_id=1,
        run_uuid=str(uuid4()),
        run_number=1,
        topic="AI",
        target_k=1,
        status="complete",
        protocol_version=2,
        is_baseline_eligible=True,
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    db_session.add(b_run)
    db_session.flush()

    b_dev = TrackerDevelopment(
        run_id=b_run.id,
        rank=1,
        title="Old Job",
        company="Old Co",
        primary_url="https://example.com/old",
        fingerprint="Old Co:Old Job",
    )
    db_session.add(b_dev)
    db_session.commit()

    # 2. Run 2: Complete research with brand new job
    run2 = TrackerRun(
        user_id=1,
        run_uuid=str(uuid4()),
        run_number=2,
        topic="AI",
        target_k=1,
        status="running",
        protocol_version=2,
        created_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
    )
    db_session.add(run2)
    db_session.commit()

    dispatcher = MagicMock()
    dispatcher.budgets = BudgetsConfig()
    dispatcher.dispatch_research.return_value = DispatchResult(
        success=True,
        response=ResearchResponse(
            request_id=uuid4(),
            run_id=uuid4(),
            status="complete",
            result=ResearchResult(
                developments=[
                    Development(
                        id="dev-2",
                        title="New Job",
                        company="New Co",
                        summary="Summary",
                        claims=[AtomicClaim(claim_id="c2", text="Claim text", source_url="https://example.com/new")],
                    )
                ]
            ),
            usage=ResourceUsage(steps=5, fetches=5, tokens=10000),
            error=None,
        ),
        status_code=200,
        measured_usage=ResourceUsage(steps=5, fetches=5, tokens=10000),
        request_id=uuid4(),
    )
    dispatcher.dispatch_verify.return_value = DispatchResult(
        success=True,
        response=VerifyResponse(
            request_id=uuid4(),
            run_id=uuid4(),
            status="complete",
            result=VerifyResult(verdicts=[ClaimVerdict(claim_id="c2", verdict="supported", evidence="Claim text")]),
            usage=ResourceUsage(steps=2, fetches=2, tokens=2000),
            error=None,
        ),
        status_code=200,
        measured_usage=ResourceUsage(steps=2, fetches=2, tokens=2000),
        request_id=uuid4(),
    )

    exec_run2 = execute_orchestration_lifecycle(db=db_session, run_id=run2.id, dispatcher=dispatcher)

    # Has 2 developments: 1 New and 1 Dropped
    assert len(exec_run2.developments) == 2
    statuses = [d.recrawl_status for d in exec_run2.developments]
    assert "New since last run" in statuses
    assert "Dropped" in statuses

