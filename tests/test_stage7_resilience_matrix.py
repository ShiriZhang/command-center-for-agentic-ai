"""
Resilience & Fault Tolerance Matrix Tests for Stage 7.4.
CSCI-GA.2630 Assignment 2

Verifies:
- Delayed responses & timeouts trigger bounded retries (3 total attempts).
- Connection failures trigger bounded retries with backoff.
- Terminal failures (400, 401, 409, 500) trigger NO retries (fail-fast).
- 503 with Retry-After header is honored and retried.
- Malformed worker payloads are invalidated completely without retries, charging full allocation.
- Partial coverage from Verifier preserves subset verdicts and leaves unverified claims.
- Backend restart recovery marks in-flight runs partial with conservative accounting.
- Worker process restart loses in-memory cache, verifying process-local idempotency limitation.
"""

from datetime import datetime, timezone
import json
import time
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4
import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from shared.config import BudgetsConfig, DeadlinesConfig, RetriesConfig
from shared.contracts import (
    AtomicClaim,
    ClaimVerdict,
    Development,
    ResearchPayload,
    ResearchRequest,
    ResearchResponse,
    ResearchResult,
    ResourceBudget,
    ResourceUsage,
    VerifyClaimInput,
    VerifyPayload,
    VerifyRequest,
    VerifyResponse,
    VerifyResult,
    WorkerError,
)
from backend.app.models import Base, TrackerClaim, TrackerDevelopment, TrackerRun, User
from backend.app.orchestration.accounting import (
    record_researcher_reservation,
    record_verifier_reservation,
    settle_researcher_charge,
    settle_verifier_charge,
)
from backend.app.orchestration.dispatch import WorkerDispatcher
from backend.app.orchestration.recovery import recover_interrupted_runs
from services.verifier.idempotency import IdempotencyRegistry


@pytest.fixture
def dispatcher():
    """Configured dispatcher with short backoff for fast deterministic testing."""
    budgets = BudgetsConfig()
    deadlines = DeadlinesConfig(
        worker_timeout_seconds=5,
        attempt_timeout_seconds=10,
        run_timeout_seconds=60,
        finalization_reserve_seconds=5,
    )
    retries = RetriesConfig(
        max_attempts=3,
        backoff_initial_seconds=0.01,
        backoff_factor=1.5,
        retryable_status_codes=[503],
    )
    return WorkerDispatcher(
        researcher_url="http://127.0.0.1:8001",
        verifier_url="http://127.0.0.1:8002",
        researcher_token="res-token",
        verifier_token="ver-token",
        budgets=budgets,
        deadlines=deadlines,
        retries=retries,
    )


# -----------------------------------------------------------------------------
# 1. Connection Failure & Timeout Retries (Bounded to 3 Attempts)
# -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "exception_to_raise",
    [
        httpx.ConnectError("Connection refused to worker", request=httpx.Request("POST", "http://127.0.0.1:8001/research")),
        httpx.ReadTimeout("Worker execution timed out", request=httpx.Request("POST", "http://127.0.0.1:8001/research")),
    ],
)
def test_transient_network_errors_retried_three_times(dispatcher, exception_to_raise):
    """Network connection failure and read timeouts must be retried up to 3 total attempts."""
    attempt_count = 0

    def mock_send_attempt(*args, **kwargs):
        nonlocal attempt_count
        attempt_count += 1
        raise exception_to_raise

    dispatcher._send_http_attempt = mock_send_attempt

    res = dispatcher.dispatch_research(
        run_id=uuid4(),
        topic="AI roles",
        k=5,
        start_run_time=time.monotonic(),
    )

    assert not res.success
    assert attempt_count == 3
    assert res.attempts == 3
    assert res.error_code == "network_or_timeout_error"


# -----------------------------------------------------------------------------
# 2. Terminal Failures (400, 401, 409, 500) -> ZERO Retries
# -----------------------------------------------------------------------------


@pytest.mark.parametrize("status_code", [400, 401, 409, 500])
def test_terminal_status_codes_halt_immediately_zero_retries(dispatcher, status_code):
    """Terminal status codes must NOT be retried: halts after attempt 1."""
    attempt_count = 0

    def mock_send_attempt(*args, **kwargs):
        nonlocal attempt_count
        attempt_count += 1
        request = httpx.Request("POST", "http://127.0.0.1:8001/research")
        return httpx.Response(
            status_code=status_code,
            text=f'{{"detail": "Terminal failure {status_code}"}}',
            request=request,
        )

    dispatcher._send_http_attempt = mock_send_attempt

    res = dispatcher.dispatch_research(
        run_id=uuid4(),
        topic="AI roles",
        k=5,
        start_run_time=time.monotonic(),
    )

    assert not res.success
    assert attempt_count == 1
    assert res.attempts == 1
    assert res.status_code == status_code


# -----------------------------------------------------------------------------
# 3. 503 / Retry-After Handling
# -----------------------------------------------------------------------------


def test_503_with_retry_after_retried_successfully(dispatcher):
    """HTTP 503 with Retry-After header is retried and succeeds on attempt 2."""
    attempt_count = 0
    run_id = uuid4()
    req_id = uuid4()

    valid_response = ResearchResponse(
        request_id=req_id,
        run_id=run_id,
        status="complete",
        result=ResearchResult(
            developments=[
                Development(
                    id="dev-1",
                    title="ML Engineer",
                    summary="PyTorch role",
                    claims=[
                        AtomicClaim(
                            claim_id="c1",
                            text="Location is Remote",
                            source_url="https://example.com/job1",
                        )
                    ],
                )
            ]
        ),
        usage=ResourceUsage(steps=3, fetches=2, tokens=5000),
    )

    def mock_send_attempt(*args, **kwargs):
        nonlocal attempt_count
        attempt_count += 1
        request = httpx.Request("POST", "http://127.0.0.1:8001/research")
        if attempt_count == 1:
            return httpx.Response(
                status_code=503,
                headers={"Retry-After": "0.01"},
                text='{"detail": "In-flight duplicate"}',
                request=request,
            )
        return httpx.Response(
            status_code=200,
            text=valid_response.model_dump_json(),
            request=request,
        )

    dispatcher._send_http_attempt = mock_send_attempt

    res = dispatcher.dispatch_research(
        run_id=run_id,
        topic="AI roles",
        k=3,
        start_run_time=time.monotonic(),
        request_id=req_id,
    )

    assert res.success
    assert attempt_count == 2
    assert res.attempts == 2
    assert res.response is not None
    assert len(res.response.result.developments) == 1


# -----------------------------------------------------------------------------
# 4. Malformed Worker Payload Invalidation & Full Reservation Charge
# -----------------------------------------------------------------------------


def test_malformed_successful_payload_invalidated_and_not_retried(dispatcher):
    """
    HTTP 200 with invalid schema or unknown claims must be completely discarded
    without retries, and settled with conservative full-share charge.
    """
    attempt_count = 0
    run_id = uuid4()
    req_id = uuid4()

    def mock_send_attempt(*args, **kwargs):
        nonlocal attempt_count
        attempt_count += 1
        request = httpx.Request("POST", "http://127.0.0.1:8002/verify")
        # Injected verdict with unknown claim_id that was never sent
        malformed_json = json.dumps(
            {
                "request_id": str(req_id),
                "run_id": str(run_id),
                "status": "complete",
                "result": {
                    "verdicts": [
                        {
                            "claim_id": "unknown_injected_claim_id",
                            "verdict": "supported",
                            "evidence": "proof",
                        }
                    ]
                },
                "usage": {"steps": 1, "fetches": 1, "tokens": 100},
                "error": None,
            }
        )
        return httpx.Response(status_code=200, text=malformed_json, request=request)

    dispatcher._send_http_attempt = mock_send_attempt

    claims = [
        VerifyClaimInput(
            claim_id="c_sent",
            text="Legitimate claim",
            source_url="https://example.com/job",
        )
    ]

    res = dispatcher.dispatch_verify(
        run_id=run_id,
        claims=claims,
        start_run_time=time.monotonic(),
        request_id=req_id,
    )

    # 1. Dispatch failed because validation rejected unknown claim
    assert not res.success
    assert attempt_count == 1  # Spec: 200 is never retried!
    assert res.error_code == "validation_failure"

    # 2. Accounting: Lost/invalid response charges full allocation
    run = TrackerRun(topic="AI", target_k=5)
    budgets = BudgetsConfig()
    record_verifier_reservation(run, req_id=req_id, budget=budgets.verifier)
    settle_verifier_charge(run=run, usage=None, budget=budgets.verifier, success=False)

    # Charged full reservation
    assert run.charged_steps == budgets.verifier.max_steps
    assert run.charged_fetches == budgets.verifier.max_fetches
    assert run.charged_tokens == budgets.verifier.max_tokens


# -----------------------------------------------------------------------------
# 5. Partial Coverage from Verifier Preserved Honestly
# -----------------------------------------------------------------------------


def test_partial_coverage_preserves_valid_subsets(dispatcher):
    """
    A valid partial verification response covering a subset of claims
    is retained; unverified status is reserved for Orchestrator to assign.
    """
    run_id = uuid4()
    req_id = uuid4()

    claims = [
        VerifyClaimInput(claim_id="c1", text="Role is SWE", source_url="https://example.com/1"),
        VerifyClaimInput(claim_id="c2", text="Salary is 150k", source_url="https://example.com/2"),
    ]

    # Worker only processed c1 before budget ran out
    partial_resp = VerifyResponse(
        request_id=req_id,
        run_id=run_id,
        status="partial",
        result=VerifyResult(
            verdicts=[
                ClaimVerdict(claim_id="c1", verdict="supported", evidence="SWE role at 150k")
            ]
        ),
        usage=ResourceUsage(steps=4, fetches=3, tokens=12000),
        error=WorkerError(code="time_budget_exhausted", message="Timeout", retryable=False),
    )

    dispatcher._send_http_attempt = lambda *args, **kwargs: httpx.Response(
        status_code=200,
        text=partial_resp.model_dump_json(),
        request=httpx.Request("POST", "http://127.0.0.1:8002/verify"),
    )

    res = dispatcher.dispatch_verify(
        run_id=run_id,
        claims=claims,
        start_run_time=time.monotonic(),
        request_id=req_id,
    )

    assert res.success
    assert res.response is not None
    assert res.response.status == "partial"
    assert len(res.response.result.verdicts) == 1
    assert res.response.result.verdicts[0].claim_id == "c1"


# -----------------------------------------------------------------------------
# 6. Backend Restart Interruption Recovery
# -----------------------------------------------------------------------------


def test_backend_restart_interruption_recovery():
    """Unfinished running records on restart become partial with conservative charges."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()

    user = User(id=1, username="testuser", email="u@example.com", hashed_password="pw")
    session.add(user)
    session.commit()

    run = TrackerRun(
        user_id=1,
        run_uuid=str(uuid4()),
        run_number=1,
        topic="AI",
        target_k=5,
        status="running",
        protocol_version=2,
    )
    session.add(run)
    session.flush()

    budgets = BudgetsConfig()
    record_researcher_reservation(run, req_id=uuid4(), budget=budgets.researcher)
    session.commit()

    # Simulate server crash & restart -> run recovery
    recovered = recover_interrupted_runs(db=session, budgets=budgets)
    assert recovered == 1

    session.refresh(run)
    assert run.status == "partial"
    assert run.researcher_status == "interrupted"
    assert run.charged_steps == budgets.researcher.max_steps
    session.close()


# -----------------------------------------------------------------------------
# 7. Worker Cache Loss (Process-Local Idempotency Limitation)
# -----------------------------------------------------------------------------


def test_worker_process_restart_clears_cache_limitation():
    """
    Demonstrates process-local idempotency limitation:
    Process restart clears memory cache; duplicate requests then re-execute.
    """
    reg = IdempotencyRegistry()
    req_id = str(uuid4())
    req_hash = "sample-hash"

    # Worker registers and completes
    status1, _ = reg.check_or_register(req_id, req_hash)
    assert status1 == "new"
    reg.complete(req_id, status_code=200, response_body=b'{"result": "first"}')

    # Replay while alive returns cached
    status2, record = reg.check_or_register(req_id, req_hash)
    assert status2 == "completed"
    assert record.response_body == b'{"result": "first"}'

    # Simulate worker restart (e.g. Render restart) -> registry reinitializes
    reg.clear()

    # After restart, same request is treated as new (cache lost!)
    status3, record_after_restart = reg.check_or_register(req_id, req_hash)
    assert status3 == "new"
    assert record_after_restart is None
