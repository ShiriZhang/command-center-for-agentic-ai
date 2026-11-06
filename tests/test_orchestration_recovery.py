"""
Tests for Task 5.7: Backend Startup Interruption Recovery.
CSCI-GA.2630 Assignment 2
"""

from datetime import datetime, timezone
from uuid import uuid4
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from shared.config import BudgetsConfig
from backend.app.models import Base, TrackerClaim, TrackerDevelopment, TrackerRun, User
from backend.app.orchestration.accounting import record_researcher_reservation, record_verifier_reservation
from backend.app.orchestration.recovery import recover_interrupted_runs


@pytest.fixture
def db_session():
    """In-memory SQLite database session fixture."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()

    user = User(id=1, username="bob", email="bob@example.com", hashed_password="pw")
    session.add(user)
    session.commit()

    yield session
    session.close()


def test_recover_running_run_at_researcher_stage(db_session):
    """Spec 5.7: Interrupted during researcher dispatch becomes partial with conservative charges."""
    run = TrackerRun(
        user_id=1,
        run_uuid=str(uuid4()),
        run_number=1,
        topic="AI",
        target_k=5,
        status="running",
        protocol_version=2,
        is_baseline_eligible=False,
    )
    db_session.add(run)
    db_session.flush()

    budgets = BudgetsConfig()
    record_researcher_reservation(run, req_id=uuid4(), budget=budgets.researcher)
    db_session.commit()

    # Trigger recovery
    recovered_count = recover_interrupted_runs(db=db_session, budgets=budgets)

    assert recovered_count == 1
    db_session.refresh(run)

    assert run.status == "partial"
    assert run.researcher_status == "interrupted"
    assert "Server restarted" in run.researcher_error
    assert run.is_baseline_eligible is False

    # Unresolved researcher allocation is charged conservatively
    assert run.charged_steps == budgets.researcher.max_steps
    assert run.charged_fetches == budgets.researcher.max_fetches
    assert run.charged_tokens == budgets.researcher.max_tokens
    assert run.measured_steps == 0


def test_recover_running_run_at_verifier_stage_preserves_progress(db_session):
    """Spec 5.7: Interrupted during verifier preserves researcher progress and marks claims unverified."""
    run = TrackerRun(
        user_id=1,
        run_uuid=str(uuid4()),
        run_number=2,
        topic="AI",
        target_k=1,
        status="running",
        protocol_version=2,
        researcher_status="complete",
        measured_steps=5,
        measured_fetches=6,
        measured_tokens=10000,
        charged_steps=5,
        charged_fetches=6,
        charged_tokens=10000,
    )
    db_session.add(run)
    db_session.flush()

    dev = TrackerDevelopment(
        run_id=run.id,
        rank=1,
        title="Saved Role",
        company="Saved Corp",
        primary_url="https://example.com/saved",
        recrawl_status="New since last run",
    )
    db_session.add(dev)
    db_session.flush()

    claim = TrackerClaim(
        run_id=run.id,
        development_id=dev.id,
        claim_id="c1",
        text="Saved claim",
        source_url="https://example.com/saved",
        verdict="unverified",
    )
    db_session.add(claim)
    db_session.flush()

    budgets = BudgetsConfig()
    record_verifier_reservation(run, req_id=uuid4(), budget=budgets.verifier)
    db_session.commit()

    recovered_count = recover_interrupted_runs(db=db_session, budgets=budgets)

    assert recovered_count == 1
    db_session.refresh(run)

    assert run.status == "partial"
    assert run.researcher_status == "complete"
    assert run.verifier_status == "interrupted"
    # Interrupted work never replaces the baseline
    assert run.is_baseline_eligible is False

    # Stored progress survived
    assert len(run.developments) == 1
    assert run.developments[0].title == "Saved Role"
    assert run.developments[0].claims[0].verdict == "unverified"

    # Researcher measured charge preserved (5) + verifier charged full reservation (12)
    assert run.measured_steps == 5
    assert run.charged_steps == 5 + budgets.verifier.max_steps
