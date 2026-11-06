"""
FastAPI application for the Researcher Service.
CSCI-GA.2630 Assignment 2
"""

import json
import os
import time
from typing import Any, Dict, Optional
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from shared.contracts import (
    ResearchRequest,
    ResearchResponse,
    ResearchResult,
    ResourceUsage,
)
from services.researcher.idempotency import IdempotencyRegistry, canonical_request_hash
from services.researcher.runtime import execute_research
from services.researcher.telemetry import default_researcher_logger

app = FastAPI(title="Researcher Service", version="1.0.0")

# Process-lifetime singleton idempotency registry
idempotency_registry = IdempotencyRegistry()


def _get_configured_token() -> str:
    return os.environ.get("RESEARCHER_TOKEN", "")


def _log_inbound(
    status: str,
    latency_ms: float,
    run_id: Optional[str] = None,
    request_id: Optional[str] = None,
    step: int = 0,
    tokens: int = 0,
) -> None:
    """Helper to emit consistent inbound telemetry records."""
    default_researcher_logger.log_event(
        service="researcher",
        run_id=run_id,
        request_id=request_id,
        step=step,
        direction="inbound",
        endpoint_or_tool="POST /research",
        status=status,
        latency_ms=latency_ms,
        tokens=tokens,
    )


@app.get("/healthz")
async def healthz() -> Dict[str, str]:
    """Unauthenticated health check."""
    default_researcher_logger.log_event(
        service="researcher",
        run_id=None,
        request_id=None,
        step=0,
        direction="inbound",
        endpoint_or_tool="GET /healthz",
        status="ok",
        latency_ms=0.5,
    )
    return {"status": "ok"}


@app.post("/research")
async def research_endpoint(request: Request) -> Response:
    """
    POST /research endpoint:
    1. Validates Authorization Bearer token before parsing request body.
       Returns 401 on missing or invalid token.
    2. Parses raw JSON and validates against ResearchRequest.
       Returns 400 on malformed JSON or schema errors (not 422).
    3. Enforces process-local idempotency:
       - Identical payload while completed -> replays terminal response (including terminal 500).
       - Identical payload while in-flight -> returns 503 with Retry-After: 5.
       - Altered payload with same request_id -> returns 409 Conflict.
    4. Executes research and registers terminal result.
    """
    start_time = time.monotonic()

    # 1. Token validation before body parsing
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        latency_ms = round((time.monotonic() - start_time) * 1000, 2)
        _log_inbound(status="unauthorized", latency_ms=latency_ms)
        return JSONResponse(status_code=401, content={"detail": "Unauthorized: Missing Bearer token"})

    token = auth_header[len("Bearer ") :].strip()
    expected_token = _get_configured_token()
    if not expected_token or token != expected_token:
        latency_ms = round((time.monotonic() - start_time) * 1000, 2)
        _log_inbound(status="unauthorized", latency_ms=latency_ms)
        return JSONResponse(status_code=401, content={"detail": "Unauthorized: Invalid service token"})

    # 2. Parse and validate body against strict ResearchRequest schema
    body_bytes = await request.body()
    try:
        raw_json: Any = json.loads(body_bytes.decode("utf-8"))
    except Exception:
        latency_ms = round((time.monotonic() - start_time) * 1000, 2)
        _log_inbound(status="malformed_json", latency_ms=latency_ms)
        return JSONResponse(status_code=400, content={"detail": "Malformed JSON body"})

    try:
        req = ResearchRequest.model_validate_json(body_bytes)
    except ValidationError:
        latency_ms = round((time.monotonic() - start_time) * 1000, 2)
        _log_inbound(status="invalid_schema", latency_ms=latency_ms)
        return JSONResponse(status_code=400, content={"detail": "Invalid request schema"})

    # 3. Idempotency check
    body_hash = canonical_request_hash(raw_json)
    req_id_str = str(req.request_id)
    run_id_str = str(req.run_id)
    action, record = idempotency_registry.check_or_register(req_id_str, body_hash)

    if action == "conflict":
        latency_ms = round((time.monotonic() - start_time) * 1000, 2)
        _log_inbound(run_id=run_id_str, request_id=req_id_str, status="conflict", latency_ms=latency_ms)
        return JSONResponse(
            status_code=409,
            content={"detail": f"Conflict: Request {req_id_str} was previously registered with a different body"},
        )

    if action == "in_flight":
        latency_ms = round((time.monotonic() - start_time) * 1000, 2)
        _log_inbound(run_id=run_id_str, request_id=req_id_str, status="in_flight_503", latency_ms=latency_ms)
        return Response(
            status_code=503,
            headers={"Retry-After": "5", "Content-Type": "application/json"},
            content=json.dumps({"detail": "Service Unavailable: Request already in flight"}),
        )

    if action == "completed" and record is not None:
        latency_ms = round((time.monotonic() - start_time) * 1000, 2)
        _log_inbound(run_id=run_id_str, request_id=req_id_str, status="replayed", latency_ms=latency_ms)
        return Response(
            status_code=record.status_code,
            headers=record.headers,
            media_type="application/json",
            content=record.response_body,
        )

    # 4. Action == "new": execute research
    try:
        resp = execute_research(req)
        resp_bytes = resp.model_dump_json().encode("utf-8")
        resp_headers = {"Content-Type": "application/json"}
        idempotency_registry.complete(req_id_str, status_code=200, response_body=resp_bytes, headers=resp_headers)
        latency_ms = round((time.monotonic() - start_time) * 1000, 2)
        _log_inbound(
            run_id=run_id_str,
            request_id=req_id_str,
            step=resp.usage.steps,
            status=resp.status,
            latency_ms=latency_ms,
            tokens=resp.usage.tokens,
        )
        return Response(
            status_code=200,
            headers=resp_headers,
            media_type="application/json",
            content=resp_bytes,
        )
    except Exception as e:
        latency_ms = round((time.monotonic() - start_time) * 1000, 2)
        err_body = json.dumps({"detail": f"Internal server error: {e}"}).encode("utf-8")
        err_headers = {"Content-Type": "application/json"}
        idempotency_registry.complete(req_id_str, status_code=500, response_body=err_body, headers=err_headers)
        _log_inbound(
            run_id=run_id_str,
            request_id=req_id_str,
            step=0,
            status="failed_500",
            latency_ms=latency_ms,
        )
        return Response(
            status_code=500,
            headers=err_headers,
            media_type="application/json",
            content=err_body,
        )
