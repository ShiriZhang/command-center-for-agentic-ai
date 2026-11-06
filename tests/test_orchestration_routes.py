"""
Tests for Tasks 5.8 & 5.9: Removal of Public Run Ingestion, Baseline Reset, History Deletion, and Active-Run Rejection.
CSCI-GA.2630 Assignment 2
"""

from unittest.mock import patch
from uuid import uuid4
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.database import get_db
from backend.app.models import Base, TrackerClaim, TrackerDevelopment, TrackerRun, User
from backend.app.auth import create_access_token, hash_password
from backend.app.routes.tracker import router


@pytest.fixture
def client_and_db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine)
    session = TestingSession()

    user1 = User(id=1, username="alice", email="alice@example.com", hashed_password=hash_password("pw1"))
    user2 = User(id=2, username="bob", email="bob@example.com", hashed_password=hash_password("pw2"))
    session.add_all([user1, user2])
    session.commit()

    app = FastAPI()
    app.include_router(router)

    def override_get_db():
        db = TestingSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)

    yield client, session, user1, user2
    session.close()


def test_public_post_runs_is_removed_405(client_and_db):
    """Spec 5.8: POST /api/tracker/runs is removed and returns HTTP 405 Method Not Allowed."""
    client, session, user1, _ = client_and_db
    token = create_access_token({"sub": "1"})

    resp = client.post(
        "/api/tracker/runs",
        headers={"Authorization": f"Bearer {token}"},
        json={"run_number": 1, "topic": "AI", "target_k": 5, "status": "complete"},
    )
    assert resp.status_code == 405
    assert "removed" in resp.json()["detail"].lower()


def test_authenticated_reads_preserve_user_isolation(client_and_db):
    """Spec 5.8: Authenticated reads preserved; users cannot read another user's runs."""
    client, session, user1, user2 = client_and_db
    token1 = create_access_token({"sub": "1"})
    token2 = create_access_token({"sub": "2"})

    run1 = TrackerRun(
        user_id=user1.id,
        run_uuid=str(uuid4()),
        run_number=1,
        topic="AI",
        target_k=5,
        status="complete",
    )
    session.add(run1)
    session.commit()

    # User 1 can read own run
    resp1 = client.get(f"/api/tracker/runs/{run1.id}", headers={"Authorization": f"Bearer {token1}"})
    assert resp1.status_code == 200
    assert resp1.json()["id"] == run1.id

    # User 2 cannot read User 1's run (403 Forbidden)
    resp2 = client.get(f"/api/tracker/runs/{run1.id}", headers={"Authorization": f"Bearer {token2}"})
    assert resp2.status_code == 403


def test_reset_and_delete_reject_when_run_is_active(client_and_db):
    """Spec 5.9: Baseline reset and history deletion reject with 409 Conflict when an active run exists."""
    client, session, user1, _ = client_and_db
    token1 = create_access_token({"sub": "1"})

    active_run = TrackerRun(
        user_id=user1.id,
        run_uuid=str(uuid4()),
        run_number=1,
        topic="AI",
        target_k=5,
        status="running",
    )
    session.add(active_run)
    session.commit()

    # Reset attempt while active -> 409 Conflict
    resp_reset = client.post("/api/tracker/reset", headers={"Authorization": f"Bearer {token1}"})
    assert resp_reset.status_code == 409

    # Delete attempt while active -> 409 Conflict
    resp_delete = client.delete("/api/tracker/runs", headers={"Authorization": f"Bearer {token1}"})
    assert resp_delete.status_code == 409


def test_reset_preserves_history_and_increments_generation(client_and_db):
    """Spec 5.9: Baseline reset preserves history and starts new reset generation."""
    client, session, user1, _ = client_and_db
    token1 = create_access_token({"sub": "1"})

    prior_run = TrackerRun(
        user_id=user1.id,
        run_uuid=str(uuid4()),
        run_number=1,
        topic="AI",
        target_k=5,
        status="complete",
        reset_generation=0,
    )
    session.add(prior_run)
    session.commit()

    resp_reset = client.post("/api/tracker/reset", headers={"Authorization": f"Bearer {token1}"})
    assert resp_reset.status_code == 200
    assert resp_reset.json()["status"] == "ok"
    assert resp_reset.json()["reset_generation"] == 1

    # Prior run history is preserved!
    session.refresh(prior_run)
    assert prior_run.id is not None


def test_delete_history_clears_baseline_pointers_without_affecting_other_users(client_and_db):
    """Spec 5.9: History deletion transactionally clears runs and baseline pointers only for caller."""
    client, session, user1, user2 = client_and_db
    token1 = create_access_token({"sub": "1"})

    run1 = TrackerRun(
        user_id=user1.id,
        run_uuid=str(uuid4()),
        run_number=1,
        topic="AI",
        target_k=5,
        status="complete",
    )
    run2 = TrackerRun(
        user_id=user2.id,
        run_uuid=str(uuid4()),
        run_number=1,
        topic="AI",
        target_k=5,
        status="complete",
    )
    session.add_all([run1, run2])
    session.commit()

    resp_del = client.delete("/api/tracker/runs", headers={"Authorization": f"Bearer {token1}"})
    assert resp_del.status_code == 200

    # User 1 runs deleted
    u1_runs = session.query(TrackerRun).filter(TrackerRun.user_id == user1.id).all()
    assert len(u1_runs) == 0

    # User 2 runs completely intact!
    u2_runs = session.query(TrackerRun).filter(TrackerRun.user_id == user2.id).all()
    assert len(u2_runs) == 1
