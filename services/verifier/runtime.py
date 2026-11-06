"""
Request-local execution runtime, resource accounting, URL grouping, and evaluation for Verifier.
CSCI-GA.2630 Assignment 2
"""

import ipaddress
import time
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

from shared.contracts import (
    ArticleAudit,
    ClaimVerdict,
    ResourceBudget,
    ResourceUsage,
    VerifyClaimInput,
    VerifyRequest,
    VerifyResponse,
    VerifyResult,
    WorkerError,
)
from services.verifier.evaluator import evaluate_claim_against_source
from services.verifier.fetch import FetchResult, guarded_fetch, validate_destination_ip
from services.verifier.telemetry import default_verifier_logger


class RequestTracker:
    """
    Request-local monotonic clock and resource counter.
    Enforces conservative pre-call token reservations, redirect hop counting,
    and remaining-deadline checks.
    """

    def __init__(self, budget: ResourceBudget, time_budget_ms: int):
        self.budget = budget
        self.time_budget_ms = time_budget_ms
        self.start_monotonic = time.monotonic()
        self.deadline_monotonic = self.start_monotonic + (time_budget_ms / 1000.0)

        # Operational counters
        self.steps: int = 0
        self.fetches: int = 0
        self.tokens: int = 0

    def remaining_time_seconds(self) -> float:
        """Returns remaining execution window in seconds."""
        return max(0.0, self.deadline_monotonic - time.monotonic())

    def has_remaining_time(self) -> bool:
        """Checks whether monotonic execution window is unexpired."""
        return self.remaining_time_seconds() > 0.0

    def can_fetch(self) -> Tuple[bool, Optional[str]]:
        """Validates if another page fetch can be initiated."""
        if self.fetches + 1 > self.budget.max_fetches:
            return False, f"Fetch limit reached ({self.fetches}/{self.budget.max_fetches})"
        return True, None

    def can_call_model(self, conservative_token_bound: int = 2000) -> Tuple[bool, Optional[str]]:
        """
        Validates if model call can be dispatched.
        Requires that BOTH step count + 1 and tokens + conservative_token_bound fit within allocation.
        """
        if self.steps + 1 > self.budget.max_steps:
            return False, f"Step limit reached ({self.steps}/{self.budget.max_steps})"

        if self.tokens + conservative_token_bound > self.budget.max_tokens:
            return (
                False,
                f"Token reservation {conservative_token_bound} exceeds remaining budget "
                f"({self.tokens}/{self.budget.max_tokens})",
            )

        return True, None

    def record_fetch(self, redirect_hops: int = 0) -> None:
        """Records initial fetch attempt plus any redirect hops."""
        self.fetches += 1 + redirect_hops

    def record_model_call(self, tokens: int = 500) -> None:
        """Records a model execution step and consumed tokens."""
        self.steps += 1
        self.tokens += tokens

    def to_usage(self) -> ResourceUsage:
        """Constructs ResourceUsage payload for worker response."""
        return ResourceUsage(
            steps=self.steps,
            fetches=self.fetches,
            tokens=self.tokens,
        )


def _is_direct_prohibited_url(url: str) -> bool:
    """Checks if a URL directly targets localhost, private network, or cloud metadata."""
    try:
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        if host in ("localhost", "127.0.0.1", "::1", "169.254.169.254"):
            return True
        try:
            ip = ipaddress.ip_address(host)
            is_safe, _ = validate_destination_ip(str(ip))
            if not is_safe:
                return True
        except ValueError:
            # host is a domain name, not an IP literal
            pass
    except Exception:
        pass
    return False


def _make_partial_response(
    req: VerifyRequest,
    tracker: RequestTracker,
    verdicts: List[ClaimVerdict],
    audits: List[ArticleAudit],
    code: str,
    message: str,
) -> VerifyResponse:
    return VerifyResponse(
        request_id=req.request_id,
        run_id=req.run_id,
        status="partial",
        result=VerifyResult(verdicts=verdicts, source_audit=audits),
        usage=tracker.to_usage(),
        error=WorkerError(
            code=code,
            message=message,
            retryable=False,
        ),
    )


def execute_verification(
    req: VerifyRequest,
    telemetry_logger: Optional[Any] = None,
    model_client: Optional[Any] = None,
) -> VerifyResponse:
    """
    Executes claim verification adhering to Assignment 2 specifications:
    1. Enforces request-local resource allocations and monotonic deadline.
    2. Groups claims by exact identical source_url to fetch each source at most once.
    3. Detects direct prohibited URLs (localhost, metadata) and marks them unreachable without fetch budget.
    4. Guarded fetch with SSRF check, redirect counting, and streaming caps.
    5. Evaluates claims independently; model failures do NOT become fabricated unreachable verdicts.
    6. Code evidence verification and normalization.
    7. Unprocessed claims on budget/time exhaustion remain absent so Orchestrator can mark unverified.
    """
    logger = telemetry_logger or default_verifier_logger
    tracker = RequestTracker(budget=req.budget, time_budget_ms=req.time_budget_ms)

    # Check for immediate deadline exhaustion
    if not tracker.has_remaining_time() or req.time_budget_ms < 100:
        return _make_partial_response(
            req, tracker, [], [], "time_budget_exhausted", "Monotonic execution deadline reached"
        )

    # Group claims by exact source_url (preserving order)
    grouped_claims: Dict[str, List[VerifyClaimInput]] = {}
    for claim in req.payload.claims:
        grouped_claims.setdefault(claim.source_url, []).append(claim)

    processed_verdicts: List[ClaimVerdict] = []
    source_audits: List[ArticleAudit] = []

    for source_url, claims_for_source in grouped_claims.items():
        # Check remaining deadline
        if not tracker.has_remaining_time():
            return _make_partial_response(
                req, tracker, processed_verdicts, source_audits, "time_budget_exhausted", "Monotonic execution deadline reached"
            )

        # Check direct prohibited SSRF targets (spec: return unreachable without fetch decrement)
        if _is_direct_prohibited_url(source_url):
            source_audits.append(
                ArticleAudit(
                    source_url=source_url,
                    worker="verifier",
                    status="rejected",
                    error="Direct prohibited SSRF destination rejected without connection",
                )
            )
            for c in claims_for_source:
                processed_verdicts.append(
                    ClaimVerdict(claim_id=c.claim_id, verdict="unreachable", evidence=None)
                )
            continue

        # Check fetch budget
        can_fetch, fetch_err = tracker.can_fetch()
        if not can_fetch:
            return _make_partial_response(
                req, tracker, processed_verdicts, source_audits, "fetch_budget_exhausted", fetch_err or "Fetch budget exhausted"
            )

        # Execute guarded fetch
        remaining_fetches = tracker.budget.max_fetches - tracker.fetches
        fetch_res = guarded_fetch(
            url=source_url,
            remaining_deadline_seconds=tracker.remaining_time_seconds(),
            remaining_fetches=remaining_fetches,
            telemetry_logger=logger,
            run_id=str(req.run_id),
            request_id=str(req.request_id),
            step=tracker.steps,
        )

        # Only count fetch if a connection was actually attempted (blocked URLs consume no page request)
        if fetch_res.status != "rejected":
            tracker.record_fetch(fetch_res.redirect_hops)

        source_audits.append(
            ArticleAudit(
                source_url=source_url,
                worker="verifier",
                status=fetch_res.status,
                latency_ms=float(fetch_res.latency_ms),
                error=fetch_res.error,
            )
        )

        # If source fetch failed or was rejected, classify claims as unreachable
        if fetch_res.status != "fetched":
            for c in claims_for_source:
                processed_verdicts.append(
                    ClaimVerdict(claim_id=c.claim_id, verdict="unreachable", evidence=None)
                )
            continue

        # Source successfully fetched: evaluate each claim
        for c in claims_for_source:
            if not tracker.has_remaining_time():
                return _make_partial_response(
                    req, tracker, processed_verdicts, source_audits, "time_budget_exhausted", "Monotonic execution deadline reached"
                )

            if model_client is not None:
                can_call, model_err = tracker.can_call_model()
                if not can_call:
                    return _make_partial_response(
                        req, tracker, processed_verdicts, source_audits, "step_budget_exhausted", model_err or "Model step or token budget exhausted"
                    )

            # Evaluate claim against page content
            eval_start = time.monotonic()
            try:
                verdict, evidence = evaluate_claim_against_source(
                    claim_text=c.text,
                    page_text=fetch_res.content,
                    model_client=model_client,
                )
            except Exception as e:
                eval_latency = round((time.monotonic() - eval_start) * 1000, 2)
                if model_client is not None:
                    logger.log_event(
                        service="verifier",
                        run_id=str(req.run_id),
                        request_id=str(req.request_id),
                        step=tracker.steps,
                        direction="outbound",
                        endpoint_or_tool="model_evaluate_claim",
                        status="error",
                        latency_ms=eval_latency,
                        tokens=0,
                    )
                # Spec: Model failure does not become fabricated unreachable!
                # Unprocessed claims remain absent for Orchestrator to mark unverified
                return _make_partial_response(
                    req, tracker, processed_verdicts, source_audits, "model_failure", f"Model evaluation failed: {e}"
                )

            eval_latency = round((time.monotonic() - eval_start) * 1000, 2)
            if model_client is not None:
                tracker.record_model_call(tokens=500)
                logger.log_event(
                    service="verifier",
                    run_id=str(req.run_id),
                    request_id=str(req.request_id),
                    step=tracker.steps,
                    direction="outbound",
                    endpoint_or_tool="model_evaluate_claim",
                    status="success",
                    latency_ms=eval_latency,
                    tokens=500,
                )

            if verdict not in ("supported", "unsupported", "unreachable"):
                verdict = "unsupported"
            processed_verdicts.append(
                ClaimVerdict(
                    claim_id=c.claim_id,
                    verdict=verdict,  # type: ignore
                    evidence=evidence,
                )
            )

    # Determine final response status
    total_requested = len(req.payload.claims)
    if len(processed_verdicts) == total_requested:
        return VerifyResponse(
            request_id=req.request_id,
            run_id=req.run_id,
            status="complete",
            result=VerifyResult(verdicts=processed_verdicts, source_audit=source_audits),
            usage=tracker.to_usage(),
            error=None,
        )

    # Partial results when not all claims could be processed
    return _make_partial_response(
        req, tracker, processed_verdicts, source_audits, "budget_exhausted", "Verification concluded with partial results within allocation"
    )
