"""
Run Admission and Lifecycle Control.
Ensures exactly one active running run per user using atomic database-backed checks,
assigns sequential per-user run numbers, and protects against concurrent duplicate triggers.
CSCI-GA.2630 Assignment 2
"""

from datetime import datetime, timezone
import threading
from typing import Dict
from uuid import uuid4
from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.app.models import TrackerRun


class ActiveRunConflictError(Exception):
    """Raised when attempting to trigger a new run while another run is actively running (HTTP 409)."""

    status_code: int = 409

    def __init__(self, message: str, user_id: int, active_run_uuid: str):
        super().__init__(message)
        self.user_id = user_id
        self.active_run_uuid = active_run_uuid


_registry_lock = threading.Lock()
_user_locks: Dict[int, threading.Lock] = {}


def _get_user_lock(user_id: int) -> threading.Lock:
    with _registry_lock:
        if user_id not in _user_locks:
            _user_locks[user_id] = threading.Lock()
        return _user_locks[user_id]


def admit_user_run(
    db: Session,
    user_id: int,
    topic: str,
    target_k: int,
    reset_generation: int = 0,
) -> TrackerRun:
    """
    Atomically admits a new run for the given user.
    - If user already has a run with status='running', raises ActiveRunConflictError (HTTP 409).
    - Otherwise assigns next per-user run_number, sets status='running', protocol_version=2,
      persists the record, and returns the admitted TrackerRun.
    """
    user_lock = _get_user_lock(user_id)
    with user_lock:
        query = db.query(TrackerRun).filter(TrackerRun.user_id == user_id, TrackerRun.status == "running")
        bind = db.get_bind()
        if bind is not None and bind.dialect.name == "postgresql":
            query = query.with_for_update()

        active_run = query.first()
        if active_run:
            raise ActiveRunConflictError(
                f"User {user_id} already has an active run {active_run.run_uuid}",
                user_id=user_id,
                active_run_uuid=str(active_run.run_uuid),
            )

        max_run_number = (
            db.query(func.coalesce(func.max(TrackerRun.run_number), 0))
            .filter(TrackerRun.user_id == user_id)
            .scalar()
            or 0
        )
        next_run_number = int(max_run_number) + 1

        now = datetime.now(timezone.utc)
        new_run = TrackerRun(
            user_id=user_id,
            run_uuid=str(uuid4()),
            run_number=next_run_number,
            topic=topic,
            target_k=target_k,
            status="running",
            protocol_version=2,
            reset_generation=reset_generation,
            is_baseline_eligible=False,
            created_at=now,
        )
        db.add(new_run)
        db.commit()
        db.refresh(new_run)
        return new_run
