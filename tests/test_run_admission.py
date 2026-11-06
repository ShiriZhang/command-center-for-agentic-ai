"""
Unit tests for Task 2.3: Database-backed Per-User Run Admission and Numbering.
Verifies atomic admission, per-user sequence numbering, active run conflict (409),
and independent user isolation.
"""

from concurrent.futures import ThreadPoolExecutor
from typing import Any, List
import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import sessionmaker

from backend.app.database import Base
from backend.app.models import User, TrackerRun
from backend.app.orchestration.admission import admit_user_run, ActiveRunConflictError


@pytest.fixture
def db_session_factory():
    """Sets up an in-memory SQLite database and returns a sessionmaker factory."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False)

    # Populate two test users
    session = Session()
    u1 = User(username="user1", email="user1@nyu.edu", hashed_password="pwd")
    u2 = User(username="user2", email="user2@nyu.edu", hashed_password="pwd")
    session.add_all([u1, u2])
    session.commit()
    session.close()

    return Session


def test_admit_first_run_for_user(db_session_factory):
    """Verify first admitted run gets run_number=1 and status='running'."""
    db = db_session_factory()
    try:
        run: Any = admit_user_run(db, user_id=1, topic="AI Engineer", target_k=10)
        assert run.status == "running"
        assert run.run_number == 1
        assert run.protocol_version == 2
        assert len(str(run.run_uuid)) == 36
        assert run.user_id == 1
    finally:
        db.close()


def test_admit_subsequent_run_increments_run_number(db_session_factory):
    """Verify that after completing run 1, run 2 gets run_number=2."""
    db = db_session_factory()
    try:
        run1: Any = admit_user_run(db, user_id=1, topic="AI Engineer", target_k=10)
        run1.status = "complete"
        db.commit()

        run2: Any = admit_user_run(db, user_id=1, topic="AI Engineer", target_k=10)
        assert run2.status == "running"
        assert run2.run_number == 2
        assert run2.run_uuid != run1.run_uuid
    finally:
        db.close()


def test_duplicate_trigger_while_running_raises_conflict(db_session_factory):
    """Verify that triggering a run while another is active raises ActiveRunConflictError."""
    db = db_session_factory()
    try:
        run1: Any = admit_user_run(db, user_id=1, topic="AI Engineer", target_k=10)
        assert run1.status == "running"

        with pytest.raises(ActiveRunConflictError) as exc_info:
            admit_user_run(db, user_id=1, topic="AI Engineer", target_k=10)

        assert "already has an active run" in str(exc_info.value)
        assert exc_info.value.active_run_uuid == run1.run_uuid
        assert exc_info.value.user_id == 1
        assert exc_info.value.status_code == 409
    finally:
        db.close()


def test_independent_users_run_in_parallel(db_session_factory):
    """Verify that User 1 and User 2 can both have active running runs simultaneously."""
    db1 = db_session_factory()
    db2 = db_session_factory()
    try:
        run1: Any = admit_user_run(db1, user_id=1, topic="Topic A", target_k=10)
        run2: Any = admit_user_run(db2, user_id=2, topic="Topic B", target_k=5)

        assert run1.status == "running"
        assert run2.status == "running"
        assert run1.user_id == 1
        assert run2.user_id == 2
        assert run1.run_number == 1
        assert run2.run_number == 1
    finally:
        db1.close()
        db2.close()


def test_concurrent_admissions_for_same_user_admit_exactly_one(db_session_factory):
    """Verify that concurrent admission attempts for the same user allow only 1 winner."""
    results: List[str] = []
    errors: List[ActiveRunConflictError] = []

    def attempt_admission():
        db = db_session_factory()
        try:
            run: Any = admit_user_run(db, user_id=1, topic="Concurrent Topic", target_k=10)
            results.append(str(run.run_uuid))
        except ActiveRunConflictError as e:
            errors.append(e)
        finally:
            db.close()

    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(attempt_admission) for _ in range(5)]
        for f in futures:
            f.result()

    # Exactly 1 success, 4 conflicts
    assert len(results) == 1
    assert len(errors) == 4
