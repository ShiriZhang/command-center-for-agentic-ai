"""
Two-Tier Job Deduplication Engine and Fingerprinting Utilities.
CSCI-GA.2630 Assignment 1B: Agentic Foundations
"""

import json
import logging
import re
from typing import Any, Dict, List, Optional, Set, Tuple
from urllib.parse import urlparse

from tracker.config import config
from tracker.llm import LLMClient

logger = logging.getLogger("tracker.memory.dedup")

from shared.fingerprint import (
    ATS_DOMAINS,
    PLATFORM_DOMAINS,
    PLATFORM_NAMES,
    SEO_COMPANY_BLACKLIST,
    is_platform_url,
    is_platform_name,
    slugify,
    are_companies_matching,
    clean_job_title,
    generate_fingerprint,
    is_ats_url,
    compute_token_jaccard_similarity,
)


# ==============================================================================
# 2. Two-Tier Deduplication Engine
# ==============================================================================

class JobDeduplicator:
    """
    Two-Tier Deduplication and Canonical Representation:
    - Tier 1: Deterministic fast-path fingerprint matching (0 token spend).
    - Tier 2: Fuzzy Jaccard trigger -> LLM semantic disambiguation.
    """

    def __init__(self, llm_client: Optional[LLMClient] = None):
        self.llm = llm_client
        self.similarity_threshold = config.deduplication.similarity_threshold
        self.max_disambiguation_calls = config.deduplication.max_disambiguation_calls
        self.disambiguation_calls_made = 0

    def _disambiguate_with_llm(
        self,
        job1: Dict[str, Any],
        job2: Dict[str, Any]
    ) -> Tuple[bool, str, str]:
        """
        Invokes LLM semantic disambiguation to determine if two postings from the same
        company represent the same underlying hiring opening.
        
        Returns:
            (is_same_role: bool, reason: str, canonical_title: str)
        """
        if not self.llm:
            return False, "No LLM client provided for disambiguation", job1.get("title", "")

        if self.disambiguation_calls_made >= self.max_disambiguation_calls:
            logger.warning("Reached maximum LLM disambiguation call cap.")
            return False, "Disambiguation call cap reached", job1.get("title", "")

        self.disambiguation_calls_made += 1
        prompt = (
            "You are an expert HR and recruitment data deduplicator. Analyze whether the following two "
            "job postings represent the SAME opening at the company, or if they are separate roles.\n\n"
            f"Role 1:\n- Title: {job1.get('title')}\n- Company: {job1.get('company')}\n- Location: {job1.get('location')}\n- Summary: {job1.get('snippet', '')[:300]}\n\n"
            f"Role 2:\n- Title: {job2.get('title')}\n- Company: {job2.get('company')}\n- Location: {job2.get('location')}\n- Summary: {job2.get('snippet', '')[:300]}\n\n"
            "Respond ONLY with a JSON object in this exact schema:\n"
            "{\n"
            '  "is_same_role": boolean,\n'
            '  "reason": "short explanation",\n'
            '  "canonical_title": "most accurate, professional title"\n'
            "}"
        )

        try:
            resp = self.llm.create_completion(
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
                max_tokens=250
            )
            content = resp.choices[0].message.content or ""
            clean_json = re.sub(r"^```json\s*|\s*```$", "", content.strip(), flags=re.MULTILINE).strip()
            data = json.loads(clean_json)
            return bool(data.get("is_same_role")), data.get("reason", ""), data.get("canonical_title", job1.get("title"))
        except Exception as e:
            logger.warning(f"LLM semantic disambiguation failed: {e}. Defaulting to false.")
            return False, f"Disambiguation error: {e}", job1.get("title", "")

    def merge_records(self, primary: Dict[str, Any], secondary: Dict[str, Any]) -> Dict[str, Any]:
        """
        Merges two matching job records into a single canonical record.
        Prioritizes direct corporate ATS links over board URLs.
        """
        merged = dict(primary)

        # ATS URL prioritization
        pri_url = primary.get("url", "")
        sec_url = secondary.get("url", "")

        if not is_ats_url(pri_url) and is_ats_url(sec_url):
            merged["url"] = sec_url
            sources = set(merged.get("supporting_sources", []))
            if pri_url:
                sources.add(pri_url)
            merged["supporting_sources"] = list(sources)
        else:
            sources = set(merged.get("supporting_sources", []))
            if sec_url and sec_url != pri_url:
                sources.add(sec_url)
            merged["supporting_sources"] = list(sources)

        if not merged.get("location") and secondary.get("location"):
            merged["location"] = secondary["location"]
        if not merged.get("compensation") and secondary.get("compensation"):
            merged["compensation"] = secondary["compensation"]

        return merged

    def deduplicate_job_list(self, jobs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Deduplicates an incoming list of jobs against each other.
        """
        canonical_jobs: List[Dict[str, Any]] = []

        for candidate in jobs:
            c_company = candidate.get("company") or ""
            c_title = candidate.get("title") or ""
            c_fp = generate_fingerprint(c_company, c_title)
            candidate["fingerprint"] = c_fp
            if "supporting_sources" not in candidate:
                candidate["supporting_sources"] = []

            matched = False
            for idx, existing in enumerate(canonical_jobs):
                e_fp = existing.get("fingerprint", "")

                # Tier 1: Deterministic Exact Fingerprint Match
                if c_fp and e_fp and c_fp == e_fp:
                    canonical_jobs[idx] = self.merge_records(existing, candidate)
                    matched = True
                    break

                # Tier 2: Same company + High Title Jaccard Similarity
                e_company = existing.get("company") or ""
                if are_companies_matching(c_company, e_company):
                    sim = compute_token_jaccard_similarity(c_title, existing.get("title", ""))
                    if sim >= self.similarity_threshold:
                        is_same, reason, canon_title = self._disambiguate_with_llm(existing, candidate)
                        if is_same:
                            canonical_jobs[idx] = self.merge_records(existing, candidate)
                            canonical_jobs[idx]["title"] = canon_title or canonical_jobs[idx]["title"]
                            matched = True
                            break

            if not matched:
                canonical_jobs.append(dict(candidate))

        return canonical_jobs
