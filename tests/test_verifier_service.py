"""
Tests for Task 4.1: Verifier Service HTTP Status Matrix & Authentication.
CSCI-GA.2630 Assignment 2
"""

from unittest.mock import patch
from uuid import uuid4
import pytest
from starlette.testclient import TestClient

from shared.contracts import (
    ResourceBudget,
    VerifyClaimInput,
    VerifyPayload,
    VerifyRequest,
    VerifyResponse,
    VerifyResult,
    ClaimVerdict,
    ResourceUsage,
)


@pytest.fixture
def verifier_client(monkeypatch):
    """Provides a TestClient for the Verifier service with a configured token."""
    monkeypatch.setenv("VERIFIER_TOKEN", "test-verifier-secret-token")
    from services.verifier.app import app, idempotency_registry
    idempotency_registry.clear()
    return TestClient(app, raise_server_exceptions=False)


def test_healthz_unauthenticated_returns_200(verifier_client):
    """GET /healthz must return 200 with status ok without credentials."""
    resp = verifier_client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_verify_missing_auth_header_returns_401(verifier_client):
    """POST /verify without Authorization header must return 401."""
    resp = verifier_client.post("/verify", content="invalid json")
    assert resp.status_code == 401
    assert "detail" in resp.json()


def test_verify_invalid_token_with_invalid_json_returns_401(verifier_client):
    """
    Spec requirement: Authentication SHALL occur before JSON parsing or schema validation.
    An invalid token must return 401 without revealing schema errors.
    """
    headers = {"Authorization": "Bearer wrong-token-xyz"}
    resp = verifier_client.post("/verify", headers=headers, content="<<<not json>>>")
    assert resp.status_code == 401


def test_verify_authenticated_malformed_json_returns_400(verifier_client):
    """Authenticated malformed JSON payload must return HTTP 400 (not 422)."""
    headers = {"Authorization": "Bearer test-verifier-secret-token"}
    resp = verifier_client.post("/verify", headers=headers, content="not a json payload")
    assert resp.status_code == 400
    assert resp.json()["detail"] == "Malformed JSON body"


def test_verify_authenticated_schema_invalid_returns_400(verifier_client):
    """Unknown fields or missing parameters must return 400."""
    headers = {"Authorization": "Bearer test-verifier-secret-token"}
    bad_payload = {
        "request_id": str(uuid4()),
        "run_id": str(uuid4()),
        "time_budget_ms": 60000,
        "budget": {"max_steps": 12, "max_fetches": 20, "max_tokens": 40000},
        "payload": {"claims": [{"claim_id": "c1", "text": "AI Engineer"}]},  # missing source_url
    }
    resp = verifier_client.post("/verify", headers=headers, json=bad_payload)
    assert resp.status_code == 400
    assert resp.json()["detail"] == "Invalid request schema"


def test_verify_endpoint_idempotency_matrix(verifier_client):
    """
    Verify complete idempotency matrix over HTTP:
    1. New request returns 200.
    2. Repeated identical request returns 200 replayed with identical content.
    3. Altered payload with same request_id returns 409 Conflict.
    """
    headers = {"Authorization": "Bearer test-verifier-secret-token"}
    req_id = uuid4()
    run_id = uuid4()

    req = VerifyRequest(
        request_id=req_id,
        run_id=run_id,
        time_budget_ms=60000,
        budget=ResourceBudget(max_steps=12, max_fetches=20, max_tokens=40000),
        payload=VerifyPayload(
            claims=[
                VerifyClaimInput(
                    claim_id="c1",
                    text="Company is hiring AI Engineer.",
                    source_url="https://example.com/job",
                )
            ]
        ),
    )

    mock_resp = VerifyResponse(
        request_id=req_id,
        run_id=run_id,
        status="complete",
        result=VerifyResult(
            verdicts=[
                ClaimVerdict(
                    claim_id="c1",
                    verdict="supported",
                    evidence="hiring AI Engineer",
                )
            ]
        ),
        usage=ResourceUsage(steps=1, fetches=1, tokens=500),
        error=None,
    )

    with patch("services.verifier.app.execute_verification", return_value=mock_resp) as mock_exec:
        # 1. First execution: 200
        resp1 = verifier_client.post("/verify", headers=headers, content=req.model_dump_json())
        assert resp1.status_code == 200
        assert resp1.json()["status"] == "complete"
        assert mock_exec.call_count == 1

        # 2. Second execution (identical body & id): 200 replayed without calling execute_verification again
        resp2 = verifier_client.post("/verify", headers=headers, content=req.model_dump_json())
        assert resp2.status_code == 200
        assert resp2.json() == resp1.json()
        assert mock_exec.call_count == 1  # Unchanged!

    # 3. Altered payload with same request_id: 409 Conflict
    req_altered = VerifyRequest(
        request_id=req_id,
        run_id=run_id,
        time_budget_ms=60000,
        budget=ResourceBudget(max_steps=12, max_fetches=20, max_tokens=40000),
        payload=VerifyPayload(
            claims=[
                VerifyClaimInput(
                    claim_id="c2",
                    text="Completely different claim text.",
                    source_url="https://example.com/other",
                )
            ]
        ),
    )
    resp3 = verifier_client.post("/verify", headers=headers, content=req_altered.model_dump_json())
    assert resp3.status_code == 409
    assert "Conflict" in resp3.json()["detail"]


def test_verify_endpoint_replays_terminal_500(verifier_client):
    """Spec Scenario: Repeated request returns cached response, including terminal 500."""
    headers = {"Authorization": "Bearer test-verifier-secret-token"}
    req_id = uuid4()
    run_id = uuid4()
    req = VerifyRequest(
        request_id=req_id,
        run_id=run_id,
        time_budget_ms=60000,
        budget=ResourceBudget(max_steps=12, max_fetches=20, max_tokens=40000),
        payload=VerifyPayload(
            claims=[
                VerifyClaimInput(
                    claim_id="c1",
                    text="Throw fatal error.",
                    source_url="https://example.com/job",
                )
            ]
        ),
    )

    with patch("services.verifier.app.execute_verification", side_effect=RuntimeError("Terminal verifier failure")):
        resp1 = verifier_client.post("/verify", headers=headers, content=req.model_dump_json())
        assert resp1.status_code == 500
        data1 = resp1.json()
        assert data1["status"] == "failed"
        assert data1["error"]["retryable"] is False
        assert data1["result"] is None

    # Second attempt without patch: must replay cached 500
    resp2 = verifier_client.post("/verify", headers=headers, content=req.model_dump_json())
    assert resp2.status_code == 500
    assert resp2.json() == resp1.json()
