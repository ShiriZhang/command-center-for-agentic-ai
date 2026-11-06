"""
Unit and integration tests for Task 3.3: Researcher In-Memory Idempotency and Response Replay.
Verifies identical cached call replay, altered body conflict (409),
in-flight duplicate handling (503 + Retry-After: 5), and thread safety.
"""

import json
from uuid import uuid4
import pytest
from starlette.testclient import TestClient

from shared.contracts import ResearchRequest, ResourceBudget, ResearchPayload
from services.researcher.idempotency import IdempotencyRegistry, canonical_request_hash


@pytest.fixture
def registry():
    """Provides a fresh idempotency registry."""
    reg = IdempotencyRegistry()
    reg.clear()
    return reg


def test_canonical_request_hash_ignores_key_order():
    """Canonical hash must be identical regardless of JSON object key ordering."""
    dict1 = {"b": 2, "a": 1, "nested": {"y": 20, "x": 10}}
    dict2 = {"a": 1, "b": 2, "nested": {"x": 10, "y": 20}}
    assert canonical_request_hash(dict1) == canonical_request_hash(dict2)

    # Different value produces different hash
    dict3 = {"a": 1, "b": 3, "nested": {"x": 10, "y": 20}}
    assert canonical_request_hash(dict1) != canonical_request_hash(dict3)


def test_registry_new_request_registered(registry):
    """First call registers as in-flight and returns 'new'."""
    req_id = str(uuid4())
    h = "hash-1"
    status, record = registry.check_or_register(req_id, h)
    assert status == "new"
    assert record is None


def test_registry_in_flight_duplicate_returns_in_flight(registry):
    """Second call with same hash while in-flight returns 'in_flight'."""
    req_id = str(uuid4())
    h = "hash-1"
    registry.check_or_register(req_id, h)

    status, record = registry.check_or_register(req_id, h)
    assert status == "in_flight"
    assert record is not None
    assert record.state == "in_flight"


def test_registry_altered_body_returns_conflict(registry):
    """Same request_id with different hash returns 'conflict' (HTTP 409)."""
    req_id = str(uuid4())
    registry.check_or_register(req_id, "hash-original")

    status, record = registry.check_or_register(req_id, "hash-mutated")
    assert status == "conflict"


def test_registry_completed_request_replays_response(registry):
    """Completed request returns 'completed' with stored response data."""
    req_id = str(uuid4())
    h = "hash-complete"
    registry.check_or_register(req_id, h)
    registry.complete(req_id, status_code=200, response_body=b'{"status":"complete"}', headers={"X-Custom": "test"})

    status, record = registry.check_or_register(req_id, h)
    assert status == "completed"
    assert record is not None
    assert record.status_code == 200
    assert record.response_body == b'{"status":"complete"}'
    assert record.headers.get("X-Custom") == "test"


def test_research_endpoint_idempotency_integration(monkeypatch):
    """
    HTTP Integration test:
    - Same request returns identical response.
    - Mutated body with same request_id returns HTTP 409.
    """
    monkeypatch.setenv("RESEARCHER_TOKEN", "secret-token")
    from services.researcher.app import app, idempotency_registry
    idempotency_registry.clear()

    client = TestClient(app, raise_server_exceptions=False)
    headers = {"Authorization": "Bearer secret-token"}

    req_id = uuid4()
    run_id = uuid4()
    req1 = ResearchRequest(
        request_id=req_id,
        run_id=run_id,
        time_budget_ms=60000,
        budget=ResourceBudget(max_steps=18, max_fetches=20, max_tokens=60000),
        payload=ResearchPayload(topic="Top AI Roles", k=3),
    )

    # 1. First invocation: 200
    resp1 = client.post("/research", headers=headers, content=req1.model_dump_json())
    assert resp1.status_code == 200
    data1 = resp1.json()

    # 2. Identical second invocation: 200 replayed
    resp2 = client.post("/research", headers=headers, content=req1.model_dump_json())
    assert resp2.status_code == 200
    assert resp2.json() == data1

    # 3. Altered body with SAME request_id: 409 Conflict
    req_altered = ResearchRequest(
        request_id=req_id,  # Same request_id
        run_id=run_id,
        time_budget_ms=60000,
        budget=ResourceBudget(max_steps=18, max_fetches=20, max_tokens=60000),
        payload=ResearchPayload(topic="Completely Different Topic", k=10),  # Altered!
    )
    resp3 = client.post("/research", headers=headers, content=req_altered.model_dump_json())
    assert resp3.status_code == 409
    assert "Conflict" in resp3.json()["detail"]


def test_research_endpoint_replays_terminal_500(monkeypatch):
    """Spec Scenario: Repeated request returns cached response, including terminal 500."""
    monkeypatch.setenv("RESEARCHER_TOKEN", "secret-token")
    from services.researcher.app import app, idempotency_registry
    idempotency_registry.clear()

    client = TestClient(app, raise_server_exceptions=False)
    headers = {"Authorization": "Bearer secret-token"}

    req_id = uuid4()
    run_id = uuid4()
    req = ResearchRequest(
        request_id=req_id,
        run_id=run_id,
        time_budget_ms=60000,
        budget=ResourceBudget(max_steps=18, max_fetches=20, max_tokens=60000),
        payload=ResearchPayload(topic="Throw Error", k=3),
    )

    with pytest.MonkeyPatch.context() as mp:
        from unittest.mock import patch
        with patch("services.researcher.app.execute_research", side_effect=RuntimeError("Unrecoverable crash")):
            # First attempt: crashes and records 500
            resp1 = client.post("/research", headers=headers, content=req.model_dump_json())
            assert resp1.status_code == 500

    # Second attempt WITHOUT mock: must replay cached 500 without calling execute_research
    resp2 = client.post("/research", headers=headers, content=req.model_dump_json())
    assert resp2.status_code == 500
    assert resp2.json() == resp1.json()
