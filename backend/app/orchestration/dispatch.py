"""
HTTP Dispatcher for Researcher and Verifier worker services.
Implements cold-start timeouts, bounded exponential backoff, Retry-After handling,
overall run deadlines, and response validation according to OpenSpec.
CSCI-GA.2630 Assignment 2
"""

from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import json
import os
import time
from typing import Any, Dict, Generic, List, Optional, Set, TypeVar
from uuid import UUID, uuid4
import httpx
from pydantic import BaseModel, Field

from shared.config import (
    FORBIDDEN_RETRY_STATUS_CODES,
    BudgetsConfig,
    ClaimsConfig,
    DeadlinesConfig,
    RetriesConfig,
    load_orchestration_config,
)
from shared.contracts import (
    ResearchPayload,
    ResearchRequest,
    ResearchResponse,
    ResourceBudget,
    ResourceUsage,
    VerifyClaimInput,
    VerifyPayload,
    VerifyRequest,
    VerifyResponse,
    validate_research_response,
    validate_verify_response,
)

TResponse = TypeVar("TResponse")


class DispatchResult(BaseModel, Generic[TResponse]):
    """Outcome of worker HTTP dispatch including attempts, status, and validated response."""

    success: bool = Field(description="Whether a valid complete/partial response was obtained")
    response: Optional[TResponse] = Field(default=None, description="Validated response if successful")
    status_code: Optional[int] = Field(default=None, description="HTTP response status code if received")
    error_code: Optional[str] = Field(default=None, description="Error code if failed or invalid")
    error_message: Optional[str] = Field(default=None, description="Explanatory error details")
    attempts: int = Field(default=0, ge=0, description="Number of HTTP attempts made")
    measured_usage: Optional[ResourceUsage] = Field(default=None, description="Reported usage if valid")
    request_id: Optional[UUID] = Field(default=None, description="Correlated request UUID")


def _parse_retry_after(header_val: Optional[str]) -> Optional[float]:
    """Parses Retry-After header as either seconds (int/float) or HTTP-date."""
    if not header_val:
        return None
    header_val = header_val.strip()
    try:
        return max(0.0, float(header_val))
    except ValueError:
        pass

    try:
        dt = parsedate_to_datetime(header_val)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        diff = (dt - datetime.now(timezone.utc)).total_seconds()
        return max(0.0, diff)
    except Exception:
        return None


class WorkerDispatcher:
    """Dispatches HTTP requests to Researcher and Verifier services with retries and bounds."""

    def __init__(
        self,
        researcher_url: Optional[str] = None,
        verifier_url: Optional[str] = None,
        researcher_token: Optional[str] = None,
        verifier_token: Optional[str] = None,
        budgets: Optional[BudgetsConfig] = None,
        deadlines: Optional[DeadlinesConfig] = None,
        retries: Optional[RetriesConfig] = None,
        claims: Optional[ClaimsConfig] = None,
        telemetry_logger: Any = None,
    ):
        cfg = load_orchestration_config()
        self.researcher_url = (
            researcher_url
            or os.environ.get("RESEARCHER_URL")
            or "http://127.0.0.1:8001"
        ).rstrip("/")
        self.verifier_url = (
            verifier_url
            or os.environ.get("VERIFIER_URL")
            or "http://127.0.0.1:8002"
        ).rstrip("/")
        res_tok = researcher_token or os.environ.get("RESEARCHER_TOKEN")
        if not res_tok:
            import sys
            if os.environ.get("TESTING") == "1" or "pytest" in sys.modules:
                res_tok = "test-researcher-token"
            else:
                raise ValueError("Missing required environment variable: RESEARCHER_TOKEN")
        self.researcher_token = res_tok

        ver_tok = verifier_token or os.environ.get("VERIFIER_TOKEN")
        if not ver_tok:
            import sys
            if os.environ.get("TESTING") == "1" or "pytest" in sys.modules:
                ver_tok = "test-verifier-token"
            else:
                raise ValueError("Missing required environment variable: VERIFIER_TOKEN")
        self.verifier_token = ver_tok
        self.budgets = budgets or cfg.budgets
        self.deadlines = deadlines or cfg.deadlines
        self.retries = retries or cfg.retries
        self.claims = claims or cfg.claims
        self.telemetry_logger = telemetry_logger

    def _send_http_attempt(
        self,
        url: str,
        headers: Dict[str, str],
        content: bytes,
        timeout: float,
    ) -> httpx.Response:
        """Sends a single HTTP attempt. Kept as an overridable method for tests."""
        # Timeout configured as full read/connect/write timeout for cold starts
        client_timeout = httpx.Timeout(
            timeout=timeout,
            connect=min(60.0, timeout),
            read=timeout,
            write=30.0,
            pool=30.0,
        )
        with httpx.Client(timeout=client_timeout) as client:
            return client.post(url, headers=headers, content=content)

    def dispatch_research(
        self,
        run_id: UUID,
        topic: str,
        k: int,
        start_run_time: float,
        request_id: Optional[UUID] = None,
    ) -> DispatchResult[ResearchResponse]:
        """Dispatches research job to Researcher service over HTTP."""
        req_id = request_id or uuid4()
        budget = self.budgets.researcher
        envelope = ResearchRequest(
            request_id=req_id,
            run_id=run_id,
            time_budget_ms=self.deadlines.worker_timeout_seconds * 1000,
            budget=budget,
            payload=ResearchPayload(topic=topic, k=k),
        )

        body_bytes = envelope.model_dump_json().encode("utf-8")
        headers = {
            "Authorization": f"Bearer {self.researcher_token}",
            "Content-Type": "application/json",
        }
        url = f"{self.researcher_url}/research"

        def validator(raw_json_str: str) -> ResearchResponse:
            resp = ResearchResponse.model_validate_json(raw_json_str)
            validate_research_response(
                response=resp,
                expected_request_id=req_id,
                expected_run_id=run_id,
                budget=budget,
                max_claims_per_dev=self.claims.max_per_development,
            )
            return resp

        return self._dispatch_loop(
            service_name="researcher",
            url=url,
            headers=headers,
            body_bytes=body_bytes,
            req_id=req_id,
            run_id=run_id,
            start_run_time=start_run_time,
            validator=validator,
        )

    def dispatch_verify(
        self,
        run_id: UUID,
        claims: List[VerifyClaimInput],
        start_run_time: float,
        request_id: Optional[UUID] = None,
    ) -> DispatchResult[VerifyResponse]:
        """Dispatches claims to Verifier service over HTTP."""
        req_id = request_id or uuid4()
        budget = self.budgets.verifier
        envelope = VerifyRequest(
            request_id=req_id,
            run_id=run_id,
            time_budget_ms=self.deadlines.worker_timeout_seconds * 1000,
            budget=budget,
            payload=VerifyPayload(claims=claims),
        )

        body_bytes = envelope.model_dump_json().encode("utf-8")
        headers = {
            "Authorization": f"Bearer {self.verifier_token}",
            "Content-Type": "application/json",
        }
        url = f"{self.verifier_url}/verify"
        expected_claim_ids: Set[str] = {c.claim_id for c in claims}

        def validator(raw_json_str: str) -> VerifyResponse:
            resp = VerifyResponse.model_validate_json(raw_json_str)
            validate_verify_response(
                response=resp,
                expected_request_id=req_id,
                expected_run_id=run_id,
                expected_claim_ids=expected_claim_ids,
                budget=budget,
            )
            return resp

        return self._dispatch_loop(
            service_name="verifier",
            url=url,
            headers=headers,
            body_bytes=body_bytes,
            req_id=req_id,
            run_id=run_id,
            start_run_time=start_run_time,
            validator=validator,
        )

    def _dispatch_loop(
        self,
        service_name: str,
        url: str,
        headers: Dict[str, str],
        body_bytes: bytes,
        req_id: UUID,
        run_id: UUID,
        start_run_time: float,
        validator: Any,
    ) -> DispatchResult[Any]:
        """
        Executes bounded attempts against a worker endpoint.
        Retries only network errors, timeouts, and HTTP 503.
        Aborts if an attempt cannot fit in remaining run window.
        """
        attempt = 1
        max_attempts = self.retries.max_attempts
        attempt_timeout = float(self.deadlines.attempt_timeout_seconds)
        max_run_dispatch_window = float(
            self.deadlines.run_timeout_seconds - self.deadlines.finalization_reserve_seconds
        )

        last_status_code: Optional[int] = None
        last_error_code: Optional[str] = None
        last_error_message: Optional[str] = None

        while attempt <= max_attempts:
            # Check if this attempt fits in the remaining run execution window
            elapsed_run = time.monotonic() - start_run_time
            if elapsed_run + attempt_timeout > max_run_dispatch_window:
                return DispatchResult(
                    success=False,
                    response=None,
                    status_code=last_status_code,
                    error_code="run_timeout_exceeded",
                    error_message=(
                        f"Attempt {attempt} would exceed available run execution window "
                        f"({elapsed_run:.1f}s + {attempt_timeout:.1f}s > {max_run_dispatch_window:.1f}s)"
                    ),
                    attempts=attempt - 1 if attempt > 1 else 0,
                    request_id=req_id,
                )

            # Send HTTP attempt
            t0 = time.monotonic()
            http_resp: Optional[httpx.Response] = None
            exception_occurred = False
            exc_desc = ""

            try:
                http_resp = self._send_http_attempt(
                    url=url,
                    headers=headers,
                    content=body_bytes,
                    timeout=attempt_timeout,
                )
            except (httpx.TimeoutException, httpx.NetworkError) as e:
                exception_occurred = True
                exc_desc = str(e) or e.__class__.__name__

            latency_ms = (time.monotonic() - t0) * 1000.0

            # Telemetry logging if logger available
            if self.telemetry_logger:
                status_str = str(http_resp.status_code) if http_resp else "network_error"
                self.telemetry_logger.log_event(
                    service="orchestrator",
                    run_id=str(run_id),
                    request_id=str(req_id),
                    step=0,
                    direction="outbound",
                    endpoint_or_tool=f"{service_name}:{url}",
                    status=status_str,
                    latency_ms=latency_ms,
                    attempt=attempt,
                    tokens=0,
                )

            if exception_occurred:
                last_status_code = None
                last_error_code = "network_or_timeout_error"
                last_error_message = exc_desc

                if attempt >= max_attempts:
                    break

                # Exponential backoff delay
                backoff_delay = self.retries.backoff_initial_seconds * (
                    self.retries.backoff_factor ** (attempt - 1)
                )
                # Check run window with backoff
                if time.monotonic() - start_run_time + backoff_delay + attempt_timeout > max_run_dispatch_window:
                    return DispatchResult(
                        success=False,
                        response=None,
                        status_code=None,
                        error_code="run_timeout_exceeded",
                        error_message="Insufficient run execution window for retry after network error",
                        attempts=attempt,
                        request_id=req_id,
                    )

                time.sleep(backoff_delay)
                attempt += 1
                continue

            assert http_resp is not None
            status_code = http_resp.status_code
            last_status_code = status_code

            # Status 200: Validate response
            if status_code == 200:
                try:
                    content_bytes = http_resp.content
                    if isinstance(content_bytes, (bytes, bytearray)):
                        raw_json_str = content_bytes.decode("utf-8")
                    else:
                        raw_json_str = str(content_bytes)

                    parsed = validator(raw_json_str)
                    return DispatchResult(
                        success=True,
                        response=parsed,
                        status_code=200,
                        attempts=attempt,
                        measured_usage=parsed.usage,
                        request_id=req_id,
                    )
                except Exception as val_err:
                    # Invalid response content: discard entire response, do not retry
                    return DispatchResult(
                        success=False,
                        response=None,
                        status_code=200,
                        error_code="validation_failure",
                        error_message=f"Worker response failed validation: {val_err}",
                        attempts=attempt,
                        request_id=req_id,
                    )

            # Terminal status codes: never retried
            if status_code in FORBIDDEN_RETRY_STATUS_CODES or status_code not in self.retries.retryable_status_codes:
                return DispatchResult(
                    success=False,
                    response=None,
                    status_code=status_code,
                    error_code=f"http_{status_code}",
                    error_message=f"Worker returned terminal status {status_code}",
                    attempts=attempt,
                    request_id=req_id,
                )

            # HTTP 503: retryable
            if status_code == 503:
                last_error_code = "service_unavailable_503"
                last_error_message = "Worker returned 503 Service Unavailable"

                if attempt >= max_attempts:
                    break

                retry_after_hdr = http_resp.headers.get("Retry-After") if hasattr(http_resp, "headers") else None
                parsed_ra = _parse_retry_after(retry_after_hdr)
                if parsed_ra is not None:
                    backoff_delay = parsed_ra
                else:
                    backoff_delay = self.retries.backoff_initial_seconds * (
                        self.retries.backoff_factor ** (attempt - 1)
                    )

                # Check if retry fits in run window
                if time.monotonic() - start_run_time + backoff_delay + attempt_timeout > max_run_dispatch_window:
                    return DispatchResult(
                        success=False,
                        response=None,
                        status_code=503,
                        error_code="run_timeout_exceeded",
                        error_message="Retry-After/backoff delay exceeds remaining run execution window",
                        attempts=attempt,
                        request_id=req_id,
                    )

                time.sleep(backoff_delay)
                attempt += 1
                continue

            # Any other unconfigured status code: treat as failure and do not retry
            return DispatchResult(
                success=False,
                response=None,
                status_code=status_code,
                error_code=f"http_{status_code}",
                error_message=f"Worker returned unexpected non-retryable status {status_code}",
                attempts=attempt,
                request_id=req_id,
            )

        # Max attempts exhausted
        return DispatchResult(
            success=False,
            response=None,
            status_code=last_status_code,
            error_code=last_error_code or "max_attempts_exhausted",
            error_message=last_error_message or f"Exhausted all {max_attempts} attempts",
            attempts=min(attempt, max_attempts),
            request_id=req_id,
        )
