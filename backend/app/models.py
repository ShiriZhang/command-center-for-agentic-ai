from datetime import datetime, timezone
from typing import Optional
import uuid
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text, Boolean, UniqueConstraint
from sqlalchemy.orm import relationship
from .database import Base


class User(Base):
    """
    SQLAlchemy ORM Model mapping to the 'users' physical table in the database.
    Represents the database storage structure for user accounts.
    """
    __tablename__ = "users"

    # Primary key: Auto-incrementing unique integer ID (indexed for O(1) lookups)
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)

    # Unique credentials: username and email are indexed for high-speed lookups during login/register
    username = Column(String(50), unique=True, index=True, nullable=False)
    email = Column(String(255), unique=True, index=True, nullable=False)

    # Security attribute: Never stores plain password; stores the 60-character bcrypt hash string
    hashed_password = Column(String(255), nullable=False)

    # Audit timestamps: Track account lifecycle using UTC timezone to eliminate daylight savings ambiguities
    created_at = Column(
        DateTime, 
        default=lambda: datetime.now(timezone.utc), 
        nullable=False
    )
    updated_at = Column(
        DateTime, 
        default=lambda: datetime.now(timezone.utc), 
        onupdate=lambda: datetime.now(timezone.utc), 
        nullable=False
    )

    # Cascade relationship: Deleting a user automatically purges all their tracker research runs
    tracker_runs = relationship(
        "TrackerRun",
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True
    )


class TrackerRun(Base):
    """
    Represents an autonomous research tracker execution.
    Scoped strictly to an authenticated User (A1 Rule 3 authorization boundary).
    """
    __tablename__ = "tracker_runs"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    run_uuid = Column(
        String(36),
        unique=True,
        index=True,
        nullable=False,
        default=lambda: str(uuid.uuid4())
    )
    run_number = Column(Integer, nullable=False, default=1)
    protocol_version = Column(Integer, nullable=False, default=2, index=True)
    reset_generation = Column(Integer, nullable=False, default=0, index=True)
    is_baseline_eligible = Column(Boolean, nullable=False, default=False)

    topic = Column(String(255), nullable=False)
    target_k = Column(Integer, nullable=False, default=10)
    status = Column(String(50), nullable=False, default="complete")

    researcher_status = Column(String(50), nullable=True)
    verifier_status = Column(String(50), nullable=True)
    researcher_error = Column(Text, nullable=True)
    verifier_error = Column(Text, nullable=True)
    researcher_request_id = Column(String(36), nullable=True)
    verifier_request_id = Column(String(36), nullable=True)

    reserved_steps = Column(Integer, nullable=False, default=0)
    reserved_fetches = Column(Integer, nullable=False, default=0)
    reserved_tokens = Column(Integer, nullable=False, default=0)

    measured_steps = Column(Integer, nullable=False, default=0)
    measured_fetches = Column(Integer, nullable=False, default=0)
    measured_tokens = Column(Integer, nullable=False, default=0)

    charged_steps = Column(Integer, nullable=False, default=0)
    charged_fetches = Column(Integer, nullable=False, default=0)
    charged_tokens = Column(Integer, nullable=False, default=0)

    step_count = Column(Integer, nullable=False, default=0)
    fetch_count = Column(Integer, nullable=False, default=0)
    tokens_spent = Column(Integer, nullable=False, default=0)

    stale_source_run_id = Column(
        Integer,
        ForeignKey("tracker_runs.id", ondelete="SET NULL"),
        nullable=True
    )
    stale_source_run_uuid = Column(String(36), nullable=True)

    report_path = Column(String(512), nullable=True)
    trace_path = Column(String(512), nullable=True)
    created_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False
    )

    # Self-referential relationship for stale baseline origin
    stale_source_run = relationship(
        "TrackerRun",
        remote_side=[id],
        foreign_keys=[stale_source_run_id],
        uselist=False,
    )

    @property
    def stale_source_created_at(self) -> Optional[datetime]:
        if self.stale_source_run:
            return self.stale_source_run.created_at
        return None

    # Relationships
    user = relationship("User", back_populates="tracker_runs")
    articles = relationship(
        "TrackerArticle",
        back_populates="run",
        cascade="all, delete-orphan",
        passive_deletes=True
    )
    developments = relationship(
        "TrackerDevelopment",
        back_populates="run",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="TrackerDevelopment.rank"
    )
    claims = relationship(
        "TrackerClaim",
        back_populates="run",
        cascade="all, delete-orphan",
        passive_deletes=True
    )


class TrackerArticle(Base):
    """
    Audit log of web articles inspected during an execution run.
    Records SSRF guardrail validation status, payload byte size, and socket latency.
    """
    __tablename__ = "tracker_articles"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    run_id = Column(
        Integer,
        ForeignKey("tracker_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    url = Column(String(1024), nullable=False)
    title = Column(String(512), nullable=True)
    status = Column(String(50), nullable=False)  # "fetched", "rejected", "error"
    byte_size = Column(Integer, default=0)
    fetch_time_ms = Column(Integer, default=0)
    error_message = Column(String(1024), nullable=True)
    created_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False
    )

    # Relationship
    run = relationship("TrackerRun", back_populates="articles")


class TrackerDevelopment(Base):
    """
    Canonical Top K job openings synthesized in a tracker run.
    Maintains verified provenance links and multi-run differential status badges.
    """
    __tablename__ = "tracker_developments"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    run_id = Column(
        Integer,
        ForeignKey("tracker_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    fingerprint = Column(String(255), index=True, nullable=True)
    rank = Column(Integer, nullable=False)
    title = Column(String(255), nullable=False)
    company = Column(String(255), nullable=False)
    primary_url = Column(String(1024), nullable=False)
    supporting_sources = Column(Text, nullable=True)  # JSON string of secondary URLs
    location = Column(String(255), nullable=True)
    compensation = Column(String(255), nullable=True)
    qualifications_summary = Column(Text, nullable=True)
    recrawl_status = Column(
        String(50),
        nullable=False,
        default="New since last run"
    )  # "New since last run", "Still in top K", "Dropped"
    created_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False
    )

    # Relationships
    run = relationship("TrackerRun", back_populates="developments")
    claims = relationship(
        "TrackerClaim",
        back_populates="development",
        cascade="all, delete-orphan",
        passive_deletes=True
    )


class TrackerClaim(Base):
    """
    Atomic cited claim discovered by Researcher and verified by Verifier.
    Cascades on development or run deletion.
    """
    __tablename__ = "tracker_claims"
    __table_args__ = (
        UniqueConstraint("run_id", "claim_id", name="uq_tracker_claims_run_claim"),
    )

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    run_id = Column(
        Integer,
        ForeignKey("tracker_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    development_id = Column(
        Integer,
        ForeignKey("tracker_developments.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    claim_id = Column(String(255), nullable=False, index=True)
    text = Column(Text, nullable=False)
    source_url = Column(String(1024), nullable=False)
    verdict = Column(String(50), nullable=False, default="unverified")  # "supported", "unsupported", "unreachable", "unverified"
    evidence = Column(Text, nullable=True)
    created_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False
    )

    # Relationships
    development = relationship("TrackerDevelopment", back_populates="claims")
    run = relationship("TrackerRun", back_populates="claims")
