"""
Unit tests for Task 4.7: Verifier Correlated JSONL Telemetry.
CSCI-GA.2630 Assignment 2
"""

import json
from uuid import uuid4
import pytest

from services.verifier.telemetry import (
    TelemetryLogger,
    TelemetryRecord,
)


@pytest.fixture
def verifier_telemetry_log_path(tmp_path):
    """Provides a temporary path for writing verifier telemetry JSONL records."""
    return tmp_path / "verifier_test.jsonl"


def test_verifier_telemetry_record_contains_eleven_required_fields():
    """Telemetry record must contain all 11 fields specified in OpenSpec."""
    run_id = str(uuid4())
    req_id = str(uuid4())

    record = TelemetryRecord(
        ts="2026-11-06T18:00:00Z",
        service="verifier",
        run_id=run_id,
        request_id=req_id,
        step=1,
        direction="outbound",
        endpoint_or_tool="GET https://example.com/job",
        status="fetched",
        latency_ms=110.5,
        attempt=1,
        tokens=0,
    )

    data = record.model_dump()
    required_fields = {
        "ts",
        "service",
        "run_id",
        "request_id",
        "step",
        "direction",
        "endpoint_or_tool",
        "status",
        "latency_ms",
        "attempt",
        "tokens",
    }
    assert required_fields.issubset(set(data.keys()))
    assert data["service"] == "verifier"
    assert data["direction"] == "outbound"


def test_verifier_telemetry_logger_emits_valid_jsonl(verifier_telemetry_log_path):
    """Telemetry logger must append valid single-line JSON records."""
    logger = TelemetryLogger(log_path=verifier_telemetry_log_path)
    run_id = str(uuid4())
    req_id = str(uuid4())

    logger.log_event(
        service="verifier",
        run_id=run_id,
        request_id=req_id,
        step=0,
        direction="inbound",
        endpoint_or_tool="POST /verify",
        status="complete",
        latency_ms=30.2,
        attempt=1,
        tokens=0,
    )

    logger.log_event(
        service="verifier",
        run_id=run_id,
        request_id=req_id,
        step=1,
        direction="outbound",
        endpoint_or_tool="model_evaluate_claim",
        status="success",
        latency_ms=250.0,
        attempt=1,
        tokens=500,
    )

    lines = verifier_telemetry_log_path.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 2

    r1 = json.loads(lines[0])
    assert r1["service"] == "verifier"
    assert r1["endpoint_or_tool"] == "POST /verify"
    assert r1["direction"] == "inbound"

    r2 = json.loads(lines[1])
    assert r2["service"] == "verifier"
    assert r2["endpoint_or_tool"] == "model_evaluate_claim"
    assert r2["tokens"] == 500
    assert r2["direction"] == "outbound"


def test_verifier_telemetry_strips_credentials_and_prompts(verifier_telemetry_log_path):
    """
    Spec requirement: Trace records SHALL exclude credentials and keys;
    absence of credentials or raw prompts.
    """
    logger = TelemetryLogger(log_path=verifier_telemetry_log_path)

    logger.log_event(
        service="verifier",
        run_id=str(uuid4()),
        request_id=str(uuid4()),
        step=1,
        direction="outbound",
        endpoint_or_tool="model_evaluate_claim",
        status="success",
        latency_ms=20.0,
        attempt=1,
        tokens=100,
        raw_prompt="System: You are an agent with secret key sk-verifier-secret-key-999",
        authorization="Bearer secret-token-xyz",
    )

    line = verifier_telemetry_log_path.read_text(encoding="utf-8")
    assert "sk-verifier-secret-key-999" not in line
    assert "secret-token-xyz" not in line
    assert "raw_prompt" not in json.loads(line)
    assert "authorization" not in json.loads(line)


def test_verifier_telemetry_null_ids_for_unauthenticated_requests(verifier_telemetry_log_path):
    """Unauthenticated or health requests without correlation IDs must record null IDs."""
    logger = TelemetryLogger(log_path=verifier_telemetry_log_path)
    logger.log_event(
        service="verifier",
        run_id=None,
        request_id=None,
        step=0,
        direction="inbound",
        endpoint_or_tool="GET /healthz",
        status="ok",
        latency_ms=0.5,
        attempt=1,
        tokens=0,
    )

    rec = json.loads(verifier_telemetry_log_path.read_text(encoding="utf-8").strip())
    assert rec["run_id"] is None
    assert rec["request_id"] is None
    assert rec["service"] == "verifier"
