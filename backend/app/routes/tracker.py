"""
Tracker API Endpoints.
CSCI-GA.2630 Assignment 1B: Agentic Foundations

Exposes:
- GET /api/tracker/runs        -> List user's execution runs
- GET /api/tracker/runs/:id    -> Get specific execution run
- POST /api/tracker/runs       -> Save run record, top K jobs, and article logs
- POST /api/tracker/trigger    -> Trigger background research execution
- GET /api/tracker/history     -> Historical telemetry summary
- DELETE /api/tracker/runs     -> Reset / clear user's tracker runs

Enforces:
- Rule 2: Strict JWT Bearer authentication (401 for missing/invalid tokens)
- Rule 3: Multi-tenant horizontal isolation (users can only access their own data)
"""

import json
import logging
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import User, TrackerRun, TrackerArticle, TrackerDevelopment
from ..auth import get_current_user, create_access_token
from ..schemas import (
    TrackerRunCreate,
    TrackerRunResponse,
    TrackerTriggerRequest,
    TrackerTriggerResponse,
    TrackerHistorySummary,
)

logger = logging.getLogger("tracker.routes")

router = APIRouter(prefix="/api/tracker", tags=["Tracker"])


def _trigger_tracker_task(
    token: str,
    username: str,
    reset: bool,
    steps_override: Optional[int]
):
    """
    Background worker that runs the autonomous research tracker and syncs
    results back to the backend using the user's authenticated token.
    """
    try:
        from tracker.run import run_tracker
        from ..config import settings
        backend_url = f"http://127.0.0.1:{getattr(settings, 'PORT', 8000)}"
        run_tracker(
            reset=reset,
            steps_override=steps_override,
            username=username,
            backend_url=backend_url,
            skip_login=False,
            token=token
        )
    except Exception as e:
        logger.error(f"Error executing triggered tracker background task: {e}")


@router.get("/runs", response_model=List[TrackerRunResponse])
def get_tracker_runs(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    GET /api/tracker/runs (Protected endpoint)
    Retrieves all research executions for the authenticated user.

    🎯 CRITICAL ENFORCEMENT - RULE 3 (Horizontal Authorization):
    Results are strictly scoped to current_user.id. Users can never view
    another user's tracker run records.
    """
    runs = (
        db.query(TrackerRun)
        .filter(TrackerRun.user_id == current_user.id)
        .order_by(TrackerRun.created_at.desc())
        .all()
    )
    return runs


@router.get("/runs/{run_id}", response_model=TrackerRunResponse)
def get_tracker_run_by_id(
    run_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    GET /api/tracker/runs/:id (Protected endpoint)
    Retrieves a specific run by ID.

    🎯 CRITICAL ENFORCEMENT - RULE 3:
    If the run exists but belongs to another user, consistently returns HTTP 403 Forbidden.
    """
    run = db.query(TrackerRun).filter(TrackerRun.id == run_id).first()
    if not run:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tracker run with ID {run_id} not found"
        )
    if run.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: You cannot access another user's tracker run"
        )
    return run


@router.post("/runs", response_model=TrackerRunResponse, status_code=status.HTTP_201_CREATED)
def create_tracker_run(
    payload: TrackerRunCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    POST /api/tracker/runs (Protected endpoint)
    Records a completed tracker execution along with discovered jobs and article audit logs.

    🎯 CRITICAL ENFORCEMENT - RULE 3:
    If payload specifies a user_id different from current_user.id, returns HTTP 403 Forbidden.
    """
    if payload.user_id is not None and payload.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: You cannot create a tracker run for another user"
        )

    new_run = TrackerRun(
        user_id=current_user.id,
        run_number=payload.run_number,
        topic=payload.topic,
        target_k=payload.target_k,
        status=payload.status,
        step_count=payload.step_count,
        fetch_count=payload.fetch_count,
        tokens_spent=payload.tokens_spent,
        report_path=payload.report_path,
        trace_path=payload.trace_path,
    )
    db.add(new_run)
    db.flush()

    # Persist job developments (supports payload.developments or payload.jobs)
    items = payload.developments or payload.jobs or []
    for idx, item in enumerate(items, 1):
        supp_json = None
        if item.supporting_sources:
            if isinstance(item.supporting_sources, list):
                supp_json = json.dumps(item.supporting_sources)
            elif isinstance(item.supporting_sources, str):
                supp_json = item.supporting_sources

        dev = TrackerDevelopment(
            run_id=new_run.id,
            fingerprint=item.fingerprint,
            rank=item.rank if item.rank is not None else idx,
            title=item.title,
            company=item.company,
            primary_url=item.primary_url or "",
            supporting_sources=supp_json,
            location=item.location,
            compensation=item.compensation,
            qualifications_summary=item.qualifications_summary,
            recrawl_status=item.recrawl_status,
        )
        db.add(dev)

    # Persist article audit logs
    articles = payload.articles or []
    for art in articles:
        art_record = TrackerArticle(
            run_id=new_run.id,
            url=art.url,
            title=art.title,
            status=art.status,
            byte_size=art.byte_size,
            fetch_time_ms=art.fetch_time_ms,
            error_message=art.error_message,
        )
        db.add(art_record)

    db.commit()
    db.refresh(new_run)
    return new_run


@router.post("/trigger", response_model=TrackerTriggerResponse)
def trigger_tracker_run(
    background_tasks: BackgroundTasks,
    payload: Optional[TrackerTriggerRequest] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    POST /api/tracker/trigger (Protected endpoint)
    Triggers an asynchronous tracker execution for the current user.
    """
    last_run = (
        db.query(TrackerRun)
        .filter(TrackerRun.user_id == current_user.id)
        .order_by(TrackerRun.run_number.desc())
        .first()
    )
    is_reset = payload.reset if payload else False
    steps_override = payload.steps_override if payload else None

    next_run = 1 if not last_run or is_reset else last_run.run_number + 1

    # Issue a short-lived token for the background worker to sync back
    worker_token = create_access_token({"sub": str(current_user.id)})

    background_tasks.add_task(
        _trigger_tracker_task,
        token=worker_token,
        username=current_user.username,
        reset=is_reset,
        steps_override=steps_override
    )

    return TrackerTriggerResponse(
        status="triggered",
        message=f"Tracker run {next_run} queued successfully in background",
        run_number=next_run
    )


@router.get("/history", response_model=TrackerHistorySummary)
def get_tracker_history(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    GET /api/tracker/history (Protected endpoint)
    Aggregates execution metrics, totals, and run history for the authenticated user.
    """
    runs = (
        db.query(TrackerRun)
        .filter(TrackerRun.user_id == current_user.id)
        .order_by(TrackerRun.created_at.desc())
        .all()
    )
    total_runs = len(runs)
    last_run = runs[0] if runs else None
    total_steps = sum(r.step_count for r in runs)
    total_fetches = sum(r.fetch_count for r in runs)
    total_tokens = sum(r.tokens_spent for r in runs)

    return TrackerHistorySummary(
        total_runs=total_runs,
        last_run_number=last_run.run_number if last_run else 0,
        last_run_status=last_run.status if last_run else None,
        last_run_at=last_run.created_at if last_run else None,
        total_steps=total_steps,
        total_fetches=total_fetches,
        total_tokens=total_tokens,
        runs=runs
    )


@router.delete("/runs")
def clear_tracker_runs(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    DELETE /api/tracker/runs (Protected endpoint)
    Purges all tracker runs and cascades deletions of associated articles and developments
    strictly for the authenticated user (satisfies --reset policy).
    """
    runs = db.query(TrackerRun).filter(TrackerRun.user_id == current_user.id).all()
    count = len(runs)
    for r in runs:
        db.delete(r)
    db.commit()
    return {
        "status": "ok",
        "message": f"Successfully deleted {count} tracker runs for user '{current_user.username}'"
    }
