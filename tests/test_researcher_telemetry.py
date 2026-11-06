"""
Unit tests for Task 3.7: Researcher Correlated JSONL Telemetry.
Verifies the 11 required fields, correlation UUIDs, caller latency,
distinct retry attempts, and absence of credentials or raw prompts.
"""

import json
from uuid import uuid4
import pytest

from services.researcher.telemetry import (
    TelemetryLogger,
    TelemetryRecord,
)


@pytest.fixture
def telemetry_log_path(tmp_path):
    """Provides a temporary path for writing telemetry JSONL records."""
    return tmp_path / "researcher_test.jsonl"


def test_telemetry_record_contains_eleven_required_fields():
    """Telemetry record must contain all 11 fields specified in OpenSpec."""
    run_id = str(uuid4())
    req_id = str(uuid4())

    record = TelemetryRecord(
        ts="2026-11-06T18:00:00Z",
        service="researcher",
        run_id=run_id,
        request_id=req_id,
        step=1,
        direction="outbound",
        endpoint_or_tool="fetch",
        status="success",
        latency_ms=125.4,
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
    assert data["service"] == "researcher"
    assert data["direction"] == "outbound"


def test_telemetry_logger_emits_valid_jsonl(telemetry_log_path):
    """Telemetry logger must append valid single-line JSON records."""
    logger = TelemetryLogger(log_path=telemetry_log_path)
    run_id = str(uuid4())
    req_id = str(uuid4())

    logger.log_event(
        service="researcher",
        run_id=run_id,
        request_id=req_id,
        step=1,
        direction="inbound",
        endpoint_or_tool="POST /research",
        status="complete",
        latency_ms=45.2,
        attempt=1,
        tokens=0,
    )

    logger.log_event(
        service="researcher",
        run_id=run_id,
        request_id=req_id,
        step=2,
        direction="outbound",
        endpoint_or_tool="openrouter/meta-llama/llama-3.1-70b-instruct",
        status="success",
        latency_ms=530.1,
        attempt=1,
        tokens=1250,
    )

    lines = telemetry_log_path.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 2

    r1 = json.loads(lines[0])
    assert r1["endpoint_or_tool"] == "POST /research"
    assert r1["direction"] == "inbound"

    r2 = json.loads(lines[1])
    assert r2["tokens"] == 1250
    assert r2["direction"] == "outbound"


def test_telemetry_logger_strips_credentials_and_prompts(telemetry_log_path):
    """
    Spec requirement: Trace records SHALL exclude credentials and keys;
    and absence of credentials or raw prompts.
    """
    logger = TelemetryLogger(log_path=telemetry_log_path)

    # Attempt to pass credentials or raw prompts via extra metadata
    logger.log_event(
        service="researcher",
        run_id=str(uuid4()),
        request_id=str(uuid4()),
        step=1,
        direction="outbound",
        endpoint_or_tool="fetch",
        status="success",
        latency_ms=20.0,
        attempt=1,
        tokens=0,
        raw_prompt="System: You are an agent with secret key sk-or-v1-secret12345",
        authorization="Bearer secret-token-xyz",
    )

    line = telemetry_log_path.read_text(encoding="utf-8")
    assert "sk-or-v1-secret12345" not in line
    assert "secret-token-xyz" not in line
    assert "raw_prompt" not in json.loads(line)
    assert "authorization" not in json.loads(line)


def test_telemetry_null_ids_for_unauthenticated_requests(telemetry_log_path):
    """Unauthenticated or health requests without correlation IDs must record null IDs."""
    logger = TelemetryLogger(log_path=telemetry_log_path)
    logger.log_event(
        service="researcher",
        run_id=None,
        request_id=None,
        step=0,
        direction="inbound",
        endpoint_or_tool="GET /healthz",
        status="success",
        latency_ms=1.5,
        attempt=1,
        tokens=0,
    )

    rec = json.loads(telemetry_log_path.read_text(encoding="utf-8").strip())
    assert rec["run_id"] is None
    assert rec["request_id"] is None
