"""
Backend Orchestration Lifecycle.
Coordinates admission, researcher dispatch, verifier dispatch, verdict mapping,
multi-run diffing, baseline scoping/promotion, and stale fallback.
CSCI-GA.2630 Assignment 2
"""

from datetime import datetime, timezone
import time
from typing import Any, List, Optional
from uuid import UUID, uuid4
from sqlalchemy.orm import Session

from shared.contracts import (
    ResearchResponse,
    VerifyClaimInput,
    VerifyResponse,
)
from backend.app.models import (
    TrackerArticle,
    TrackerClaim,
    TrackerDevelopment,
    TrackerRun,
)
from pathlib import Path
from backend.app.orchestration.accounting import (
    record_researcher_reservation,
    record_verifier_reservation,
    settle_researcher_charge,
    settle_verifier_charge,
)
from backend.app.orchestration.dispatch import WorkerDispatcher
from backend.app.orchestration.report import save_report_artifacts
from backend.app.orchestration.telemetry import default_orchestrator_logger


def find_matching_baseline(
    db: Session,
    user_id: int,
    topic: str,
    target_k: int,
    reset_generation: int,
    current_run_id: int,
) -> Optional[TrackerRun]:
    """
    Finds the most recent baseline-eligible run in the exact user/topic/target_k/reset_generation scope.
    """
    return (
        db.query(TrackerRun)
        .filter(
            TrackerRun.user_id == user_id,
            TrackerRun.topic == topic,
            TrackerRun.target_k == target_k,
            TrackerRun.reset_generation == reset_generation,
            TrackerRun.is_baseline_eligible == True,  # noqa: E712
            TrackerRun.id != current_run_id,
        )
        .order_by(TrackerRun.created_at.desc(), TrackerRun.id.desc())
        .first()
    )


def compute_development_badges(
    current_devs: List[TrackerDevelopment],
    baseline: Optional[TrackerRun],
    researcher_status: str,
) -> None:
    """
    Computes multi-run differential status badges:
    - 'New since last run'
    - 'Still in top K'
    - 'Dropped' (only generated when researcher status is complete)
    Partial research never generates false Dropped badges.
    """
    if baseline is None or not baseline.developments:
        for dev in current_devs:
            r_dev: Any = dev
            r_dev.recrawl_status = "New since last run"
        return

    baseline_fps = {
        (d.fingerprint or f"{d.company}:{d.title}").strip().lower()
        for d in baseline.developments
    }

    current_fps = set()
    for dev in current_devs:
        r_dev: Any = dev
        dev_fp = (dev.fingerprint or f"{dev.company}:{dev.title}").strip().lower()
        current_fps.add(dev_fp)
        if dev_fp in baseline_fps:
            r_dev.recrawl_status = "Still in top K"
        else:
            r_dev.recrawl_status = "New since last run"

    # Only complete research generates Dropped positions from previous baseline
    if researcher_status == "complete":
        dropped_b_devs = [
            b_dev for b_dev in baseline.developments
            if (b_dev.fingerprint or f"{b_dev.company}:{b_dev.title}").strip().lower() not in current_fps
        ]
        next_rank = len(current_devs) + 1
        for b_dev in dropped_b_devs:
            dropped_dev = TrackerDevelopment(
                run_id=current_devs[0].run_id if current_devs else baseline.id,
                rank=next_rank,
                title=b_dev.title,
                company=b_dev.company,
                primary_url=b_dev.primary_url,
                fingerprint=b_dev.fingerprint,
                location=b_dev.location,
                compensation=b_dev.compensation,
                qualifications_summary=b_dev.qualifications_summary,
                recrawl_status="Dropped",
            )
            current_devs.append(dropped_dev)
            next_rank += 1


def execute_orchestration_lifecycle(
    db: Session,
    run_id: int,
    dispatcher: Optional[WorkerDispatcher] = None,
) -> TrackerRun:
    """
    Executes the end-to-end orchestration pipeline for an admitted run:
    1. Researcher reservation & HTTP dispatch
    2. Researcher response validation & DB persistence (developments, claims, articles)
    3. Verifier reservation & HTTP dispatch
    4. Verdict mapping (unreturned claims become unverified)
    5. Baseline scoping & promotion (only complete research promotes)
    6. Multi-run diffing & stale fallback if researcher fails
    """
    run = db.query(TrackerRun).filter(TrackerRun.id == run_id).first()
    if not run:
        raise ValueError(f"TrackerRun {run_id} not found")

    r_run: Any = run
    if r_run.status != "running":
        return run

    disp = dispatcher or WorkerDispatcher(telemetry_logger=default_orchestrator_logger)
    start_run_time = time.monotonic()
    run_uuid_obj = UUID(str(r_run.run_uuid))

    default_orchestrator_logger.log_event(
        service="orchestrator",
        run_id=str(r_run.run_uuid),
        request_id=str(r_run.run_uuid),
        step=0,
        direction="inbound",
        endpoint_or_tool="lifecycle:execute",
        status="started",
        latency_ms=0.0,
    )

    # --- Step 1: Researcher Reservation & Dispatch ---
    res_req_id = uuid4()
    record_researcher_reservation(run, req_id=res_req_id, budget=disp.budgets.researcher)
    db.commit()

    res_result = disp.dispatch_research(
        run_id=run_uuid_obj,
        topic=str(r_run.topic),
        k=int(r_run.target_k),
        start_run_time=start_run_time,
        request_id=res_req_id,
    )

    settle_researcher_charge(
        run,
        usage=res_result.measured_usage,
        budget=disp.budgets.researcher,
        success=res_result.success,
    )
    db.commit()

    # --- Step 2: Handle Researcher Failure or Success ---
    if not res_result.success or res_result.response is None:
        r_run.researcher_status = "failed"
        r_run.researcher_error = res_result.error_message or res_result.error_code
        r_run.verifier_status = "skipped"
        r_run.status = "partial"
        r_run.is_baseline_eligible = False

        # Check for matching baseline fallback
        baseline = find_matching_baseline(
            db=db,
            user_id=int(r_run.user_id),
            topic=str(r_run.topic),
            target_k=int(r_run.target_k),
            reset_generation=int(r_run.reset_generation),
            current_run_id=int(r_run.id),
        )

        if baseline:
            r_run.stale_source_run_id = baseline.id
            r_run.stale_source_run_uuid = baseline.run_uuid

            for b_dev in baseline.developments:
                new_dev = TrackerDevelopment(
                    run_id=run.id,
                    rank=b_dev.rank,
                    title=b_dev.title,
                    company=b_dev.company,
                    primary_url=b_dev.primary_url,
                    fingerprint=b_dev.fingerprint,
                    location=b_dev.location,
                    compensation=b_dev.compensation,
                    qualifications_summary=b_dev.qualifications_summary,
                    recrawl_status="Still in top K",
                )
                db.add(new_dev)
                db.flush()

                for b_claim in b_dev.claims:
                    new_claim = TrackerClaim(
                        run_id=run.id,
                        development_id=new_dev.id,
                        claim_id=b_claim.claim_id,
                        text=b_claim.text,
                        source_url=b_claim.source_url,
                        verdict=b_claim.verdict,
                        evidence=b_claim.evidence,
                    )
                    db.add(new_claim)

        try:
            md_p, _ = save_report_artifacts(run)
            r_run.report_path = str(md_p)
        except Exception:
            r_run.report_path = f"reports/run_{r_run.run_uuid}.md"

        default_orchestrator_logger.log_event(
            service="orchestrator",
            run_id=str(r_run.run_uuid),
            request_id=str(r_run.run_uuid),
            step=0,
            direction="outbound",
            endpoint_or_tool="lifecycle:execute",
            status=str(r_run.status),
            latency_ms=(time.monotonic() - start_run_time) * 1000.0,
        )
        trace_path = Path(f"reports/trace_{r_run.run_uuid}.jsonl")
        default_orchestrator_logger.export_run_traces(str(r_run.run_uuid), trace_path)
        r_run.trace_path = str(trace_path)

        db.commit()
        db.refresh(run)
        return run

    # Researcher succeeded (complete or partial)
    res_resp: ResearchResponse = res_result.response
    r_run.researcher_status = res_resp.status
    if res_resp.error:
        r_run.researcher_error = res_resp.error.message

    # Persist developments & claims
    assert res_resp.result is not None
    for idx, dev in enumerate(res_resp.result.developments, start=1):
        primary_url = dev.primary_url or (dev.claims[0].source_url if dev.claims else "https://example.com")
        company = dev.company or "Unknown Company"
        fp = dev.fingerprint or f"{company}:{dev.title}"

        new_dev = TrackerDevelopment(
            run_id=run.id,
            rank=idx,
            title=dev.title,
            company=company,
            primary_url=primary_url,
            fingerprint=fp,
            location=dev.location,
            compensation=dev.compensation,
            qualifications_summary=dev.qualifications_summary,
            recrawl_status="New since last run",
        )
        db.add(new_dev)
        db.flush()

        for claim in dev.claims:
            new_claim = TrackerClaim(
                run_id=run.id,
                development_id=new_dev.id,
                claim_id=claim.claim_id,
                text=claim.text,
                source_url=claim.source_url,
                verdict="unverified",
                evidence=None,
            )
            db.add(new_claim)

    if res_resp.result.articles:
        for art in res_resp.result.articles:
            new_art = TrackerArticle(
                run_id=run.id,
                url=art.source_url,
                title=art.title,
                status=art.status,
                fetch_time_ms=int(art.latency_ms or 0),
                error_message=art.error,
            )
            db.add(new_art)

    db.commit()

    # --- Step 3: Verifier Stage ---
    all_claims = db.query(TrackerClaim).filter(TrackerClaim.run_id == run.id).all()
    claims_to_verify = [
        VerifyClaimInput(claim_id=str(c.claim_id), text=str(c.text), source_url=str(c.source_url))
        for c in all_claims
    ]

    if not claims_to_verify:
        r_run.verifier_status = "skipped"
    else:
        ver_req_id = uuid4()
        record_verifier_reservation(run, req_id=ver_req_id, budget=disp.budgets.verifier)
        db.commit()

        ver_result = disp.dispatch_verify(
            run_id=run_uuid_obj,
            claims=claims_to_verify,
            start_run_time=start_run_time,
            request_id=ver_req_id,
        )

        settle_verifier_charge(
            run,
            usage=ver_result.measured_usage,
            budget=disp.budgets.verifier,
            success=ver_result.success,
        )
        db.commit()

        if not ver_result.success or ver_result.response is None:
            r_run.verifier_status = "failed"
            r_run.verifier_error = ver_result.error_message or ver_result.error_code
            # Claims remain unverified
        else:
            ver_resp: VerifyResponse = ver_result.response
            r_run.verifier_status = ver_resp.status
            if ver_resp.error:
                r_run.verifier_error = ver_resp.error.message

            assert ver_resp.result is not None
            verdict_map = {v.claim_id: v for v in ver_resp.result.verdicts}
            for c in all_claims:
                r_c: Any = c
                cid = str(r_c.claim_id)
                if cid in verdict_map:
                    v = verdict_map[cid]
                    r_c.verdict = v.verdict
                    r_c.evidence = v.evidence
                else:
                    # Missing from partial coverage -> unverified
                    r_c.verdict = "unverified"
                    r_c.evidence = None

            if ver_resp.result.source_audit:
                for src in ver_resp.result.source_audit:
                    new_art = TrackerArticle(
                        run_id=run.id,
                        url=src.source_url,
                        title=src.title,
                        status=src.status,
                        fetch_time_ms=int(src.latency_ms or 0),
                        error_message=src.error,
                    )
                    db.add(new_art)

            db.commit()

    # --- Step 4: Overall Status & Baseline Eligibility ---
    if r_run.researcher_status == "complete" and r_run.verifier_status in ("complete", "skipped"):
        r_run.status = "complete"
    else:
        r_run.status = "partial"

    # Baseline Promotion Rule (Spec 5.6):
    # Only complete Researcher results promote to baseline.
    # Verifier failure does not disqualify baseline eligibility.
    if r_run.researcher_status == "complete":
        r_run.is_baseline_eligible = True
    else:
        r_run.is_baseline_eligible = False

    # --- Step 5: Multi-run Diffing Badges ---
    baseline = find_matching_baseline(
        db=db,
        user_id=int(r_run.user_id),
        topic=str(r_run.topic),
        target_k=int(r_run.target_k),
        reset_generation=int(r_run.reset_generation),
        current_run_id=int(r_run.id),
    )
    compute_development_badges(run.developments, baseline, str(r_run.researcher_status))

    # --- Step 6: Artifact Paths ---
    try:
        md_p, _ = save_report_artifacts(run)
        r_run.report_path = str(md_p)
    except Exception:
        r_run.report_path = f"reports/run_{r_run.run_uuid}.md"

    default_orchestrator_logger.log_event(
        service="orchestrator",
        run_id=str(r_run.run_uuid),
        request_id=str(r_run.run_uuid),
        step=0,
        direction="outbound",
        endpoint_or_tool="lifecycle:execute",
        status=str(r_run.status),
        latency_ms=(time.monotonic() - start_run_time) * 1000.0,
    )
    trace_path = Path(f"reports/trace_{r_run.run_uuid}.jsonl")
    default_orchestrator_logger.export_run_traces(str(r_run.run_uuid), trace_path)
    r_run.trace_path = str(trace_path)

    db.commit()
    db.refresh(run)
    return run
