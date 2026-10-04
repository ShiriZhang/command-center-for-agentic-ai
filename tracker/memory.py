"""
Recrawl Memory Manager and Two-Tier Job Deduplication Engine.
CSCI-GA.2630 Assignment 1B: Agentic Foundations
"""

import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
from urllib.parse import urlparse

from tracker.config import config
from tracker.llm import LLMClient

logger = logging.getLogger("tracker.memory")

# Recognized corporate Applicant Tracking Systems (ATS)
ATS_DOMAINS = (
    "greenhouse.io",
    "lever.co",
    "ashbyhq.com",
    "myworkdayjobs.com",
    "smartrecruiters.com",
    "rippling-ats.com",
    "workable.com",
    "bamboohr.com"
)


# ==============================================================================
# 1. Normalization & Fingerprinting Utilities
# ==============================================================================

def slugify(text: str) -> str:
    """
    Normalizes a text string into a clean lowercase slug.
    Strips punctuation, requisition codes, and extraneous whitespace.
    """
    if not text:
        return ""
    text = text.lower()
    # Strip common corporate suffix abbreviations
    text = re.sub(
        r"\b(inc|corp|corporation|llc|ltd|technologies|tech|ai|labs|industries|group|holdings|company|co)\b\.?",
        "",
        text
    )
    # Strip requisition codes e.g. (Req #1234), [R-12345]
    text = re.sub(r"[\(\[\{][^\)\]\}]*[\)\]\}]", "", text)
    # Replace non-alphanumeric with spaces
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


def are_companies_matching(comp1: str, comp2: str) -> bool:
    """
    Determines whether two company names refer to the same corporate entity.
    """
    s1 = slugify(comp1)
    s2 = slugify(comp2)
    if not s1 or not s2:
        return False
    return s1 == s2 or s1 in s2 or s2 in s1


def clean_job_title(title: str) -> str:
    """
    Cleans and standardizes job titles by standardizing seniority abbreviations
    and removing company prefixes if prepended.
    """
    slug = slugify(title)
    # Standardize common acronyms
    slug = re.sub(r"\bsr\b", "senior", slug)
    slug = re.sub(r"\bjr\b", "junior", slug)
    slug = re.sub(r"\bml\b", "machine learning", slug)
    slug = re.sub(r"\bswe\b", "software engineer", slug)
    return slug


def generate_fingerprint(company: str, title: str) -> str:
    """
    Generates a deterministic Tier 1 fingerprint: [slug(company):slug(title)].
    """
    company_slug = slugify(company)
    title_slug = clean_job_title(title)
    return f"{company_slug}:{title_slug}"


def is_ats_url(url: str) -> bool:
    """Returns True if the URL points to a recognized direct corporate ATS portal."""
    if not url:
        return False
    parsed = urlparse(url.lower())
    netloc = parsed.netloc
    return any(ats in netloc for ats in ATS_DOMAINS)


def compute_token_jaccard_similarity(str1: str, str2: str) -> float:
    """
    Computes Jaccard similarity between token sets of two strings:
    J(A, B) = |A ∩ B| / |A ∪ B|
    """
    tokens1 = set(clean_job_title(str1).split())
    tokens2 = set(clean_job_title(str2).split())
    if not tokens1 or not tokens2:
        return 0.0
    intersection = tokens1.intersection(tokens2)
    union = tokens1.union(tokens2)
    return len(intersection) / len(union)


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
            # Parse JSON from content (handling optional markdown code fences)
            clean_json = re.sub(r"^```json\s*|\s*```$", "", content.strip(), flags=re.MULTILINE).strip()
            data = json.loads(clean_json)
            return bool(data.get("is_same_role")), data.get("reason", ""), data.get("canonical_title", job1.get("title"))
        except Exception as e:
            logger.warning(f"LLM semantic disambiguation failed: {e}. Defaulting to false.")
            # Conservative default: do not merge on error to avoid false positives
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
            # Promote secondary ATS link to primary
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

        # Merge location/compensation if primary lacked them
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


# ==============================================================================
# 3. Recrawl Memory Manager
# ==============================================================================

class RecrawlMemoryManager:
    """
    Persists and inspects multi-run state, providing:
    1. Known URL persistence (Run 2 skips Run 1 URLs).
    2. Multi-run classification: 'New since last run', 'Still in top K', 'Dropped'.
    """

    def __init__(self, state_file_path: Optional[Path] = None):
        root_dir = Path(__file__).resolve().parent.parent
        self.state_file = state_file_path or (root_dir / "reports" / "tracker_state.json")
        self.deduplicator = JobDeduplicator()

    def load_previous_state(self) -> Optional[Dict[str, Any]]:
        """Loads state persisted from prior executions."""
        if not self.state_file.exists():
            return None
        try:
            with open(self.state_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Could not read previous tracker state: {e}")
            return None

    def get_known_urls(self) -> Set[str]:
        """Returns set of all URLs visited in prior runs to prevent re-crawling."""
        state = self.load_previous_state()
        if not state:
            return set()
        return set(state.get("visited_urls", []))

    def get_previous_top_k(self) -> List[Dict[str, Any]]:
        """Returns Top K roles saved from the previous run."""
        state = self.load_previous_state()
        if not state:
            return []
        return state.get("top_k_jobs", [])

    def classify_multi_run_developments(
        self,
        previous_top_k: List[Dict[str, Any]],
        current_top_k: List[Dict[str, Any]]
    ) -> Dict[str, List[Dict[str, Any]]]:
        """
        Classifies findings into the three mandatory categories:
        1. 'New since last run': Present in current Top K, absent in previous Top K.
        2. 'Still in top K': Present in both previous and current Top K.
        3. 'Dropped': Present in previous Top K, absent in current Top K.
        """
        prev_fps: Dict[str, Dict[str, Any]] = {}
        for p in previous_top_k:
            fp = p.get("fingerprint") or generate_fingerprint(p.get("company", ""), p.get("title", ""))
            prev_fps[fp] = p

        curr_fps: Dict[str, Dict[str, Any]] = {}
        for c in current_top_k:
            fp = c.get("fingerprint") or generate_fingerprint(c.get("company", ""), c.get("title", ""))
            curr_fps[fp] = c

        new_since_last_run: List[Dict[str, Any]] = []
        still_in_top_k: List[Dict[str, Any]] = []
        dropped: List[Dict[str, Any]] = []

        # Analyze current top K
        for fp, job in curr_fps.items():
            if fp in prev_fps:
                item = dict(job)
                item["status"] = "Still in top K"
                item["recrawl_badge"] = "[STILL IN TOP 10]"
                still_in_top_k.append(item)
            else:
                item = dict(job)
                item["status"] = "New since last run"
                item["recrawl_badge"] = "[NEW]"
                new_since_last_run.append(item)

        # Analyze dropped positions
        for fp, prev_job in prev_fps.items():
            if fp not in curr_fps:
                item = dict(prev_job)
                item["status"] = "Dropped"
                item["recrawl_badge"] = "[DROPPED]"
                dropped.append(item)

        return {
            "new_since_last_run": new_since_last_run,
            "still_in_top_k": still_in_top_k,
            "dropped": dropped
        }

    def save_state(
        self,
        run_number: int,
        visited_urls: Set[str],
        top_k_jobs: List[Dict[str, Any]],
        metadata: Optional[Dict[str, Any]] = None
    ) -> None:
        """Persists state to local JSON file for subsequent run comparison."""
        self.state_file.parent.mkdir(parents=True, exist_ok=True)

        # Accumulate with previous URLs
        prev_urls = self.get_known_urls()
        all_urls = sorted(list(prev_urls.union(visited_urls)))

        # Ensure canonical fingerprints
        deduped = self.deduplicator.deduplicate_job_list(top_k_jobs)

        data = {
            "run_number": run_number,
            "visited_urls": all_urls,
            "top_k_jobs": deduped,
            "metadata": metadata or {}
        }

        with open(self.state_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        logger.info(f"Saved tracker recrawl state to {self.state_file}")

    def reset_state(self) -> None:
        """Wipes the local state file for clean testing from scratch."""
        if self.state_file.exists():
            self.state_file.unlink()
            logger.info("Cleared tracker recrawl state.")
