"""
Wire contracts and protocol schemas for Three-Service Agentic Orchestration.
CSCI-GA.2630 Assignment 2
"""

from typing import Generic, List, Literal, Optional, Set, TypeVar
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictBaseModel(BaseModel):
    """Base model enforcing strict types and forbidding unknown extra fields."""

    model_config = ConfigDict(extra="forbid", strict=True)


class ResourceBudget(StrictBaseModel):
    """Resource allocations passed in worker request envelopes."""

    max_steps: int = Field(ge=0, description="Maximum model calls allocated")
    max_fetches: int = Field(ge=0, description="Maximum web fetches allocated")
    max_tokens: int = Field(ge=0, description="Maximum tokens allocated")


class ResourceUsage(StrictBaseModel):
    """Resource consumption reported in worker response envelopes."""

    steps: int = Field(ge=0, description="Actual model calls consumed")
    fetches: int = Field(ge=0, description="Actual web fetches consumed")
    tokens: int = Field(ge=0, description="Actual tokens consumed")

    def exceeds(self, budget: ResourceBudget) -> bool:
        """Returns True if any consumed resource exceeds the allocated budget."""
        return (
            self.steps > budget.max_steps
            or self.fetches > budget.max_fetches
            or self.tokens > budget.max_tokens
        )


class WorkerError(StrictBaseModel):
    """Error payload reported on partial or failed worker outcomes."""

    code: str = Field(min_length=1, description="Machine-readable error code")
    message: str = Field(min_length=1, description="Explanatory error description")
    retryable: bool = Field(description="Whether the failure is transient and retryable")


TPayload = TypeVar("TPayload", bound=StrictBaseModel)


class WorkerRequestEnvelope(StrictBaseModel, Generic[TPayload]):
    """Standard request envelope for worker POST endpoints."""

    request_id: UUID = Field(description="Per-dispatch unique request UUID")
    run_id: UUID = Field(description="Enclosing run UUID")
    time_budget_ms: int = Field(gt=0, description="Positive execution deadline in milliseconds")
    budget: ResourceBudget = Field(description="Allocated step/fetch/token resources")
    payload: TPayload = Field(description="Endpoint-specific payload")


class ResearchPayload(StrictBaseModel):
    """Payload sent to Researcher POST /research."""

    topic: str = Field(min_length=1, description="Research search topic")
    k: int = Field(ge=3, le=10, description="Target number of ranked developments")


class VerifyClaimInput(StrictBaseModel):
    """Isolated claim representation sent to Verifier POST /verify."""

    claim_id: str = Field(min_length=1, description="Run-unique claim identifier")
    text: str = Field(min_length=1, description="Claim text statement")
    source_url: str = Field(min_length=1, description="Cited primary source URL")


class VerifyPayload(StrictBaseModel):
    """Payload sent to Verifier POST /verify."""

    claims: List[VerifyClaimInput] = Field(description="List of claims to verify independently")


ResearchRequest = WorkerRequestEnvelope[ResearchPayload]
VerifyRequest = WorkerRequestEnvelope[VerifyPayload]


class JobMetadata(StrictBaseModel):
    """Explicitly typed optional job metadata needed for UI cards."""

    company: Optional[str] = None
    primary_url: Optional[str] = None
    location: Optional[str] = None
    compensation: Optional[str] = None
    qualifications_summary: Optional[str] = None
    fingerprint: Optional[str] = None


class ArticleAudit(StrictBaseModel):
    """Source fetch audit entry attributed to a specific worker."""

    source_url: str = Field(min_length=1, description="Target URL")
    title: Optional[str] = None
    worker: Literal["researcher", "verifier"] = Field(description="Originating worker service")
    status: str = Field(min_length=1, description="Fetch or rejection status")
    latency_ms: Optional[float] = None
    error: Optional[str] = None


class AtomicClaim(StrictBaseModel):
    """Atomic cited claim discovered by Researcher."""

    claim_id: str = Field(min_length=1, description="Run-unique claim identifier")
    text: str = Field(min_length=1, description="Atomic claim text")
    source_url: str = Field(min_length=1, description="Source URL where claim was found")


class Development(JobMetadata):
    """Ranked job development produced by Researcher, inheriting typed job metadata."""

    id: str = Field(min_length=1, description="Development identifier")
    title: str = Field(min_length=1, description="Role title")
    summary: str = Field(min_length=1, description="Role summary")
    claims: List[AtomicClaim] = Field(min_length=1, description="Cited atomic claims (1 to 4)")


class ResearchResult(StrictBaseModel):
    """Result payload from Researcher."""

    developments: List[Development] = Field(description="Ranked job developments")
    articles: Optional[List[ArticleAudit]] = Field(default=None, description="Researcher article audit")

    @model_validator(mode="after")
    def validate_worker_attribution(self) -> "ResearchResult":
        if self.articles:
            for article in self.articles:
                if article.worker != "researcher":
                    raise ValueError(
                        f"ResearchResult articles must be attributed to 'researcher', got '{article.worker}'"
                    )
        return self


ClaimVerdictStatus = Literal["supported", "unsupported", "unreachable"]


class ClaimVerdict(StrictBaseModel):
    """Verdict evaluated by Verifier."""

    claim_id: str = Field(min_length=1, description="Target claim identifier")
    verdict: ClaimVerdictStatus = Field(description="Verification verdict (excluding unverified)")
    evidence: Optional[str] = Field(default=None, description="Normalized source excerpt for supported")

    @model_validator(mode="after")
    def validate_evidence_rules(self) -> "ClaimVerdict":
        if self.verdict == "supported":
            if not self.evidence or not self.evidence.strip():
                raise ValueError("Supported verdict must have nonblank evidence")
            if len(self.evidence) > 300:
                raise ValueError("Evidence exceeds maximum length of 300 characters")
        else:
            if self.evidence is not None:
                raise ValueError("Non-supported verdict must have null evidence")
        return self


class VerifyResult(StrictBaseModel):
    """Result payload from Verifier."""

    verdicts: List[ClaimVerdict] = Field(description="Claim verdicts")
    source_audit: Optional[List[ArticleAudit]] = Field(default=None, description="Verifier fetch audit")

    @model_validator(mode="after")
    def validate_worker_attribution(self) -> "VerifyResult":
        if self.source_audit:
            for audit in self.source_audit:
                if audit.worker != "verifier":
                    raise ValueError(
                        f"VerifyResult source_audit must be attributed to 'verifier', got '{audit.worker}'"
                    )
        return self


TResult = TypeVar("TResult", bound=StrictBaseModel)
WorkerStatus = Literal["complete", "partial", "failed"]


class WorkerResponseEnvelope(StrictBaseModel, Generic[TResult]):
    """Standard response envelope for worker operations."""

    request_id: UUID = Field(description="Echoed request UUID")
    run_id: UUID = Field(description="Echoed run UUID")
    status: WorkerStatus = Field(description="Operational completion status")
    result: Optional[TResult] = Field(default=None, description="Result payload if completed or partial")
    usage: ResourceUsage = Field(description="Actual resource usage consumed")
    error: Optional[WorkerError] = Field(default=None, description="Error detail if partial or failed")

    @model_validator(mode="after")
    def validate_status_error_consistency(self) -> "WorkerResponseEnvelope[TResult]":
        if self.status == "complete":
            if self.error is not None:
                raise ValueError("Complete response cannot carry an error")
            if self.result is None:
                raise ValueError("Complete response must have result payload")
        elif self.status == "partial":
            if self.error is None:
                raise ValueError("Partial response must carry an error")
            if self.error.retryable:
                raise ValueError("Partial response error must be non-retryable")
            if self.result is None:
                raise ValueError("Partial response must have result payload")
        elif self.status == "failed":
            if self.error is None:
                raise ValueError("Failed response must carry an error")
            if self.result is not None:
                raise ValueError("Failed response must have null result")
        return self


ResearchResponse = WorkerResponseEnvelope[ResearchResult]
VerifyResponse = WorkerResponseEnvelope[VerifyResult]


def _validate_envelope_and_budget(
    response: WorkerResponseEnvelope,
    expected_request_id: UUID,
    expected_run_id: UUID,
    budget: ResourceBudget,
) -> None:
    """Validates correlation UUIDs and ensures consumed usage remains within allocation."""
    if response.request_id != expected_request_id:
        raise ValueError(
            f"Response request_id does not match dispatch request_id: "
            f"got {response.request_id}, expected {expected_request_id}"
        )
    if response.run_id != expected_run_id:
        raise ValueError(
            f"Response run_id does not match dispatch run_id: "
            f"got {response.run_id}, expected {expected_run_id}"
        )
    if response.usage.exceeds(budget):
        raise ValueError(
            f"Usage exceeds allocated budget: usage={response.usage.model_dump()}, "
            f"budget={budget.model_dump()}"
        )


def validate_research_response(
    response: ResearchResponse,
    expected_request_id: UUID,
    expected_run_id: UUID,
    budget: ResourceBudget,
    max_claims_per_dev: int = 4,
) -> None:
    """
    Validates a Researcher operational response before persisting or using any content.
    Raises ValueError on any protocol violation.
    """
    _validate_envelope_and_budget(response, expected_request_id, expected_run_id, budget)

    if response.result is not None:
        seen_dev_ids: Set[str] = set()
        seen_claim_ids: Set[str] = set()

        for dev in response.result.developments:
            if dev.id in seen_dev_ids:
                raise ValueError(f"Duplicate development ID detected: {dev.id}")
            seen_dev_ids.add(dev.id)

            if len(dev.claims) < 1:
                raise ValueError(f"Development {dev.id} must have at least 1 claim")
            if len(dev.claims) > max_claims_per_dev:
                raise ValueError(
                    f"Development {dev.id} claims count exceeds maximum ({len(dev.claims)} > {max_claims_per_dev})"
                )

            for claim in dev.claims:
                if claim.claim_id in seen_claim_ids:
                    raise ValueError(f"Duplicate claim ID detected: {claim.claim_id}")
                seen_claim_ids.add(claim.claim_id)


def validate_verify_response(
    response: VerifyResponse,
    expected_request_id: UUID,
    expected_run_id: UUID,
    expected_claim_ids: Set[str],
    budget: ResourceBudget,
) -> None:
    """
    Validates a Verifier operational response before persisting or using any content.
    Raises ValueError on any protocol violation.
    """
    _validate_envelope_and_budget(response, expected_request_id, expected_run_id, budget)

    if response.result is not None:
        seen_claim_ids: Set[str] = set()
        for verdict in response.result.verdicts:
            if verdict.claim_id in seen_claim_ids:
                raise ValueError(f"Duplicate claim ID detected in verdicts: {verdict.claim_id}")
            seen_claim_ids.add(verdict.claim_id)

            if verdict.claim_id not in expected_claim_ids:
                raise ValueError(
                    f"Unknown claim ID detected in verifier response: {verdict.claim_id}"
                )

        if response.status == "complete":
            missing = expected_claim_ids - seen_claim_ids
            if missing:
                raise ValueError(
                    f"Complete verify response missing expected claims: {missing}"
                )
        elif response.status == "partial":
            # Partial coverage is allowed; missing claims will be assigned unverified by Orchestrator
            pass
