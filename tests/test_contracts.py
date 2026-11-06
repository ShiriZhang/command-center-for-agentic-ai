"""
Tests for shared/contracts.py wire schemas, validation boundaries,
and protocol invariants according to OpenSpec agentic-orchestration.
"""

from uuid import UUID, uuid4
import pytest
from pydantic import ValidationError

from shared.contracts import (
    AtomicClaim,
    ArticleAudit,
    ClaimVerdict,
    Development,
    JobMetadata,
    ResearchPayload,
    ResearchRequest,
    ResearchResponse,
    ResearchResult,
    ResourceBudget,
    ResourceUsage,
    VerifyClaimInput,
    VerifyPayload,
    VerifyRequest,
    VerifyResponse,
    VerifyResult,
    WorkerError,
    validate_research_response,
    validate_verify_response,
)


class TestRequestEnvelopeAndPayloads:
    def test_valid_research_request(self):
        req_id = uuid4()
        run_id = uuid4()
        req = ResearchRequest(
            request_id=req_id,
            run_id=run_id,
            time_budget_ms=120000,
            budget=ResourceBudget(max_steps=18, max_fetches=20, max_tokens=60000),
            payload=ResearchPayload(topic="AI/ML jobs", k=10),
        )
        assert req.request_id == req_id
        assert req.run_id == run_id
        assert req.time_budget_ms == 120000
        assert req.budget.max_steps == 18
        assert req.payload.k == 10

    def test_time_budget_must_be_positive(self):
        with pytest.raises(ValidationError):
            ResearchRequest(
                request_id=uuid4(),
                run_id=uuid4(),
                time_budget_ms=0,
                budget=ResourceBudget(max_steps=18, max_fetches=20, max_tokens=60000),
                payload=ResearchPayload(topic="AI/ML jobs", k=10),
            )

    def test_budget_allocations_cannot_be_negative(self):
        with pytest.raises(ValidationError):
            ResourceBudget(max_steps=-1, max_fetches=20, max_tokens=60000)

    def test_reject_unknown_fields(self):
        with pytest.raises(ValidationError):
            ResearchRequest(
                request_id=uuid4(),
                run_id=uuid4(),
                time_budget_ms=120000,
                budget=ResourceBudget(max_steps=18, max_fetches=20, max_tokens=60000),
                payload=ResearchPayload(topic="AI/ML jobs", k=10),
                unexpected_extra_field="malicious",  # type: ignore
            )

    def test_strict_types_no_scalar_coercion(self):
        # Strict mode prevents string-to-int coercion
        with pytest.raises(ValidationError):
            ResourceBudget(max_steps="18", max_fetches=20, max_tokens=60000)  # type: ignore

    def test_invalid_uuid_rejected(self):
        with pytest.raises(ValidationError):
            ResearchRequest(
                request_id="not-a-valid-uuid",  # type: ignore
                run_id=uuid4(),
                time_budget_ms=120000,
                budget=ResourceBudget(max_steps=18, max_fetches=20, max_tokens=60000),
                payload=ResearchPayload(topic="AI/ML jobs", k=10),
            )


class TestResponseEnvelopeAndStatusConsistency:
    def test_valid_complete_response(self):
        req_id = uuid4()
        run_id = uuid4()
        resp = ResearchResponse(
            request_id=req_id,
            run_id=run_id,
            status="complete",
            result=ResearchResult(developments=[]),
            usage=ResourceUsage(steps=5, fetches=3, tokens=1200),
            error=None,
        )
        assert resp.status == "complete"
        assert resp.error is None
        assert resp.result is not None

    def test_complete_response_cannot_have_error(self):
        with pytest.raises(ValidationError, match="Complete response cannot carry an error"):
            ResearchResponse(
                request_id=uuid4(),
                run_id=uuid4(),
                status="complete",
                result=ResearchResult(developments=[]),
                usage=ResourceUsage(steps=5, fetches=3, tokens=1200),
                error=WorkerError(code="SOME_ERR", message="Oops", retryable=False),
            )

    def test_valid_partial_response_requires_non_retryable_error(self):
        resp = ResearchResponse(
            request_id=uuid4(),
            run_id=uuid4(),
            status="partial",
            result=ResearchResult(developments=[]),
            usage=ResourceUsage(steps=18, fetches=20, tokens=60000),
            error=WorkerError(
                code="time_budget_exhausted",
                message="Deadline reached",
                retryable=False,
            ),
        )
        assert resp.status == "partial"
        assert resp.error is not None
        assert resp.error.retryable is False

    def test_partial_response_cannot_have_retryable_error(self):
        with pytest.raises(ValidationError, match="Partial response error must be non-retryable"):
            ResearchResponse(
                request_id=uuid4(),
                run_id=uuid4(),
                status="partial",
                result=ResearchResult(developments=[]),
                usage=ResourceUsage(steps=10, fetches=5, tokens=20000),
                error=WorkerError(
                    code="transient_network_error",
                    message="Network timeout",
                    retryable=True,
                ),
            )

    def test_partial_response_requires_result_present(self):
        with pytest.raises(ValidationError, match="Partial response must have result payload"):
            ResearchResponse(
                request_id=uuid4(),
                run_id=uuid4(),
                status="partial",
                result=None,
                usage=ResourceUsage(steps=10, fetches=5, tokens=20000),
                error=WorkerError(code="budget_exhausted", message="Done", retryable=False),
            )

    def test_failed_response_requires_error_and_null_result(self):
        resp = ResearchResponse(
            request_id=uuid4(),
            run_id=uuid4(),
            status="failed",
            result=None,
            usage=ResourceUsage(steps=1, fetches=0, tokens=100),
            error=WorkerError(code="auth_error", message="Invalid token", retryable=False),
        )
        assert resp.status == "failed"
        assert resp.result is None

        with pytest.raises(ValidationError, match="Failed response must have null result"):
            ResearchResponse(
                request_id=uuid4(),
                run_id=uuid4(),
                status="failed",
                result=ResearchResult(developments=[]),
                usage=ResourceUsage(steps=1, fetches=0, tokens=100),
                error=WorkerError(code="auth_error", message="Invalid token", retryable=False),
            )


class TestEvidenceRulesAndVerdicts:
    def test_supported_verdict_with_valid_evidence(self):
        v = ClaimVerdict(
            claim_id="c1",
            verdict="supported",
            evidence="Starting salary is $150,000 / year as disclosed on official ATS page.",
        )
        assert v.verdict == "supported"
        assert v.evidence is not None

    def test_supported_verdict_with_blank_or_none_evidence_fails(self):
        with pytest.raises(ValidationError, match="Supported verdict must have nonblank evidence"):
            ClaimVerdict(claim_id="c1", verdict="supported", evidence="   ")

        with pytest.raises(ValidationError, match="Supported verdict must have nonblank evidence"):
            ClaimVerdict(claim_id="c1", verdict="supported", evidence=None)

    def test_supported_verdict_evidence_max_300_chars(self):
        long_evidence = "a" * 301
        with pytest.raises(ValidationError, match="Evidence exceeds maximum length of 300 characters"):
            ClaimVerdict(claim_id="c1", verdict="supported", evidence=long_evidence)

    def test_unsupported_verdict_must_have_null_evidence(self):
        with pytest.raises(ValidationError, match="Non-supported verdict must have null evidence"):
            ClaimVerdict(claim_id="c1", verdict="unsupported", evidence="Some evidence")

        v = ClaimVerdict(claim_id="c1", verdict="unsupported", evidence=None)
        assert v.evidence is None

    def test_unreachable_verdict_must_have_null_evidence(self):
        with pytest.raises(ValidationError, match="Non-supported verdict must have null evidence"):
            ClaimVerdict(claim_id="c1", verdict="unreachable", evidence="Some evidence")

        v = ClaimVerdict(claim_id="c1", verdict="unreachable", evidence=None)
        assert v.evidence is None

    def test_unverified_verdict_is_prohibited_on_worker_wire(self):
        # Worker verdict domain strictly excludes "unverified"
        with pytest.raises(ValidationError):
            ClaimVerdict(claim_id="c1", verdict="unverified", evidence=None)  # type: ignore


class TestVerifyInputIsolationAndAuditPayloads:
    def test_verify_claim_input_accepts_only_specified_fields(self):
        c = VerifyClaimInput(
            claim_id="claim-101",
            text="Minimum qualification is BS in Computer Science.",
            source_url="https://boards.greenhouse.io/co/jobs/1",
        )
        assert c.claim_id == "claim-101"
        assert c.source_url == "https://boards.greenhouse.io/co/jobs/1"

    def test_verify_claim_input_rejects_credentials_summaries_and_pages(self):
        with pytest.raises(ValidationError):
            VerifyClaimInput(
                claim_id="claim-101",
                text="Some text",
                source_url="https://boards.greenhouse.io/co/jobs/1",
                summary="Full summary of the role",  # type: ignore
            )
        with pytest.raises(ValidationError):
            VerifyClaimInput(
                claim_id="claim-101",
                text="Some text",
                source_url="https://boards.greenhouse.io/co/jobs/1",
                page_content="<html>raw html</html>",  # type: ignore
            )
        with pytest.raises(ValidationError):
            VerifyClaimInput(
                claim_id="claim-101",
                text="Some text",
                source_url="https://boards.greenhouse.io/co/jobs/1",
                reasoning="Step-by-step reasoning",  # type: ignore
            )
        with pytest.raises(ValidationError):
            VerifyClaimInput(
                claim_id="claim-101",
                text="Some text",
                source_url="https://boards.greenhouse.io/co/jobs/1",
                user_token="secret-jwt-token",  # type: ignore
            )

    def test_verify_payload_json_deserialization_rejects_injected_fields(self):
        # 1. Injected summary
        with pytest.raises(ValidationError):
            VerifyPayload.model_validate_json(
                '{"claims": [{"claim_id": "c1", "text": "t", "source_url": "https://a.com", "summary": "leaked"}]}'
            )

        # 2. Injected page content
        with pytest.raises(ValidationError):
            VerifyPayload.model_validate_json(
                '{"claims": [{"claim_id": "c1", "text": "t", "source_url": "https://a.com", "page": "<html>...</html>"}]}'
            )

        # 3. Injected reasoning
        with pytest.raises(ValidationError):
            VerifyPayload.model_validate_json(
                '{"claims": [{"claim_id": "c1", "text": "t", "source_url": "https://a.com", "reasoning": "thought process"}]}'
            )

        # 4. Injected credentials at claim level
        with pytest.raises(ValidationError):
            VerifyPayload.model_validate_json(
                '{"claims": [{"claim_id": "c1", "text": "t", "source_url": "https://a.com", "api_key": "secret"}]}'
            )

        # 5. Injected credentials at payload level
        with pytest.raises(ValidationError):
            VerifyPayload.model_validate_json(
                '{"claims": [{"claim_id": "c1", "text": "t", "source_url": "https://a.com"}], "user_token": "secret"}'
            )

    def test_verify_request_json_deserialization_rejects_injected_envelope_credentials(self):
        valid_json = (
            '{"request_id": "00000000-0000-0000-0000-000000000001", '
            '"run_id": "00000000-0000-0000-0000-000000000002", '
            '"time_budget_ms": 120000, '
            '"budget": {"max_steps": 12, "max_fetches": 20, "max_tokens": 40000}, '
            '"payload": {"claims": [{"claim_id": "c1", "text": "t", "source_url": "https://a.com"}]}}'
        )
        req = VerifyRequest.model_validate_json(valid_json)
        assert req.budget.max_steps == 12

        # Injected credentials at envelope level
        injected_json = (
            '{"request_id": "00000000-0000-0000-0000-000000000001", '
            '"run_id": "00000000-0000-0000-0000-000000000002", '
            '"time_budget_ms": 120000, '
            '"budget": {"max_steps": 12, "max_fetches": 20, "max_tokens": 40000}, '
            '"user_password": "insecure_plaintext_password", '
            '"payload": {"claims": [{"claim_id": "c1", "text": "t", "source_url": "https://a.com"}]}}'
        )
        with pytest.raises(ValidationError):
            VerifyRequest.model_validate_json(injected_json)

    def test_article_audit_worker_attribution(self):
        audit_res = ArticleAudit(
            source_url="https://boards.greenhouse.io/co/jobs/1",
            title="AI Engineer",
            worker="researcher",
            status="fetched",
            latency_ms=120.5,
        )
        assert audit_res.worker == "researcher"

        audit_ver = ArticleAudit(
            source_url="https://boards.greenhouse.io/co/jobs/1",
            worker="verifier",
            status="fetched",
        )
        assert audit_ver.worker == "verifier"

        with pytest.raises(ValidationError):
            ArticleAudit(
                source_url="https://boards.greenhouse.io/co/jobs/1",
                worker="orchestrator",  # type: ignore
                status="fetched",
            )

    def test_job_metadata_structure(self):
        meta = JobMetadata(
            company="Anthropic",
            primary_url="https://jobs.lever.co/anthropic/1",
            location="San Francisco, CA",
            compensation="$160,000 - $190,000",
            qualifications_summary="Python, PyTorch",
            fingerprint="anthropic:research-engineer",
        )
        dev = Development(
            id="dev-1",
            title="Research Engineer",
            summary="Entry-level AI research role",
            claims=[
                AtomicClaim(
                    claim_id="c1",
                    text="Requires PyTorch",
                    source_url="https://jobs.lever.co/anthropic/1",
                )
            ],
            company=meta.company,
            primary_url=meta.primary_url,
            location=meta.location,
            compensation=meta.compensation,
            qualifications_summary=meta.qualifications_summary,
            fingerprint=meta.fingerprint,
        )
        assert isinstance(dev, JobMetadata)
        assert dev.company == "Anthropic"
        assert len(dev.claims) == 1

    def test_research_result_rejects_non_researcher_worker_audit(self):
        with pytest.raises(ValidationError, match="ResearchResult articles must be attributed to 'researcher'"):
            ResearchResult(
                developments=[],
                articles=[
                    ArticleAudit(
                        source_url="https://a.com",
                        worker="verifier",  # Mismatch!
                        status="fetched",
                    )
                ],
            )

    def test_verify_result_rejects_non_verifier_worker_audit(self):
        with pytest.raises(ValidationError, match="VerifyResult source_audit must be attributed to 'verifier'"):
            VerifyResult(
                verdicts=[],
                source_audit=[
                    ArticleAudit(
                        source_url="https://a.com",
                        worker="researcher",  # Mismatch!
                        status="fetched",
                    )
                ],
            )


class TestOrchestratorResponseValidation:
    def test_validate_research_response_success(self):
        req_id = uuid4()
        run_id = uuid4()
        budget = ResourceBudget(max_steps=18, max_fetches=20, max_tokens=60000)
        resp = ResearchResponse(
            request_id=req_id,
            run_id=run_id,
            status="complete",
            result=ResearchResult(
                developments=[
                    Development(
                        id="dev-1",
                        title="Job 1",
                        summary="Summary 1",
                        claims=[
                            AtomicClaim(claim_id="c1", text="T1", source_url="https://a.com/1"),
                            AtomicClaim(claim_id="c2", text="T2", source_url="https://a.com/1"),
                        ],
                    )
                ]
            ),
            usage=ResourceUsage(steps=10, fetches=8, tokens=15000),
            error=None,
        )
        validate_research_response(resp, req_id, run_id, budget, max_claims_per_dev=4)

    def test_validate_research_response_mismatched_ids(self):
        req_id = uuid4()
        run_id = uuid4()
        budget = ResourceBudget(max_steps=18, max_fetches=20, max_tokens=60000)
        resp = ResearchResponse(
            request_id=uuid4(),  # Mismatched!
            run_id=run_id,
            status="complete",
            result=ResearchResult(developments=[]),
            usage=ResourceUsage(steps=1, fetches=1, tokens=100),
            error=None,
        )
        with pytest.raises(ValueError, match="Response request_id does not match"):
            validate_research_response(resp, req_id, run_id, budget)

    def test_validate_research_response_usage_exceeds_budget(self):
        req_id = uuid4()
        run_id = uuid4()
        budget = ResourceBudget(max_steps=18, max_fetches=20, max_tokens=60000)
        resp = ResearchResponse(
            request_id=req_id,
            run_id=run_id,
            status="complete",
            result=ResearchResult(developments=[]),
            usage=ResourceUsage(steps=19, fetches=1, tokens=100),  # steps > 18!
            error=None,
        )
        with pytest.raises(ValueError, match="Usage exceeds allocated budget"):
            validate_research_response(resp, req_id, run_id, budget)

    def test_validate_research_response_duplicate_development_ids(self):
        req_id = uuid4()
        run_id = uuid4()
        budget = ResourceBudget(max_steps=18, max_fetches=20, max_tokens=60000)
        resp = ResearchResponse(
            request_id=req_id,
            run_id=run_id,
            status="complete",
            result=ResearchResult(
                developments=[
                    Development(
                        id="dev-1",
                        title="Job 1",
                        summary="Summary 1",
                        claims=[AtomicClaim(claim_id="c1", text="T1", source_url="https://a.com/1")],
                    ),
                    Development(
                        id="dev-1",  # Duplicate dev id!
                        title="Job 2",
                        summary="Summary 2",
                        claims=[AtomicClaim(claim_id="c2", text="T2", source_url="https://a.com/2")],
                    ),
                ]
            ),
            usage=ResourceUsage(steps=1, fetches=1, tokens=100),
            error=None,
        )
        with pytest.raises(ValueError, match="Duplicate development ID detected: dev-1"):
            validate_research_response(resp, req_id, run_id, budget)

    def test_validate_research_response_duplicate_claim_ids(self):
        req_id = uuid4()
        run_id = uuid4()
        budget = ResourceBudget(max_steps=18, max_fetches=20, max_tokens=60000)
        resp = ResearchResponse(
            request_id=req_id,
            run_id=run_id,
            status="complete",
            result=ResearchResult(
                developments=[
                    Development(
                        id="dev-1",
                        title="Job 1",
                        summary="Summary 1",
                        claims=[
                            AtomicClaim(claim_id="c1", text="T1", source_url="https://a.com/1"),
                            AtomicClaim(claim_id="c1", text="T2", source_url="https://a.com/2"),  # Duplicate!
                        ],
                    )
                ]
            ),
            usage=ResourceUsage(steps=1, fetches=1, tokens=100),
            error=None,
        )
        with pytest.raises(ValueError, match="Duplicate claim ID detected"):
            validate_research_response(resp, req_id, run_id, budget)

    def test_validate_research_response_claims_count_bounds(self):
        req_id = uuid4()
        run_id = uuid4()
        budget = ResourceBudget(max_steps=18, max_fetches=20, max_tokens=60000)
        # Development with 5 claims exceeds max 4
        claims_5 = [
            AtomicClaim(claim_id=f"c{i}", text=f"T{i}", source_url="https://a.com")
            for i in range(5)
        ]
        resp = ResearchResponse(
            request_id=req_id,
            run_id=run_id,
            status="complete",
            result=ResearchResult(
                developments=[
                    Development(id="dev-1", title="Job 1", summary="Summary 1", claims=claims_5)
                ]
            ),
            usage=ResourceUsage(steps=1, fetches=1, tokens=100),
            error=None,
        )
        with pytest.raises(ValueError, match="claims count exceeds maximum"):
            validate_research_response(resp, req_id, run_id, budget, max_claims_per_dev=4)

    def test_validate_verify_response_coverage_complete(self):
        req_id = uuid4()
        run_id = uuid4()
        budget = ResourceBudget(max_steps=12, max_fetches=20, max_tokens=40000)
        expected_claims = {"c1", "c2"}

        # Complete response with all claims covered
        resp = VerifyResponse(
            request_id=req_id,
            run_id=run_id,
            status="complete",
            result=VerifyResult(
                verdicts=[
                    ClaimVerdict(claim_id="c1", verdict="supported", evidence="Excerpt 1"),
                    ClaimVerdict(claim_id="c2", verdict="unsupported", evidence=None),
                ]
            ),
            usage=ResourceUsage(steps=5, fetches=4, tokens=5000),
            error=None,
        )
        validate_verify_response(resp, req_id, run_id, expected_claims, budget)

        # Complete response missing c2 must fail validation
        resp_missing = VerifyResponse(
            request_id=req_id,
            run_id=run_id,
            status="complete",
            result=VerifyResult(
                verdicts=[
                    ClaimVerdict(claim_id="c1", verdict="supported", evidence="Excerpt 1"),
                ]
            ),
            usage=ResourceUsage(steps=5, fetches=4, tokens=5000),
            error=None,
        )
        with pytest.raises(ValueError, match="Complete verify response missing expected claims"):
            validate_verify_response(resp_missing, req_id, run_id, expected_claims, budget)

    def test_validate_verify_response_partial_coverage_allowed_for_partial_status(self):
        req_id = uuid4()
        run_id = uuid4()
        budget = ResourceBudget(max_steps=12, max_fetches=20, max_tokens=40000)
        expected_claims = {"c1", "c2", "c3"}

        # Partial response with subset of claims {c1, c2}
        resp = VerifyResponse(
            request_id=req_id,
            run_id=run_id,
            status="partial",
            result=VerifyResult(
                verdicts=[
                    ClaimVerdict(claim_id="c1", verdict="supported", evidence="Excerpt 1"),
                    ClaimVerdict(claim_id="c2", verdict="unreachable", evidence=None),
                ]
            ),
            usage=ResourceUsage(steps=12, fetches=10, tokens=25000),
            error=WorkerError(code="time_exhausted", message="Timeout", retryable=False),
        )
        validate_verify_response(resp, req_id, run_id, expected_claims, budget)

    def test_validate_verify_response_unknown_claim_rejected(self):
        req_id = uuid4()
        run_id = uuid4()
        budget = ResourceBudget(max_steps=12, max_fetches=20, max_tokens=40000)
        expected_claims = {"c1", "c2"}

        # Response with an unknown claim "c_unknown"
        resp = VerifyResponse(
            request_id=req_id,
            run_id=run_id,
            status="complete",
            result=VerifyResult(
                verdicts=[
                    ClaimVerdict(claim_id="c1", verdict="supported", evidence="Excerpt 1"),
                    ClaimVerdict(claim_id="c2", verdict="unsupported", evidence=None),
                    ClaimVerdict(claim_id="c_unknown", verdict="unsupported", evidence=None),
                ]
            ),
            usage=ResourceUsage(steps=5, fetches=4, tokens=5000),
            error=None,
        )
        with pytest.raises(ValueError, match="Unknown claim ID detected"):
            validate_verify_response(resp, req_id, run_id, expected_claims, budget)

    def test_validate_verify_response_duplicate_claim_ids(self):
        req_id = uuid4()
        run_id = uuid4()
        budget = ResourceBudget(max_steps=12, max_fetches=20, max_tokens=40000)
        expected_claims = {"c1", "c2"}

        resp = VerifyResponse(
            request_id=req_id,
            run_id=run_id,
            status="complete",
            result=VerifyResult(
                verdicts=[
                    ClaimVerdict(claim_id="c1", verdict="supported", evidence="Excerpt 1"),
                    ClaimVerdict(claim_id="c1", verdict="unsupported", evidence=None),  # Duplicate c1!
                ]
            ),
            usage=ResourceUsage(steps=5, fetches=4, tokens=5000),
            error=None,
        )
        with pytest.raises(ValueError, match="Duplicate claim ID detected in verdicts: c1"):
            validate_verify_response(resp, req_id, run_id, expected_claims, budget)
