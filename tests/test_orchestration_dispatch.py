"""
Tests for Tasks 5.1, 5.2, & 5.4: Orchestrator HTTP Dispatch, Deadlines, Retries, and Validation.
CSCI-GA.2630 Assignment 2
"""

import sys
import time
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4
import httpx
import pytest

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
from backend.app.orchestration.dispatch import (
    DispatchResult,
    WorkerDispatcher,
)


def test_zero_worker_runtime_imports():
    """Spec Requirement 5.1: No direct worker runtime imports in backend orchestration."""
    import backend.app.orchestration.dispatch as dispatch_mod

    module_file = dispatch_mod.__file__ or ""
    with open(module_file, "r", encoding="utf-8") as f:
        content = f.read()

    assert "services.researcher" not in content
    assert "services.verifier" not in content
    assert "tracker.run" not in content


def test_dispatch_researcher_success():
    """Spec: Dispatches valid envelope and returns validated research response."""
    run_id = uuid4()
    dispatcher = WorkerDispatcher(
        researcher_url="http://127.0.0.1:8001",
        verifier_url="http://127.0.0.1:8002",
        researcher_token="res-secret",
        verifier_token="ver-secret",
    )

    req_id = uuid4()
    mock_response = ResearchResponse(
        request_id=req_id,
        run_id=run_id,
        status="complete",
        result=ResearchResult(
            developments=[
                Development(
                    id="dev-1",
                    title="AI Engineer",
                    summary="Role summary",
                    claims=[
                        AtomicClaim(
                            claim_id="c1",
                            text="Hiring AI Engineer",
                            source_url="https://example.com/job",
                        )
                    ],
                )
            ]
        ),
        usage=ResourceUsage(steps=5, fetches=6, tokens=12000),
        error=None,
    )

    mock_http_resp = MagicMock()
    mock_http_resp.status_code = 200
    mock_http_resp.content = mock_response.model_dump_json().encode("utf-8")
    mock_http_resp.headers = {"Content-Type": "application/json"}

    with patch.object(dispatcher, "_send_http_attempt", return_value=mock_http_resp) as mock_send:
        result = dispatcher.dispatch_research(
            run_id=run_id,
            topic="AI",
            k=3,
            start_run_time=time.monotonic(),
            request_id=req_id,
        )

        assert result.success is True
        assert result.response is not None
        assert result.response.status == "complete"
        assert result.response.request_id == req_id
        assert result.attempts == 1
        assert mock_send.call_count == 1

        # Check call arguments: authorization header and payload
        call_kwargs = mock_send.call_args.kwargs
        assert call_kwargs["headers"]["Authorization"] == "Bearer res-secret"
        sent_envelope = ResearchRequest.model_validate_json(call_kwargs["content"])
        assert sent_envelope.time_budget_ms == 120000
        assert sent_envelope.budget.max_steps == 18


def test_dispatch_terminal_status_never_retried():
    """Spec Requirement 5.2: Terminal status codes (400, 401, 409, 500) are never retried."""
    dispatcher = WorkerDispatcher()
    for terminal_code in [400, 401, 409, 500]:
        mock_http_resp = MagicMock()
        mock_http_resp.status_code = terminal_code
        mock_http_resp.content = b'{"detail": "Terminal error"}'
        mock_http_resp.headers = {"Content-Type": "application/json"}

        with patch.object(dispatcher, "_send_http_attempt", return_value=mock_http_resp) as mock_send:
            result = dispatcher.dispatch_research(
                run_id=uuid4(),
                topic="AI",
                k=3,
                start_run_time=time.monotonic(),
            )
            assert result.success is False
            assert result.status_code == terminal_code
            assert mock_send.call_count == 1  # Never retried!


def test_dispatch_200_partial_never_retried():
    """Spec Requirement 5.2: HTTP 200 partial is a successful transport response, never retried."""
    req_id = uuid4()
    run_id = uuid4()
    mock_resp = ResearchResponse(
        request_id=req_id,
        run_id=run_id,
        status="partial",
        result=ResearchResult(developments=[]),
        usage=ResourceUsage(steps=1, fetches=1, tokens=500),
        error=WorkerError(code="time_budget_exhausted", message="Timeout", retryable=False),
    )
    mock_http_resp = MagicMock()
    mock_http_resp.status_code = 200
    mock_http_resp.content = mock_resp.model_dump_json().encode("utf-8")

    dispatcher = WorkerDispatcher()
    with patch.object(dispatcher, "_send_http_attempt", return_value=mock_http_resp) as mock_send:
        result = dispatcher.dispatch_research(
            run_id=run_id,
            topic="AI",
            k=3,
            start_run_time=time.monotonic(),
            request_id=req_id,
        )
        assert result.success is True
        assert result.response is not None
        assert result.response.status == "partial"
        assert mock_send.call_count == 1


def test_dispatch_503_retries_with_retry_after():
    """Spec Requirement 5.2: HTTP 503 is retried honoring Retry-After with identical request_id."""
    req_id = uuid4()
    run_id = uuid4()

    resp_503 = MagicMock()
    resp_503.status_code = 503
    resp_503.headers = {"Retry-After": "1"}
    resp_503.content = b'{"detail": "In flight"}'

    valid_resp = ResearchResponse(
        request_id=req_id,
        run_id=run_id,
        status="complete",
        result=ResearchResult(
            developments=[
                Development(
                    id="dev-1",
                    title="Role",
                    summary="Sum",
                    claims=[AtomicClaim(claim_id="c1", text="text", source_url="https://example.com")],
                )
            ]
        ),
        usage=ResourceUsage(steps=1, fetches=1, tokens=500),
        error=None,
    )
    resp_200 = MagicMock()
    resp_200.status_code = 200
    resp_200.content = valid_resp.model_dump_json().encode("utf-8")

    dispatcher = WorkerDispatcher()
    with patch.object(dispatcher, "_send_http_attempt", side_effect=[resp_503, resp_200]) as mock_send:
        with patch("time.sleep") as mock_sleep:
            result = dispatcher.dispatch_research(
                run_id=run_id,
                topic="AI",
                k=3,
                start_run_time=time.monotonic(),
                request_id=req_id,
            )
            assert result.success is True
            assert result.attempts == 2
            assert mock_send.call_count == 2
            mock_sleep.assert_called_with(1.0)  # Honored Retry-After: 1

            # Verify identical bodies sent across attempts
            body1 = mock_send.call_args_list[0].kwargs["content"]
            body2 = mock_send.call_args_list[1].kwargs["content"]
            assert body1 == body2


def test_dispatch_max_attempts_bounded_at_three():
    """Spec Requirement 5.2: At most three attempts total."""
    resp_503 = MagicMock()
    resp_503.status_code = 503
    resp_503.headers = {"Retry-After": "1"}
    resp_503.content = b'{"detail": "Overloaded"}'

    dispatcher = WorkerDispatcher()
    with patch.object(dispatcher, "_send_http_attempt", return_value=resp_503) as mock_send:
        with patch("time.sleep"):
            result = dispatcher.dispatch_research(
                run_id=uuid4(),
                topic="AI",
                k=3,
                start_run_time=time.monotonic(),
            )
            assert result.success is False
            assert result.attempts == 3
            assert mock_send.call_count == 3


def test_dispatch_skips_attempt_if_exceeds_run_window():
    """Spec Requirement 5.2: Skips attempt that cannot fit in remaining run execution window."""
    dispatcher = WorkerDispatcher()

    # Simulate run started 800 seconds ago (out of 900s total, with 30s reserve -> available 870s)
    # Remaining window is 70s, but attempt timeout is 210s. Cannot fit!
    start_run_time = time.monotonic() - 800.0

    with patch.object(dispatcher, "_send_http_attempt") as mock_send:
        result = dispatcher.dispatch_research(
            run_id=uuid4(),
            topic="AI",
            k=3,
            start_run_time=start_run_time,
        )
        assert result.success is False
        assert "run_timeout_exceeded" in result.error_code
        assert mock_send.call_count == 0  # Skipped!


def test_dispatch_invalid_response_discarded_without_crashing():
    """Spec Requirement 5.4: Discards invalid worker response without crashing."""
    req_id = uuid4()
    run_id = uuid4()
    # Response contains claims with evidence length > 300 (validation failure)
    bad_resp_json = {
        "request_id": str(req_id),
        "run_id": str(run_id),
        "status": "complete",
        "result": {
            "verdicts": [
                {
                    "claim_id": "c1",
                    "verdict": "supported",
                    "evidence": "X" * 350,  # Invalid evidence > 300!
                }
            ]
        },
        "usage": {"steps": 1, "fetches": 1, "tokens": 500},
        "error": None,
    }
    mock_http_resp = MagicMock()
    mock_http_resp.status_code = 200
    mock_http_resp.content = bytes(str(bad_resp_json).replace("'", '"'), "utf-8")

    dispatcher = WorkerDispatcher()
    with patch.object(dispatcher, "_send_http_attempt", return_value=mock_http_resp):
        result = dispatcher.dispatch_verify(
            run_id=run_id,
            claims=[VerifyClaimInput(claim_id="c1", text="text", source_url="https://example.com")],
            start_run_time=time.monotonic(),
            request_id=req_id,
        )
        assert result.success is False
        assert result.response is None
        assert "validation_failure" in result.error_code
