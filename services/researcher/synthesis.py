"""
Discovery, ranking, and atomic claim synthesis for Researcher service.
CSCI-GA.2630 Assignment 2
"""

from typing import Any, Dict, List, Optional
from shared.contracts import Development, AtomicClaim
from shared.fingerprint import generate_fingerprint


def build_atomic_claims(
    dev_id: str,
    title: str,
    company: Optional[str],
    primary_url: str,
    location: Optional[str] = None,
    compensation: Optional[str] = None,
    qualifications: Optional[str] = None,
    content_snippet: str = "",
    max_claims: int = 4,
) -> List[AtomicClaim]:
    """
    Constructs cited atomic claims for a job development.
    Guarantees:
    - At least 1 claim citing the primary URL.
    - At most max_claims claims (default 4).
    - Missing compensation, location, or qualifications are NEVER fabricated or invented.
    - Unique claim IDs within the development.
    """
    effective_max = max(1, max_claims)
    claims: List[AtomicClaim] = []
    claim_idx = 1

    # Claim 1: Role existence and title/company attribution
    comp_str = company or "Company"
    claim_1_text = f"Job opening for '{title}' at {comp_str}."
    if content_snippet:
        snippet_excerpt = content_snippet[:150].strip()
        claim_1_text = f"Opening: {title} at {comp_str}. Details: {snippet_excerpt}"

    claims.append(
        AtomicClaim(
            claim_id=f"{dev_id}-c{claim_idx}",
            text=claim_1_text,
            source_url=primary_url,
        )
    )
    claim_idx += 1

    # Claim 2: Compensation (ONLY if real compensation was extracted)
    if compensation and len(claims) < effective_max:
        claims.append(
            AtomicClaim(
                claim_id=f"{dev_id}-c{claim_idx}",
                text=f"The compensation for {title} is {compensation}.",
                source_url=primary_url,
            )
        )
        claim_idx += 1

    # Claim 3: Location / Modality (ONLY if location was extracted)
    if location and len(claims) < effective_max:
        claims.append(
            AtomicClaim(
                claim_id=f"{dev_id}-c{claim_idx}",
                text=f"The job location/work mode for {title} is {location}.",
                source_url=primary_url,
            )
        )
        claim_idx += 1

    # Claim 4: Qualifications (ONLY if qualifications were extracted)
    if qualifications and len(claims) < effective_max:
        claims.append(
            AtomicClaim(
                claim_id=f"{dev_id}-c{claim_idx}",
                text=f"Qualifications requirement for {title}: {qualifications}.",
                source_url=primary_url,
            )
        )
        claim_idx += 1

    return claims


def synthesize_job_developments(
    extracted_jobs: List[Dict[str, Any]],
    target_k: int = 10,
    max_claims_per_dev: int = 4,
) -> List[Development]:
    """
    Transforms extracted jobs into ranked Development models with deterministic fingerprints
    and cited atomic claims.
    """
    developments: List[Development] = []

    for idx, raw_job in enumerate(extracted_jobs[:target_k], 1):
        dev_id = f"dev-{idx}"
        title = raw_job.get("title") or f"Discovered Opportunity {idx}"
        company = raw_job.get("company")
        primary_url = raw_job.get("url") or raw_job.get("primary_url") or "https://boards.greenhouse.io"
        location = raw_job.get("location")
        compensation = raw_job.get("compensation")
        qualifications = raw_job.get("qualifications")
        snippet = raw_job.get("snippet") or raw_job.get("summary") or ""

        # Deterministic fingerprint
        fingerprint = raw_job.get("fingerprint") or generate_fingerprint(company or "", title)

        # Build atomic claims
        claims = build_atomic_claims(
            dev_id=dev_id,
            title=title,
            company=company,
            primary_url=primary_url,
            location=location,
            compensation=compensation,
            qualifications=qualifications,
            content_snippet=snippet,
            max_claims=max_claims_per_dev,
        )

        dev = Development(
            id=dev_id,
            title=title,
            summary=snippet or f"Discovered {title} at {company or 'employer'}.",
            claims=claims,
            company=company,
            primary_url=primary_url,
            location=location,
            compensation=compensation,
            qualifications_summary=qualifications,
            fingerprint=fingerprint,
        )
        developments.append(dev)

    return developments
