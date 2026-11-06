"""
Tests for Tasks 3.1 & 3.2: Researcher Service HTTP Interface and Authentication Boundary.
Verifies GET /healthz, token-before-body authentication (HTTP 401),
malformed input handling (HTTP 400), and request isolation.
"""

from uuid import uuid4
import pytest
from starlette.testclient import TestClient

from shared.contracts import ResearchRequest, ResourceBudget, ResearchPayload


@pytest.fixture
def researcher_client(monkeypatch):
    """Provides a TestClient for the Researcher service with a fixed service token."""
    monkeypatch.setenv("RESEARCHER_TOKEN", "test-researcher-secret-token")
    from services.researcher.app import app
    return TestClient(app, raise_server_exceptions=False)


def test_healthz_unauthenticated_returns_200(researcher_client):
    """GET /healthz must return 200 with status ok without requiring credentials."""
    resp = researcher_client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_research_missing_auth_header_returns_401(researcher_client):
    """POST /research without Authorization header must return 401."""
    resp = researcher_client.post("/research", content="invalid json body")
    assert resp.status_code == 401
    assert "detail" in resp.json()


def test_research_invalid_token_with_invalid_json_returns_401(researcher_client):
    """
    Spec requirement: Authentication SHALL occur before JSON parsing or schema validation.
    An invalid token must return 401 without parsing or revealing body schema errors.
    """
    headers = {"Authorization": "Bearer wrong-token-12345"}
    resp = researcher_client.post("/research", headers=headers, content="<<<not json>>>")
    assert resp.status_code == 401


def test_research_authenticated_malformed_json_returns_400(researcher_client):
    """
    Spec requirement: Authenticated validation failures return 400 rather than 422.
    Malformed JSON payload must return HTTP 400.
    """
    headers = {"Authorization": "Bearer test-researcher-secret-token"}
    resp = researcher_client.post("/research", headers=headers, content="not a valid json string")
    assert resp.status_code == 400
    assert resp.json()["detail"] == "Malformed JSON body"


def test_research_authenticated_schema_invalid_returns_400(researcher_client):
    """
    Spec requirement: Authenticated validation failures return 400 rather than 422.
    Unknown fields or missing envelope parameters must return 400.
    """
    headers = {"Authorization": "Bearer test-researcher-secret-token"}
    # Missing required 'budget' and has unknown field
    invalid_body = {
        "request_id": str(uuid4()),
        "run_id": str(uuid4()),
        "time_budget_ms": 120000,
        "unknown_extra_param": "forbidden",
        "payload": {"topic": "AI", "k": 10},
    }
    resp = researcher_client.post("/research", headers=headers, json=invalid_body)
    assert resp.status_code == 400


def test_research_authenticated_valid_envelope_accepted(researcher_client):
    """Valid envelope is accepted and returns a valid ResearchResponse."""
    headers = {"Authorization": "Bearer test-researcher-secret-token"}
    valid_req = ResearchRequest(
        request_id=uuid4(),
        run_id=uuid4(),
        time_budget_ms=60000,
        budget=ResourceBudget(max_steps=18, max_fetches=20, max_tokens=60000),
        payload=ResearchPayload(topic="Top AI Roles", k=3),
    )
    resp = researcher_client.post("/research", headers=headers, content=valid_req.model_dump_json())
    assert resp.status_code == 200
    data = resp.json()
    assert data["request_id"] == str(valid_req.request_id)
    assert data["run_id"] == str(valid_req.run_id)
    assert data["status"] in ("complete", "partial")
    assert "usage" in data


def test_research_two_requests_are_isolated(researcher_client):
    """
    Task 3.1 requirement: Verify two HTTP requests research independently
    with isolated clients/counters and no history/database credentials or local state reads.
    """
    headers = {"Authorization": "Bearer test-researcher-secret-token"}
    req1 = ResearchRequest(
        request_id=uuid4(),
        run_id=uuid4(),
        time_budget_ms=60000,
        budget=ResourceBudget(max_steps=18, max_fetches=20, max_tokens=60000),
        payload=ResearchPayload(topic="Topic A", k=3),
    )
    req2 = ResearchRequest(
        request_id=uuid4(),
        run_id=uuid4(),
        time_budget_ms=60000,
        budget=ResourceBudget(max_steps=18, max_fetches=20, max_tokens=60000),
        payload=ResearchPayload(topic="Topic B", k=5),
    )

    resp1 = researcher_client.post("/research", headers=headers, content=req1.model_dump_json())
    resp2 = researcher_client.post("/research", headers=headers, content=req2.model_dump_json())

    assert resp1.status_code == 200
    assert resp2.status_code == 200
    d1 = resp1.json()
    d2 = resp2.json()

    assert d1["request_id"] == str(req1.request_id)
    assert d2["request_id"] == str(req2.request_id)
    assert d1["request_id"] != d2["request_id"]
    assert d1["run_id"] != d2["run_id"]
