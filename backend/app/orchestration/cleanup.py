"""
Selected-User Legacy Cleanup.
Provides preview and transactional deletion of an account's legacy tracker data (protocol_version = 1),
preserving user accounts, new protocol runs, other users' data, and report files.
CSCI-GA.2630 Assignment 2
"""

from typing import List, Optional
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from backend.app.models import TrackerRun, TrackerDevelopment, TrackerArticle, TrackerClaim
from backend.app.orchestration.admission import ActiveRunConflictError


class LegacyCleanupPreview(BaseModel):
    """Preview summary of legacy rows eligible for cleanup."""

    model_config = ConfigDict(strict=True)

    user_id: int
    legacy_runs_count: int
    developments_count: int
    articles_count: int
    claims_count: int


class LegacyCleanupResult(BaseModel):
    """Execution outcome of transactional legacy cleanup."""

    model_config = ConfigDict(strict=True)

    user_id: int
    deleted_runs_count: int
    deleted_developments_count: int
    deleted_articles_count: int
    deleted_claims_count: int
    success: bool


def preview_legacy_cleanup(db: Session, user_id: int) -> LegacyCleanupPreview:
    """
    Previews row counts of legacy tracker data (protocol_version = 1) for the selected user.
    Does not delete or alter any records.
    """
    legacy_run_ids: List[int] = [
        r.id
        for r in db.query(TrackerRun.id)
        .filter(TrackerRun.user_id == user_id, TrackerRun.protocol_version == 1)
        .all()
    ]

    runs_count = len(legacy_run_ids)
    if runs_count == 0:
        return LegacyCleanupPreview(
            user_id=user_id,
            legacy_runs_count=0,
            developments_count=0,
            articles_count=0,
            claims_count=0,
        )

    devs_count = (
        db.query(TrackerDevelopment)
        .filter(TrackerDevelopment.run_id.in_(legacy_run_ids))
        .count()
    )
    articles_count = (
        db.query(TrackerArticle)
        .filter(TrackerArticle.run_id.in_(legacy_run_ids))
        .count()
    )
    claims_count = (
        db.query(TrackerClaim)
        .filter(TrackerClaim.run_id.in_(legacy_run_ids))
        .count()
    )

    return LegacyCleanupPreview(
        user_id=user_id,
        legacy_runs_count=runs_count,
        developments_count=devs_count,
        articles_count=articles_count,
        claims_count=claims_count,
    )


def execute_legacy_cleanup(db: Session, user_id: int) -> LegacyCleanupResult:
    """
    Transactionally purges only the selected user's legacy tracker rows (protocol_version = 1).
    - Rejects operation if the user currently has an active running run.
    - Preserves user account, other users' data, new protocol runs, and report files on disk.
    - Repeat-call safe (idempotent).
    """
    active_run = (
        db.query(TrackerRun)
        .filter(TrackerRun.user_id == user_id, TrackerRun.status == "running")
        .first()
    )
    if active_run:
        raise ActiveRunConflictError(
            f"Cannot perform cleanup while a run is actively running: {active_run.run_uuid}",
            user_id=user_id,
            active_run_uuid=str(active_run.run_uuid),
        )

    preview = preview_legacy_cleanup(db, user_id)
    if preview.legacy_runs_count == 0:
        return LegacyCleanupResult(
            user_id=user_id,
            deleted_runs_count=0,
            deleted_developments_count=0,
            deleted_articles_count=0,
            deleted_claims_count=0,
            success=True,
        )

    legacy_runs = (
        db.query(TrackerRun)
        .filter(TrackerRun.user_id == user_id, TrackerRun.protocol_version == 1)
        .all()
    )
    for run in legacy_runs:
        db.delete(run)

    db.commit()

    return LegacyCleanupResult(
        user_id=user_id,
        deleted_runs_count=preview.legacy_runs_count,
        deleted_developments_count=preview.developments_count,
        deleted_articles_count=preview.articles_count,
        deleted_claims_count=preview.claims_count,
        success=True,
    )


def build_cleanup_parser():
    import argparse
    parser = argparse.ArgumentParser(description="Selected-User Legacy Cleanup CLI")
    parser.add_argument("--user-id", type=int, required=True, help="Target user ID for legacy cleanup")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--preview", action="store_true", help="Preview legacy rows eligible for cleanup")
    mode.add_argument("--execute", action="store_true", help="Execute transactional deletion of legacy rows")
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    from backend.app.database import SessionLocal
    parser = build_cleanup_parser()
    args = parser.parse_args(argv)

    db = SessionLocal()
    try:
        if args.preview:
            preview = preview_legacy_cleanup(db, args.user_id)
            print(f"Legacy Cleanup Preview for user {args.user_id}:")
            print(f"  Runs: {preview.legacy_runs_count}")
            print(f"  Developments: {preview.developments_count}")
            print(f"  Articles: {preview.articles_count}")
            print(f"  Claims: {preview.claims_count}")
        elif args.execute:
            result = execute_legacy_cleanup(db, args.user_id)
            print(f"Legacy Cleanup Executed for user {args.user_id}:")
            print(f"  Deleted runs: {result.deleted_runs_count}")
            print(f"  Deleted developments: {result.deleted_developments_count}")
            print(f"  Deleted articles: {result.deleted_articles_count}")
            print(f"  Deleted claims: {result.deleted_claims_count}")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    import sys
    sys.exit(main())
