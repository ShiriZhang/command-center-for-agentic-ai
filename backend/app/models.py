from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text
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
    run_number = Column(Integer, nullable=False, default=1)
    topic = Column(String(255), nullable=False)
    target_k = Column(Integer, nullable=False, default=10)
    status = Column(String(50), nullable=False, default="complete")  # "complete", "partial", "error"
    step_count = Column(Integer, nullable=False, default=0)
    fetch_count = Column(Integer, nullable=False, default=0)
    tokens_spent = Column(Integer, nullable=False, default=0)
    report_path = Column(String(512), nullable=True)
    trace_path = Column(String(512), nullable=True)
    created_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False
    )

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

    # Relationship
    run = relationship("TrackerRun", back_populates="developments")
