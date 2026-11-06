"""
Unit tests for Task 2.4: Selected-User Legacy Cleanup.
Verifies preview, protocol-version filtering, transactional deletion,
preservation of users/new runs/other users/files, and repeat-call safety.
"""

from pathlib import Path
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.database import Base
from backend.app.models import User, TrackerRun, TrackerArticle, TrackerDevelopment, TrackerClaim
from backend.app.orchestration.cleanup import (
    preview_legacy_cleanup,
    execute_legacy_cleanup,
    build_cleanup_parser,
    main,
    LegacyCleanupPreview,
    LegacyCleanupResult,
)
from backend.app.orchestration.admission import ActiveRunConflictError


@pytest.fixture
def db_session(tmp_path):
    """Sets up an in-memory SQLite database populated with legacy and new runs for two users."""
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()

    # User 1 & User 2
    u1 = User(username="user1", email="u1@test.com", hashed_password="pwd")
    u2 = User(username="user2", email="u2@test.com", hashed_password="pwd")
    session.add_all([u1, u2])
    session.commit()

    # Create a dummy report file on disk
    dummy_report = tmp_path / "reports_run1.md"
    dummy_report.write_text("# Old Report Content", encoding="utf-8")

    # User 1: 2 legacy runs (protocol 1), 1 new run (protocol 2)
    r1_legacy = TrackerRun(
        user_id=u1.id,
        run_uuid="11111111-0000-0000-0000-000000000001",
        topic="AI Jobs",
        protocol_version=1,
        status="complete",
        report_path=str(dummy_report),
    )
    r2_legacy = TrackerRun(
        user_id=u1.id,
        run_uuid="11111111-0000-0000-0000-000000000002",
        topic="AI Jobs",
        protocol_version=1,
        status="complete",
    )
    r3_new = TrackerRun(
        user_id=u1.id,
        run_uuid="11111111-0000-0000-0000-000000000003",
        topic="AI Jobs",
        protocol_version=2,
        status="complete",
    )
    session.add_all([r1_legacy, r2_legacy, r3_new])
    session.commit()

    # User 1 developments and articles on legacy runs
    d1 = TrackerDevelopment(run_id=r1_legacy.id, rank=1, title="Role 1", company="Co", primary_url="https://a.com")
    d2 = TrackerDevelopment(run_id=r2_legacy.id, rank=1, title="Role 2", company="Co", primary_url="https://b.com")
    a1 = TrackerArticle(run_id=r1_legacy.id, url="https://a.com", status="fetched")
    session.add_all([d1, d2, a1])

    # User 1 development on new run
    d3_new = TrackerDevelopment(run_id=r3_new.id, rank=1, title="Role 3", company="Co", primary_url="https://c.com")
    session.add(d3_new)

    # User 2: 1 legacy run (must NOT be touched when User 1 cleans up)
    u2_legacy = TrackerRun(
        user_id=u2.id,
        run_uuid="22222222-0000-0000-0000-000000000001",
        topic="User 2 topic",
        protocol_version=1,
        status="complete",
    )
    session.add(u2_legacy)
    session.commit()

    session.dummy_report_path = dummy_report  # type: ignore
    session.u1_id = u1.id  # type: ignore
    session.u2_id = u2.id  # type: ignore
    session.r3_new_id = r3_new.id  # type: ignore
    session.u2_legacy_id = u2_legacy.id  # type: ignore

    try:
        yield session
    finally:
        session.close()


def test_preview_legacy_cleanup(db_session):
    """Verify preview accurately counts only selected user's legacy rows."""
    u1_id = db_session.u1_id
    preview = preview_legacy_cleanup(db_session, user_id=u1_id)

    assert isinstance(preview, LegacyCleanupPreview)
    assert preview.user_id == u1_id
    assert preview.legacy_runs_count == 2
    assert preview.developments_count == 2
    assert preview.articles_count == 1
    assert preview.claims_count == 0


def test_execute_legacy_cleanup_isolation_and_preservation(db_session):
    """
    Verify cleanup:
    1. Deletes User 1 legacy runs and dependent items.
    2. Preserves User 1 account.
    3. Preserves User 1 new protocol-2 runs.
    4. Preserves User 2 legacy runs entirely.
    5. Preserves report files on disk.
    """
    u1_id = db_session.u1_id
    u2_id = db_session.u2_id
    r3_new_id = db_session.r3_new_id
    u2_legacy_id = db_session.u2_legacy_id
    report_file = db_session.dummy_report_path

    result = execute_legacy_cleanup(db_session, user_id=u1_id)
    assert isinstance(result, LegacyCleanupResult)
    assert result.user_id == u1_id
    assert result.deleted_runs_count == 2
    assert result.deleted_developments_count == 2
    assert result.deleted_articles_count == 1
    assert result.success is True

    # 1. User 1 has 0 legacy runs left
    u1_legacy_left = db_session.query(TrackerRun).filter_by(user_id=u1_id, protocol_version=1).count()
    assert u1_legacy_left == 0

    # 2. User 1 account is preserved
    user1 = db_session.query(User).filter_by(id=u1_id).one_or_none()
    assert user1 is not None

    # 3. User 1 new protocol-2 run is preserved
    new_run = db_session.query(TrackerRun).filter_by(id=r3_new_id).one_or_none()
    assert new_run is not None
    assert new_run.protocol_version == 2

    # 4. User 2 legacy run is preserved
    u2_run = db_session.query(TrackerRun).filter_by(id=u2_legacy_id).one_or_none()
    assert u2_run is not None
    assert u2_run.protocol_version == 1

    # 5. Report file on disk is untouched
    assert report_file.exists()
    assert report_file.read_text(encoding="utf-8") == "# Old Report Content"


def test_cleanup_repeat_call_safety(db_session):
    """Verify that calling cleanup a second time is safe, idempotent, and reports 0 deleted."""
    u1_id = db_session.u1_id
    result1 = execute_legacy_cleanup(db_session, user_id=u1_id)
    assert result1.deleted_runs_count == 2

    # Second invocation
    result2 = execute_legacy_cleanup(db_session, user_id=u1_id)
    assert result2.deleted_runs_count == 0
    assert result2.deleted_developments_count == 0
    assert result2.deleted_articles_count == 0
    assert result2.success is True


def test_cleanup_rejected_when_active_run_running(db_session):
    """Verify that cleanup is rejected if user currently has an active run."""
    u1_id = db_session.u1_id
    active_run = TrackerRun(
        user_id=u1_id,
        run_uuid="99999999-0000-0000-0000-000000000001",
        topic="Active Run",
        status="running",
        protocol_version=2,
    )
    db_session.add(active_run)
    db_session.commit()

    with pytest.raises(ActiveRunConflictError) as exc_info:
        execute_legacy_cleanup(db_session, user_id=u1_id)
    assert exc_info.value.status_code == 409
    assert "Cannot perform cleanup while a run is actively running" in str(exc_info.value)


def test_cleanup_cli_parser():
    """Verify cleanup CLI argument parser configuration."""
    parser = build_cleanup_parser()

    # Must reject when neither preview nor execute is provided
    with pytest.raises(SystemExit):
        parser.parse_args(["--user-id", "1"])

    # Preview args
    args_prev = parser.parse_args(["--user-id", "1", "--preview"])
    assert args_prev.user_id == 1
    assert args_prev.preview is True
    assert args_prev.execute is False

    # Execute args
    args_exec = parser.parse_args(["--user-id", "2", "--execute"])
    assert args_exec.user_id == 2
    assert args_exec.execute is True
    assert args_prev.execute is False
