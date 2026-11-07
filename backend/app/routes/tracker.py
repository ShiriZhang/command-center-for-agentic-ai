"""
Tracker API Endpoints.
Coordinates authenticated queries, baseline reset, history deletion,
and triggers backend orchestration lifecycles.
CSCI-GA.2630 Assignment 2
"""

import json
import logging
from typing import Any, List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..database import SessionLocal, get_db
from ..models import TrackerArticle, TrackerDevelopment, TrackerRun, User
from ..auth import get_current_user
from ..orchestration.admission import ActiveRunConflictError, admit_user_run
from ..schemas import (
    TrackerHistorySummary,
    TrackerRunResponse,
    TrackerTriggerRequest,
    TrackerTriggerResponse,
)

logger = logging.getLogger("tracker.routes")

router = APIRouter(prefix="/api/tracker", tags=["Tracker"])


def _run_lifecycle_in_background(run_id: int, steps_override: Optional[int] = None):
    """Executes backend orchestration in a background worker thread."""
    db: Session = SessionLocal()
    try:
        from ..orchestration.lifecycle import execute_orchestration_lifecycle
        from ..orchestration.dispatch import WorkerDispatcher
        from ..orchestration.telemetry import default_orchestrator_logger
        from shared.config import split_step_budget

        dispatcher = None
        if steps_override is not None:
            budgets = split_step_budget(steps_override)
            dispatcher = WorkerDispatcher(budgets=budgets, telemetry_logger=default_orchestrator_logger)

        execute_orchestration_lifecycle(db=db, run_id=run_id, dispatcher=dispatcher)
    except Exception as e:
        logger.error(f"Error in background orchestration run {run_id}: {e}")
    finally:
        db.close()


@router.get("/runs", response_model=List[TrackerRunResponse])
def get_tracker_runs(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    GET /api/tracker/runs (Protected endpoint)
    Retrieves all research executions for the authenticated user strictly isolated.
    """
    user_any: Any = current_user
    u_id: int = user_any.id
    runs = (
        db.query(TrackerRun)
        .filter(TrackerRun.user_id == u_id)
        .order_by(TrackerRun.created_at.desc())
        .all()
    )
    return [TrackerRunResponse.model_validate(r) for r in runs]


@router.get("/runs/{run_id}", response_model=TrackerRunResponse)
def get_tracker_run_by_id(
    run_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    GET /api/tracker/runs/:id (Protected endpoint)
    Retrieves a specific run by ID with strict horizontal isolation (403 for other users).
    """
    user_any: Any = current_user
    u_id: int = user_any.id
    run = db.query(TrackerRun).filter(TrackerRun.id == run_id).first()
    if not run:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tracker run with ID {run_id} not found",
        )
    run_any: Any = run
    if int(run_any.user_id) != u_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: You cannot access another user's tracker run",
        )
    return TrackerRunResponse.model_validate(run)


@router.post("/runs")
def create_tracker_run():
    """
    POST /api/tracker/runs (Removed - Spec 5.8)
    Public run ingestion is prohibited to prevent external clients from fabricating runs.
    Use POST /api/tracker/trigger to orchestrate runs through the backend.
    """
    raise HTTPException(
        status_code=status.HTTP_405_METHOD_NOT_ALLOWED,
        detail="Public run ingestion is removed. Use POST /api/tracker/trigger to orchestrate runs.",
    )


@router.post("/trigger", response_model=TrackerTriggerResponse, status_code=status.HTTP_202_ACCEPTED)
def trigger_tracker_run(
    background_tasks: BackgroundTasks,
    payload: Optional[TrackerTriggerRequest] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    POST /api/tracker/trigger (Protected endpoint)
    Admits a new run and triggers backend orchestration lifecycle in the background.
    Rejects with HTTP 409 Conflict if another run is actively running.
    """
    user_any: Any = current_user
    u_id: int = user_any.id
    is_reset = payload.reset if payload else False
    steps_override = payload.steps_override if payload else None
    if steps_override is not None:
        from shared.config import load_orchestration_config
        orch_cfg = load_orchestration_config()
        if steps_override < 2 or steps_override > orch_cfg.budgets.total.max_steps:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"steps_override ({steps_override}) must be at least 2 and cannot exceed total configured allowance ({orch_cfg.budgets.total.max_steps}).",
            )

    topic = "Top 10 newest entry-level and new grad AI/ML engineering roles"
    target_k = 10

    max_gen = (
        db.query(func.coalesce(func.max(TrackerRun.reset_generation), 0))
        .filter(TrackerRun.user_id == u_id)
        .scalar()
        or 0
    )
    reset_generation = int(max_gen) + (1 if is_reset else 0)

    try:
        admitted = admit_user_run(
            db=db,
            user_id=u_id,
            topic=topic,
            target_k=target_k,
            reset_generation=reset_generation,
        )
    except ActiveRunConflictError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Conflict: Active run {e.active_run_uuid} already running",
        )

    admitted_any: Any = admitted
    from ..orchestration.telemetry import default_orchestrator_logger

    default_orchestrator_logger.log_event(
        service="orchestrator",
        run_id=str(admitted_any.run_uuid),
        request_id=str(admitted_any.run_uuid),
        step=0,
        direction="inbound",
        endpoint_or_tool="/api/tracker/trigger",
        status="admitted",
        latency_ms=0.0,
    )

    background_tasks.add_task(
        _run_lifecycle_in_background,
        int(admitted_any.id),
        steps_override=steps_override,
    )

    return TrackerTriggerResponse(
        status="triggered",
        message=f"Tracker run {admitted_any.run_number} queued successfully in background",
        run_number=int(admitted_any.run_number),
        run_id=int(admitted_any.id),
        run_uuid=str(admitted_any.run_uuid),
    )


@router.post("/reset")
def reset_tracker_baseline(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    POST /api/tracker/reset (Protected endpoint - Spec 5.9)
    Starts a new scoped baseline comparison lineage by incrementing reset_generation.
    Rejects with HTTP 409 Conflict if an active run exists.
    Preserves historical runs intact.
    """
    user_any: Any = current_user
    u_id: int = user_any.id
    active_run = (
        db.query(TrackerRun)
        .filter(TrackerRun.user_id == u_id, TrackerRun.status == "running")
        .first()
    )
    if active_run:
        run_any: Any = active_run
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Conflict: Cannot reset baseline while active run {run_any.run_uuid} is running",
        )

    # Invalidate baseline eligibility for all prior runs of this user
    db.query(TrackerRun).filter(
        TrackerRun.user_id == u_id,
        TrackerRun.is_baseline_eligible == True,  # noqa: E712
    ).update({TrackerRun.is_baseline_eligible: False})
    db.commit()

    max_gen = (
        db.query(func.coalesce(func.max(TrackerRun.reset_generation), 0))
        .filter(TrackerRun.user_id == u_id)
        .scalar()
        or 0
    )
    next_gen = int(max_gen) + 1
    return {
        "status": "ok",
        "reset_generation": next_gen,
        "message": f"Baseline reset successfully for user '{user_any.username}'. History preserved.",
    }


@router.get("/history", response_model=TrackerHistorySummary)
def get_tracker_history(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    GET /api/tracker/history (Protected endpoint)
    Aggregates execution metrics, totals, and run history for the authenticated user.
    """
    user_any: Any = current_user
    u_id: int = user_any.id
    runs = (
        db.query(TrackerRun)
        .filter(TrackerRun.user_id == u_id)
        .order_by(TrackerRun.created_at.desc())
        .all()
    )
    total_runs = len(runs)
    last_run_any: Any = runs[0] if runs else None
    total_steps = sum(int(getattr(r, "step_count", 0) or 0) for r in runs)
    total_fetches = sum(int(getattr(r, "fetch_count", 0) or 0) for r in runs)
    total_tokens = sum(int(getattr(r, "tokens_spent", 0) or 0) for r in runs)
    runs_payload = [TrackerRunResponse.model_validate(r) for r in runs]

    return TrackerHistorySummary(
        total_runs=total_runs,
        last_run_number=int(last_run_any.run_number) if last_run_any else 0,
        last_run_status=str(last_run_any.status) if last_run_any and last_run_any.status else None,
        last_run_at=last_run_any.created_at if last_run_any else None,
        total_steps=total_steps,
        total_fetches=total_fetches,
        total_tokens=total_tokens,
        runs=runs_payload,
    )


@router.delete("/runs")
def clear_tracker_runs(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    DELETE /api/tracker/runs (Protected endpoint - Spec 5.9)
    Purges all tracker runs strictly for the authenticated user.
    Rejects with HTTP 409 Conflict if an active run exists.
    Clears baseline pointers and cascades dependent records.
    """
    user_any: Any = current_user
    u_id: int = user_any.id
    active_run = (
        db.query(TrackerRun)
        .filter(TrackerRun.user_id == u_id, TrackerRun.status == "running")
        .first()
    )
    if active_run:
        run_any: Any = active_run
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Conflict: Cannot delete history while active run {run_any.run_uuid} is running",
        )

    # Clear baseline pointers first to satisfy foreign key constraints
    db.query(TrackerRun).filter(TrackerRun.user_id == u_id).update(
        {TrackerRun.stale_source_run_id: None, TrackerRun.stale_source_run_uuid: None}
    )
    db.flush()

    runs = db.query(TrackerRun).filter(TrackerRun.user_id == u_id).all()
    count = len(runs)
    for r in runs:
        db.delete(r)
    db.commit()
    return {
        "status": "ok",
        "message": f"Successfully deleted {count} tracker runs for user '{user_any.username}'",
    }
