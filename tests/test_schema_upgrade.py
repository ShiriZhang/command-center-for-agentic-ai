"""
Unit tests for Task 2.2: Schema Upgrades and Compatible Rollback Checks.
Tests explicit schema upgrades against a representative old Assignment 1B schema fixture.
"""

from datetime import datetime, timezone
import pytest
from sqlalchemy import create_engine, text, inspect
from sqlalchemy.orm import sessionmaker

from backend.app.schema_upgrade import upgrade_schema, check_schema_compatibility, check_rollback_compatibility


OLD_A1B_SCHEMA_DDL = """
CREATE TABLE users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username VARCHAR(50) NOT NULL UNIQUE,
    email VARCHAR(255) NOT NULL UNIQUE,
    hashed_password VARCHAR(255) NOT NULL,
    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL
);

CREATE TABLE tracker_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    run_number INTEGER NOT NULL DEFAULT 1,
    topic VARCHAR(255) NOT NULL,
    target_k INTEGER NOT NULL DEFAULT 10,
    status VARCHAR(50) NOT NULL DEFAULT 'complete',
    step_count INTEGER NOT NULL DEFAULT 0,
    fetch_count INTEGER NOT NULL DEFAULT 0,
    tokens_spent INTEGER NOT NULL DEFAULT 0,
    report_path VARCHAR(512),
    trace_path VARCHAR(512),
    created_at TIMESTAMP NOT NULL
);

CREATE TABLE tracker_articles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL REFERENCES tracker_runs(id) ON DELETE CASCADE,
    url VARCHAR(1024) NOT NULL,
    title VARCHAR(512),
    status VARCHAR(50) NOT NULL,
    byte_size INTEGER DEFAULT 0,
    fetch_time_ms INTEGER DEFAULT 0,
    error_message VARCHAR(1024),
    created_at TIMESTAMP NOT NULL
);

CREATE TABLE tracker_developments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL REFERENCES tracker_runs(id) ON DELETE CASCADE,
    fingerprint VARCHAR(255),
    rank INTEGER NOT NULL,
    title VARCHAR(255) NOT NULL,
    company VARCHAR(255) NOT NULL,
    primary_url VARCHAR(1024) NOT NULL,
    supporting_sources TEXT,
    location VARCHAR(255),
    compensation VARCHAR(255),
    qualifications_summary TEXT,
    recrawl_status VARCHAR(50) NOT NULL DEFAULT 'New since last run',
    created_at TIMESTAMP NOT NULL
);
"""


@pytest.fixture
def old_schema_db():
    """Sets up an in-memory SQLite database mimicking the old Assignment 1B schema and data."""
    engine = create_engine("sqlite:///:memory:", echo=False)
    with engine.connect() as conn:
        for stmt in OLD_A1B_SCHEMA_DDL.strip().split(";"):
            cleaned = stmt.strip()
            if cleaned:
                conn.execute(text(cleaned))
        
        # Insert representative legacy data
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            text("INSERT INTO users (username, email, hashed_password, created_at, updated_at) "
                 "VALUES ('alice', 'alice@nyu.edu', 'hashed_pw', :now, :now)"),
            {"now": now}
        )
        conn.execute(
            text("INSERT INTO tracker_runs (user_id, run_number, topic, target_k, status, step_count, fetch_count, tokens_spent, created_at) "
                 "VALUES (1, 1, 'Top 10 AI Roles', 10, 'complete', 15, 12, 45000, :now)"),
            {"now": now}
        )
        conn.execute(
            text("INSERT INTO tracker_developments (run_id, rank, title, company, primary_url, created_at) "
                 "VALUES (1, 1, 'Research Scientist', 'DeepMind', 'https://deepmind.google/jobs/1', :now)"),
            {"now": now}
        )
        conn.commit()

    return engine


def test_old_schema_fixture_state(old_schema_db):
    """Verify pre-upgrade state lacks Stage 2 columns and tracker_claims table."""
    compat = check_schema_compatibility(old_schema_db)
    assert compat["compatible"] is False
    assert "tracker_claims" in compat["missing_tables"]
    assert "run_uuid" in compat["missing_columns"].get("tracker_runs", [])
    assert "protocol_version" in compat["missing_columns"].get("tracker_runs", [])


def test_upgrade_schema_on_old_fixture(old_schema_db):
    """Verify that upgrade_schema adds all required columns, creates tracker_claims, and preserves legacy data."""
    report = upgrade_schema(old_schema_db)
    assert len(report["added_columns"]) > 0
    assert "tracker_claims" in report["created_tables"]
    assert report["legacy_rows_marked"] == 1

    # Verify compatibility passes after upgrade
    compat = check_schema_compatibility(old_schema_db)
    assert compat["compatible"] is True

    # Inspect database to verify legacy run marked as protocol_version=1 with valid run_uuid
    with old_schema_db.connect() as conn:
        row = conn.execute(text("SELECT id, user_id, protocol_version, run_uuid, reserved_steps FROM tracker_runs WHERE id = 1")).mappings().one()
        assert row["id"] == 1
        assert row["user_id"] == 1
        assert row["protocol_version"] == 1  # Legacy protocol version marker!
        assert len(row["run_uuid"]) == 36    # Populated valid UUID!
        assert row["reserved_steps"] == 0

        # Verify old user is preserved
        user_row = conn.execute(text("SELECT username, email FROM users WHERE id = 1")).mappings().one()
        assert user_row["username"] == "alice"

        # Verify tracker_claims can accept new rows
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            text("INSERT INTO tracker_claims (run_id, development_id, claim_id, text, source_url, verdict, created_at) "
                 "VALUES (1, 1, 'c1', 'Starting salary $180k', 'https://deepmind.google/jobs/1', 'supported', :now)"),
            {"now": now}
        )
        conn.commit()

        claims_count = conn.execute(text("SELECT count(*) FROM tracker_claims")).scalar()
        assert claims_count == 1


def test_upgrade_schema_is_idempotent(old_schema_db):
    """Verify that running upgrade_schema multiple times is safe and makes no unwanted changes."""
    report1 = upgrade_schema(old_schema_db)
    assert len(report1["added_columns"]) > 0

    report2 = upgrade_schema(old_schema_db)
    assert len(report2["added_columns"]) == 0
    assert len(report2["created_tables"]) == 0

    compat = check_schema_compatibility(old_schema_db)
    assert compat["compatible"] is True


def test_rollback_compatibility_check(old_schema_db):
    """Verify that legacy reads continue to function cleanly on upgraded database."""
    upgrade_schema(old_schema_db)
    rollback_status = check_rollback_compatibility(old_schema_db)
    assert rollback_status["compatible"] is True
    assert rollback_status["can_read_legacy_runs"] is True


def test_tracker_claims_run_unique_constraint_enforced_after_upgrade(old_schema_db):
    """Verify tracker_claims table created by upgrade_schema enforces (run_id, claim_id) uniqueness."""
    upgrade_schema(old_schema_db)
    now = datetime.now(timezone.utc).isoformat()
    with old_schema_db.connect() as conn:
        conn.execute(
            text("INSERT INTO tracker_claims (run_id, development_id, claim_id, text, source_url, verdict, created_at) "
                 "VALUES (1, 1, 'claim-dup', 'Text 1', 'https://a.com', 'supported', :now)"),
            {"now": now}
        )
        conn.commit()

        # Duplicate claim_id on same run_id must raise error
        with pytest.raises(Exception):
            conn.execute(
                text("INSERT INTO tracker_claims (run_id, development_id, claim_id, text, source_url, verdict, created_at) "
                     "VALUES (1, 1, 'claim-dup', 'Text 2', 'https://a.com', 'unsupported', :now)"),
                {"now": now}
            )
            conn.commit()
