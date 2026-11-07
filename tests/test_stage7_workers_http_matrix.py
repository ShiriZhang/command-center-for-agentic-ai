"""
Comprehensive Real Socket HTTP Matrix Tests for Stage 7.3: Researcher & Verifier Workers.
CSCI-GA.2630 Assignment 2

Exercises both workers over real localhost TCP socket HTTP for:
- Missing/wrong bearer token (401 before body validation)
- Authenticated malformed JSON or invalid schema (400)
- In-flight duplicate requests (503 with Retry-After: 5)
- Reused request_id with altered payload (409 Conflict)
- Repeated identical completed requests (replayed response, zero duplicate operations in logs)
- Tiny deadline exhaustion (200 partial with time_budget_exhausted)
- Guarded source filtering (SSRF loopback / metadata blocked, unreachable verdict, 0 fetch decrement)
"""

import json
from pathlib import Path
import socket
import threading
import time
from uuid import uuid4
import httpx
import pytest
import uvicorn

from shared.contracts import (
    ResearchPayload,
    ResearchRequest,
    ResourceBudget,
    VerifyClaimInput,
    VerifyPayload,
    VerifyRequest,
)
from services.researcher.app import app as researcher_app, idempotency_registry as res_reg
from services.verifier.app import app as verifier_app, idempotency_registry as ver_reg
from services.researcher.telemetry import default_researcher_logger
from services.verifier.telemetry import default_verifier_logger


def get_free_port() -> int:
    """Finds an unused ephemeral TCP port on localhost."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


class UvicornServerThread(threading.Thread):
    """Runs a FastAPI application in a background thread on a real socket port."""

    def __init__(self, app, port: int):
        super().__init__(daemon=True)
        self.port = port
        config = uvicorn.Config(
            app=app,
            host="127.0.0.1",
            port=port,
            log_level="error",
        )
        self.server = uvicorn.Server(config)

    def run(self):
        self.server.run()

    def stop(self):
        self.server.should_exit = True


@pytest.fixture(scope="module")
def worker_servers():
    """Starts both worker services on real local TCP socket ports for the test module."""
    res_port = get_free_port()
    ver_port = get_free_port()

    # Configure tokens
    import os
    os.environ["RESEARCHER_TOKEN"] = "test-researcher-token"
    os.environ["VERIFIER_TOKEN"] = "test-verifier-token"

    res_server = UvicornServerThread(researcher_app, res_port)
    ver_server = UvicornServerThread(verifier_app, ver_port)
    res_server.start()
    ver_server.start()

    # Wait until socket is ready
    for p in (res_port, ver_port):
        for _ in range(50):
            try:
                with socket.create_connection(("127.0.0.1", p), timeout=0.1):
                    break
            except OSError:
                time.sleep(0.05)

    yield {
        "researcher_url": f"http://127.0.0.1:{res_port}",
        "verifier_url": f"http://127.0.0.1:{ver_port}",
    }

    res_server.stop()
    ver_server.stop()


@pytest.fixture(autouse=True)
def clean_registries():
    """Clears in-memory caches between test runs."""
    res_reg.clear()
    ver_reg.clear()


# -----------------------------------------------------------------------------
# 1. Parametrized Token-Before-Body Authentication & Schema Validation Barrier
# -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "service_key,endpoint,token,invalid_schema_payload",
    [
        (
            "researcher_url",
            "/research",
            "test-researcher-token",
            {
                "request_id": str(uuid4()),
                "run_id": str(uuid4()),
                "time_budget_ms": 120000,
                "unexpected_field": "illegal",
                "payload": {"topic": "AI", "k": 10},
            },
        ),
        (
            "verifier_url",
            "/verify",
            "test-verifier-token",
            {
                "request_id": str(uuid4()),
                "run_id": str(uuid4()),
                "time_budget_ms": 120000,
                "unexpected_field": "illegal",
                "payload": {"claims": []},
            },
        ),
    ],
)
def test_worker_auth_and_schema_validation_matrix(
    worker_servers, service_key, endpoint, token, invalid_schema_payload
):
    """Verifies token-before-body authentication and 400 rejection over real socket HTTP."""
    base_url = worker_servers[service_key]
    with httpx.Client(base_url=base_url, timeout=5.0) as client:
        # 1. Missing Authorization header -> 401
        resp_no_auth = client.post(endpoint, content=b"invalid json")
        assert resp_no_auth.status_code == 401

        # 2. Wrong token with malformed body -> 401 before body parsing
        resp_wrong_token = client.post(
            endpoint,
            headers={"Authorization": "Bearer wrong-token"},
            content=b"<<<not json>>>",
        )
        assert resp_wrong_token.status_code == 401

        # 3. Authenticated malformed JSON body -> 400 (not 422)
        resp_bad_json = client.post(
            endpoint,
            headers={"Authorization": f"Bearer {token}"},
            content=b"not a json string",
        )
        assert resp_bad_json.status_code == 400

        # 4. Authenticated invalid schema -> 400
        resp_bad_schema = client.post(
            endpoint,
            headers={"Authorization": f"Bearer {token}"},
            json=invalid_schema_payload,
        )
        assert resp_bad_schema.status_code == 400


# -----------------------------------------------------------------------------
# 2. Idempotency & Zero Duplicate Operations Assertion in Traces
# -----------------------------------------------------------------------------


def test_researcher_idempotency_and_zero_duplicate_work(worker_servers, tmp_path):
    """
    Over real HTTP: repeated identical completed request returns cached response.
    Verifies that zero additional model or fetch operations occur in process lifetime.
    """
    base_url = worker_servers["researcher_url"]
    req_id = uuid4()
    run_id = uuid4()
    headers = {"Authorization": "Bearer test-researcher-token"}

    req_body = ResearchRequest(
        request_id=req_id,
        run_id=run_id,
        time_budget_ms=5000,
        budget=ResourceBudget(max_steps=5, max_fetches=5, max_tokens=10000),
        payload=ResearchPayload(topic="Top AI roles", k=3),
    ).model_dump(mode="json")

    log_path = Path("reports/researcher.jsonl")
    initial_log_lines = log_path.read_text(encoding="utf-8").splitlines() if log_path.exists() else []

    with httpx.Client(base_url=base_url, timeout=10.0) as client:
        # Call 1: First arrival
        resp1 = client.post("/research", headers=headers, json=req_body)
        assert resp1.status_code == 200
        data1 = resp1.json()

        lines_after_call1 = log_path.read_text(encoding="utf-8").splitlines() if log_path.exists() else []
        assert len(lines_after_call1) >= len(initial_log_lines)

        # Call 2: Repeated identical request
        resp2 = client.post("/research", headers=headers, json=req_body)
        assert resp2.status_code == 200
        data2 = resp2.json()
        assert data1 == data2

        # Check logs: replayed event only, zero extra tool or model executions
        lines_after_call2 = log_path.read_text(encoding="utf-8").splitlines() if log_path.exists() else []
        new_records = [json.loads(line) for line in lines_after_call2[len(lines_after_call1):]]
        outbound_calls = [r for r in new_records if r.get("direction") == "outbound"]
        assert len(outbound_calls) == 0, "Repeated request must not perform duplicate outbound work"

        # Call 3: Altered body with same request_id -> 409 Conflict
        altered_body = dict(req_body)
        altered_body["payload"] = {"topic": "Altered topic", "k": 4}
        resp_altered = client.post("/research", headers=headers, json=altered_body)
        assert resp_altered.status_code == 409


def test_verifier_idempotency_and_zero_duplicate_work(worker_servers):
    """
    Over real HTTP: repeated identical completed verify request returns cached response.
    Verifies that zero additional model or fetch operations occur.
    """
    base_url = worker_servers["verifier_url"]
    req_id = uuid4()
    run_id = uuid4()
    headers = {"Authorization": "Bearer test-verifier-token"}

    req_body = VerifyRequest(
        request_id=req_id,
        run_id=run_id,
        time_budget_ms=5000,
        budget=ResourceBudget(max_steps=5, max_fetches=5, max_tokens=10000),
        payload=VerifyPayload(
            claims=[
                VerifyClaimInput(
                    claim_id="c1",
                    text="Company is DeepMind",
                    source_url="http://127.0.0.1:8000/careers",
                )
            ]
        ),
    ).model_dump(mode="json")

    log_path = Path("reports/verifier.jsonl")
    initial_log_lines = log_path.read_text(encoding="utf-8").splitlines() if log_path.exists() else []

    with httpx.Client(base_url=base_url, timeout=10.0) as client:
        # Call 1: Completed request
        resp1 = client.post("/verify", headers=headers, json=req_body)
        assert resp1.status_code == 200
        data1 = resp1.json()

        lines_after_call1 = log_path.read_text(encoding="utf-8").splitlines() if log_path.exists() else []

        # Call 2: Repeated identical request
        resp2 = client.post("/verify", headers=headers, json=req_body)
        assert resp2.status_code == 200
        assert data1 == resp2.json()

        lines_after_call2 = log_path.read_text(encoding="utf-8").splitlines() if log_path.exists() else []
        new_records = [json.loads(line) for line in lines_after_call2[len(lines_after_call1):]]
        outbound_calls = [r for r in new_records if r.get("direction") == "outbound"]
        assert len(outbound_calls) == 0, "Repeated request must not perform duplicate outbound work"

        # Call 3: Altered body -> 409 Conflict
        altered_body = dict(req_body)
        altered_body["payload"] = {
            "claims": [
                {
                    "claim_id": "c1",
                    "text": "Altered claim text",
                    "source_url": "http://127.0.0.1:8000/careers",
                }
            ]
        }
        resp_altered = client.post("/verify", headers=headers, json=altered_body)
        assert resp_altered.status_code == 409


# -----------------------------------------------------------------------------
# 3. In-Flight Duplicate Handling (503 + Retry-After: 5)
# -----------------------------------------------------------------------------


def test_in_flight_duplicate_handling_both_workers_real_http(worker_servers):
    """Tests 503 + Retry-After: 5 for in-flight requests over real socket HTTP."""
    from services.researcher.idempotency import canonical_request_hash

    # 1. Researcher in-flight duplicate
    res_base = worker_servers["researcher_url"]
    req_id = str(uuid4())
    res_body = {
        "request_id": req_id,
        "run_id": str(uuid4()),
        "time_budget_ms": 10000,
        "budget": {"max_steps": 5, "max_fetches": 5, "max_tokens": 10000},
        "payload": {"topic": "AI", "k": 3},
    }
    h = canonical_request_hash(res_body)
    res_reg.check_or_register(req_id, h)

    with httpx.Client(base_url=res_base, timeout=5.0) as client:
        resp_res = client.post(
            "/research",
            headers={"Authorization": "Bearer test-researcher-token"},
            json=res_body,
        )
        assert resp_res.status_code == 503
        assert resp_res.headers.get("retry-after") == "5"

    # 2. Verifier in-flight duplicate
    ver_base = worker_servers["verifier_url"]
    ver_req_id = str(uuid4())
    ver_body = {
        "request_id": ver_req_id,
        "run_id": str(uuid4()),
        "time_budget_ms": 10000,
        "budget": {"max_steps": 5, "max_fetches": 5, "max_tokens": 10000},
        "payload": {"claims": []},
    }
    vh = canonical_request_hash(ver_body)
    ver_reg.check_or_register(ver_req_id, vh)

    with httpx.Client(base_url=ver_base, timeout=5.0) as client:
        resp_ver = client.post(
            "/verify",
            headers={"Authorization": "Bearer test-verifier-token"},
            json=ver_body,
        )
        assert resp_ver.status_code == 503
        assert resp_ver.headers.get("retry-after") == "5"


# -----------------------------------------------------------------------------
# 4. Tiny Deadline & SSRF Guarded Source Verification
# -----------------------------------------------------------------------------


def test_tiny_deadline_exhaustion_real_http(worker_servers):
    """Tiny time_budget_ms returns 200 partial with time_budget_exhausted over real socket HTTP."""
    base_url = worker_servers["researcher_url"]
    res_body = {
        "request_id": str(uuid4()),
        "run_id": str(uuid4()),
        "time_budget_ms": 1,
        "budget": {"max_steps": 10, "max_fetches": 10, "max_tokens": 20000},
        "payload": {"topic": "AI", "k": 5},
    }
    time.sleep(0.005)

    with httpx.Client(base_url=base_url, timeout=5.0) as client:
        resp = client.post(
            "/research",
            headers={"Authorization": "Bearer test-researcher-token"},
            json=res_body,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "partial"
        assert data["error"]["code"] == "time_budget_exhausted"


def test_guarded_source_rejection_real_http(worker_servers):
    """Prohibited loopback/metadata targets are marked unreachable with 0 fetch spend over real socket HTTP."""
    base_url = worker_servers["verifier_url"]
    ver_body = {
        "request_id": str(uuid4()),
        "run_id": str(uuid4()),
        "time_budget_ms": 10000,
        "budget": {"max_steps": 5, "max_fetches": 5, "max_tokens": 10000},
        "payload": {
            "claims": [
                {
                    "claim_id": "c_loopback",
                    "text": "Internal Admin portal",
                    "source_url": "http://127.0.0.1:8000/admin",
                },
                {
                    "claim_id": "c_metadata",
                    "text": "AWS metadata credential",
                    "source_url": "http://169.254.169.254/latest/meta-data/",
                },
            ]
        },
    }

    with httpx.Client(base_url=base_url, timeout=5.0) as client:
        resp = client.post(
            "/verify",
            headers={"Authorization": "Bearer test-verifier-token"},
            json=ver_body,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "complete"
        verdicts = {v["claim_id"]: v for v in data["result"]["verdicts"]}

        assert verdicts["c_loopback"]["verdict"] == "unreachable"
        assert verdicts["c_loopback"]["evidence"] is None
        assert verdicts["c_metadata"]["verdict"] == "unreachable"
        assert verdicts["c_metadata"]["evidence"] is None
        assert data["usage"]["fetches"] == 0
