from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, DateTime
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
