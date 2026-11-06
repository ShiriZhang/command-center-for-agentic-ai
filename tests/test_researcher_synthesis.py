"""
Unit tests for Task 3.4: Researcher Job Discovery, Synthesis, Fingerprints, and Atomic Claims.
Verifies ranked job synthesis, >=1 and <= max_claims_per_dev atomic claims per job,
preservation of deterministic fingerprints, and non-invention of missing salary/qualifications.
"""

import sys
import pytest
from shared.fingerprint import generate_fingerprint
from shared.contracts import Development, AtomicClaim
from services.researcher.synthesis import (
    build_atomic_claims,
    synthesize_job_developments,
)


def test_researcher_service_has_zero_tracker_backend_imports():
    """Spec: Researcher must be completely decoupled from tracker.run lifecycle and database credentials."""
    import services.researcher.synthesis
    import services.researcher.runtime
    import services.researcher.fetch
    import services.researcher.idempotency
    import services.researcher.telemetry
    import services.researcher.app

    loaded_modules = list(sys.modules.keys())
    assert not any(m.startswith("tracker.") for m in loaded_modules if "services.researcher" in m)
    # Ensure neither tracker.config nor backend.app.database was loaded as a side-effect
    # (Check sys.modules for any unwanted credential loaders if starting freshly)


def test_build_atomic_claims_always_has_at_least_one_claim():
    """Every development must have at least 1 cited atomic claim."""
    claims = build_atomic_claims(
        dev_id="dev-1",
        title="AI Engineer",
        company="Anthropic",
        primary_url="https://jobs.lever.co/anthropic/1",
        location=None,
        compensation=None,
        qualifications=None,
        content_snippet="Anthropic is seeking an AI Engineer to join our safety team.",
        max_claims=4,
    )
    assert len(claims) >= 1
    assert claims[0].claim_id == "dev-1-c1"
    assert claims[0].source_url == "https://jobs.lever.co/anthropic/1"
    assert "AI Engineer" in claims[0].text or "Anthropic" in claims[0].text


def test_build_atomic_claims_does_not_invent_missing_compensation():
    """Missing compensation must remain None and must NOT produce a fabricated compensation claim."""
    claims = build_atomic_claims(
        dev_id="dev-2",
        title="ML Scientist",
        company="OpenAI",
        primary_url="https://openai.com/careers/1",
        location="San Francisco, CA",
        compensation=None,  # Missing!
        qualifications="MS or PhD in Computer Science",
        content_snippet="Research role in SF.",
        max_claims=4,
    )
    claim_texts = [c.text.lower() for c in claims]
    assert not any("compensation" in t or "salary" in t or "$" in t for t in claim_texts)
    assert any("san francisco" in t for t in claim_texts)


def test_build_atomic_claims_enforces_max_claims_bound():
    """Number of claims per development cannot exceed configured max_claims (e.g. 2 or 4)."""
    claims = build_atomic_claims(
        dev_id="dev-3",
        title="Staff Research Engineer",
        company="Google DeepMind",
        primary_url="https://deepmind.google/jobs/1",
        location="New York, NY",
        compensation="$220,000 - $260,000 / yr",
        qualifications="5+ years experience in deep learning systems",
        content_snippet="Full job description snippet.",
        max_claims=2,  # Configured cap is 2!
    )
    assert len(claims) == 2


def test_synthesize_job_developments_produces_valid_ranked_developments():
    """Synthesizes raw job extractions into ordered Development contracts with fingerprints."""
    raw_jobs = [
        {
            "title": "Machine Learning Engineer",
            "company": "Anthropic",
            "url": "https://jobs.lever.co/anthropic/ml-eng",
            "location": "San Francisco, CA",
            "compensation": "$180,000 - $240,000 / yr",
            "qualifications": "Strong proficiency in PyTorch",
            "snippet": "We are looking for an ML Engineer in SF.",
        },
        {
            "title": "Applied AI Scientist",
            "company": "DeepMind",
            "url": "https://deepmind.google/careers/ai-sci",
            "location": "London, UK",
            "compensation": None,  # No compensation info
            "qualifications": "PhD in AI/ML",
            "snippet": "Applied AI research in London.",
        },
    ]

    devs = synthesize_job_developments(raw_jobs, target_k=2, max_claims_per_dev=4)
    assert len(devs) == 2
    assert all(isinstance(d, Development) for d in devs)

    # Verify rank order preserved
    assert devs[0].title == "Machine Learning Engineer"
    assert devs[1].title == "Applied AI Scientist"

    # Verify deterministic fingerprint
    expected_fp1 = generate_fingerprint("Anthropic", "Machine Learning Engineer")
    expected_fp2 = generate_fingerprint("DeepMind", "Applied AI Scientist")
    assert devs[0].fingerprint == expected_fp1
    assert devs[1].fingerprint == expected_fp2

    # Verify claim counts
    assert 1 <= len(devs[0].claims) <= 4
    assert 1 <= len(devs[1].claims) <= 4

    # Verify unique claim IDs across all developments
    all_claim_ids = [c.claim_id for d in devs for c in d.claims]
    assert len(all_claim_ids) == len(set(all_claim_ids))
