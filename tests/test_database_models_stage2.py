"""
Unit tests for Task 2.1: Database Ownership and Stage 2 Models.
Verifies run UUIDs, protocol version, worker outcomes, reservations,
measured/charged usage, TrackerClaim rows, stale provenance, and cascade deletion.
"""

from datetime import datetime, timezone
import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.exc import IntegrityError

from backend.app.database import Base
from backend.app.models import User, TrackerRun, TrackerArticle, TrackerDevelopment, TrackerClaim


@pytest.fixture
def db_session():
    """Provides a fresh in-memory SQLite database session for model testing."""
    engine = create_engine("sqlite:///:memory:", echo=False)

    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()


def test_tracker_run_stage2_columns_and_defaults(db_session):
    """Verify that TrackerRun contains all required Stage 2 fields with valid defaults."""
    user = User(username="alice", email="alice@test.com", hashed_password="pwd")
    db_session.add(user)
    db_session.commit()

    run = TrackerRun(
        user_id=user.id,
        run_uuid="11111111-1111-1111-1111-111111111111",
        run_number=1,
        topic="Top 10 AI/ML Roles",
        target_k=10,
        status="running",
        protocol_version=2,
        reset_generation=0,
        is_baseline_eligible=False,
        reserved_steps=30,
        reserved_fetches=40,
        reserved_tokens=100000,
    )
    db_session.add(run)
    db_session.commit()

    loaded = db_session.query(TrackerRun).filter_by(id=run.id).one()
    assert loaded.run_uuid == "11111111-1111-1111-1111-111111111111"
    assert loaded.protocol_version == 2
    assert loaded.reset_generation == 0
    assert loaded.is_baseline_eligible is False
    assert loaded.reserved_steps == 30
    assert loaded.reserved_fetches == 40
    assert loaded.reserved_tokens == 100000
    assert loaded.measured_steps == 0
    assert loaded.measured_fetches == 0
    assert loaded.measured_tokens == 0
    assert loaded.charged_steps == 0
    assert loaded.charged_fetches == 0
    assert loaded.charged_tokens == 0
    assert loaded.researcher_status is None
    assert loaded.verifier_status is None
    assert loaded.researcher_error is None
    assert loaded.verifier_error is None
    assert loaded.researcher_request_id is None
    assert loaded.verifier_request_id is None
    assert loaded.stale_source_run_id is None


def test_tracker_run_unique_uuid_constraint(db_session):
    """Verify that run_uuid must be unique across all runs."""
    user = User(username="bob", email="bob@test.com", hashed_password="pwd")
    db_session.add(user)
    db_session.commit()

    uuid_str = "22222222-2222-2222-2222-222222222222"
    run1 = TrackerRun(user_id=user.id, run_uuid=uuid_str, topic="T", status="complete")
    db_session.add(run1)
    db_session.commit()

    run2 = TrackerRun(user_id=user.id, run_uuid=uuid_str, topic="T", status="complete")
    db_session.add(run2)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_tracker_claim_model_and_relationships(db_session):
    """Verify TrackerClaim creation, development relationship, and fields."""
    user = User(username="carol", email="carol@test.com", hashed_password="pwd")
    db_session.add(user)
    db_session.commit()

    run = TrackerRun(user_id=user.id, run_uuid="33333333-3333-3333-3333-333333333333", topic="T", status="complete")
    db_session.add(run)
    db_session.commit()

    dev = TrackerDevelopment(
        run_id=run.id,
        rank=1,
        title="ML Engineer",
        company="Anthropic",
        primary_url="https://jobs.lever.co/anthropic/1",
    )
    db_session.add(dev)
    db_session.commit()

    claim = TrackerClaim(
        run_id=run.id,
        development_id=dev.id,
        claim_id="c1",
        text="Starting compensation is $160,000.",
        source_url="https://jobs.lever.co/anthropic/1",
        verdict="supported",
        evidence="Starting compensation is $160,000 per year.",
    )
    db_session.add(claim)
    db_session.commit()

    loaded_dev = db_session.query(TrackerDevelopment).filter_by(id=dev.id).one()
    assert len(loaded_dev.claims) == 1
    assert loaded_dev.claims[0].claim_id == "c1"
    assert loaded_dev.claims[0].verdict == "supported"
    assert loaded_dev.claims[0].evidence == "Starting compensation is $160,000 per year."
    assert loaded_dev.claims[0].run_id == run.id


def test_cascade_deletion_from_user(db_session):
    """Verify that deleting a User cascades to runs, developments, articles, and claims."""
    user = User(username="dave", email="dave@test.com", hashed_password="pwd")
    db_session.add(user)
    db_session.commit()

    run = TrackerRun(user_id=user.id, run_uuid="44444444-4444-4444-4444-444444444444", topic="T", status="complete")
    db_session.add(run)
    db_session.commit()

    art = TrackerArticle(run_id=run.id, url="https://a.com", status="fetched")
    dev = TrackerDevelopment(run_id=run.id, rank=1, title="Role", company="Co", primary_url="https://a.com")
    db_session.add_all([art, dev])
    db_session.commit()

    claim = TrackerClaim(
        run_id=run.id,
        development_id=dev.id,
        claim_id="c-dave-1",
        text="Test claim",
        source_url="https://a.com",
        verdict="unverified",
    )
    db_session.add(claim)
    db_session.commit()

    # Save IDs before deletion
    run_id = run.id
    dev_id = dev.id
    art_id = art.id
    claim_id = claim.id

    # Pre-condition: entities exist
    assert db_session.query(TrackerRun).filter_by(id=run_id).count() == 1
    assert db_session.query(TrackerDevelopment).filter_by(id=dev_id).count() == 1
    assert db_session.query(TrackerArticle).filter_by(id=art_id).count() == 1
    assert db_session.query(TrackerClaim).filter_by(id=claim_id).count() == 1

    # Delete user
    db_session.delete(user)
    db_session.commit()

    # Post-condition: everything cascaded
    assert db_session.query(TrackerRun).filter_by(id=run_id).count() == 0
    assert db_session.query(TrackerDevelopment).filter_by(id=dev_id).count() == 0
    assert db_session.query(TrackerArticle).filter_by(id=art_id).count() == 0
    assert db_session.query(TrackerClaim).filter_by(id=claim_id).count() == 0


def test_stale_provenance_foreign_key(db_session):
    """Verify that stale_source_run_id links to a previous baseline run."""
    user = User(username="eve", email="eve@test.com", hashed_password="pwd")
    db_session.add(user)
    db_session.commit()

    baseline_run = TrackerRun(
        user_id=user.id,
        run_uuid="55555555-5555-5555-5555-555555555555",
        topic="T",
        status="complete",
        is_baseline_eligible=True,
    )
    db_session.add(baseline_run)
    db_session.commit()

    current_run = TrackerRun(
        user_id=user.id,
        run_uuid="66666666-6666-6666-6666-666666666666",
        topic="T",
        status="partial",
        stale_source_run_id=baseline_run.id,
        stale_source_run_uuid=baseline_run.run_uuid,
    )
    db_session.add(current_run)
    db_session.commit()

    loaded = db_session.query(TrackerRun).filter_by(id=current_run.id).one()
    assert loaded.stale_source_run_id == baseline_run.id
    assert loaded.stale_source_run_uuid == "55555555-5555-5555-5555-555555555555"


def test_tracker_claim_run_unique_constraint(db_session):
    """Verify that (run_id, claim_id) is unique within a run, but distinct runs can share claim_id."""
    user = User(username="frank", email="frank@test.com", hashed_password="pwd")
    db_session.add(user)
    db_session.commit()

    run1 = TrackerRun(user_id=user.id, run_uuid="77777777-7777-7777-7777-777777777777", topic="T", status="complete")
    run2 = TrackerRun(user_id=user.id, run_uuid="88888888-8888-8888-8888-888888888888", topic="T", status="complete")
    db_session.add_all([run1, run2])
    db_session.commit()

    dev1 = TrackerDevelopment(run_id=run1.id, rank=1, title="Dev 1", company="A", primary_url="https://a.com")
    dev2 = TrackerDevelopment(run_id=run2.id, rank=1, title="Dev 2", company="B", primary_url="https://b.com")
    db_session.add_all([dev1, dev2])
    db_session.commit()

    # Claim in run 1
    c1 = TrackerClaim(run_id=run1.id, development_id=dev1.id, claim_id="claim-abc", text="text1", source_url="https://a.com")
    # Same claim_id in run 2 should succeed (different run_id)
    c2 = TrackerClaim(run_id=run2.id, development_id=dev2.id, claim_id="claim-abc", text="text2", source_url="https://b.com")
    db_session.add_all([c1, c2])
    db_session.commit()

    # Duplicate claim_id within same run 1 must fail with IntegrityError
    dup_claim = TrackerClaim(run_id=run1.id, development_id=dev1.id, claim_id="claim-abc", text="dup", source_url="https://a.com")
    db_session.add(dup_claim)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_tracker_run_has_no_unrequested_updated_at_column():
    """Verify that TrackerRun does not include unrequested updated_at column."""
    run_columns = {col.name for col in TrackerRun.__table__.columns}
    assert "updated_at" not in run_columns
