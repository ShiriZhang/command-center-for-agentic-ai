"""
Semantic Memory Module: AI/ML Recruiting Domain Knowledge, Ontologies, and Scoring.
CSCI-GA.2630 Assignment 1B: Agentic Foundations
"""

from datetime import datetime, timezone, timedelta
import logging
import re
from typing import Any, Dict, List, Optional, Tuple, Union
from urllib.parse import urlparse

from tracker.memory.dedup import (
    ATS_DOMAINS,
    slugify,
    clean_job_title,
    generate_fingerprint,
    is_ats_url,
)

logger = logging.getLogger("tracker.memory.semantic")

# Regex patterns for seniority filtering and entry exemptions
SENIOR_PATTERN = re.compile(
    r"\b(senior|sr\.?|lead|staff|principal|director|vp|vice president|head of|architect)\b|"
    r"\b([5-9]|\d{2})\+?\s*(years?|yrs?)\b",
    re.IGNORECASE
)

ENTRY_EXEMPTION_PATTERN = re.compile(
    r"\b(entry[\s-]?level|junior|jr\.?|new[\s-]?grad|university[\s-]?grad|early[\s-]?career|intern|internship|associate|fellow)\b",
    re.IGNORECASE
)


class SemanticMemory:
    """
    Encapsulates static AI/ML domain rules, applicant tracking system (ATS) knowledge,
    seniority qualification boundaries, and candidate priority scoring.
    """

    def __init__(self):
        self.ats_domains = ATS_DOMAINS

    @staticmethod
    def is_ats_url(url: str) -> bool:
        """Determines if a URL points to an authentic corporate ATS portal."""
        return is_ats_url(url)

    @staticmethod
    def canonicalize_company(company: str) -> str:
        """Normalizes company names to canonical slugs."""
        return slugify(company)

    @staticmethod
    def clean_title(title: str) -> str:
        """Cleans and standardizes job titles."""
        return clean_job_title(title)

    @staticmethod
    def generate_fingerprint(company: str, title: str) -> str:
        """Generates deterministic Tier 1 dedup fingerprint."""
        return generate_fingerprint(company, title)

    def filter_seniority(self, title: str, snippet: str = "") -> Tuple[bool, str]:
        """
        Seniority Dual-Check Filter:
        Disqualifies postings that contain Senior/Staff/Lead or 5+ years experience
        UNLESS explicitly labeled with Entry/Junior/New Grad exemptions.
        
        Returns:
            (is_qualified: bool, reason: str)
        """
        combined_text = f"{title} {snippet}"
        has_senior = bool(SENIOR_PATTERN.search(combined_text))
        has_entry = bool(ENTRY_EXEMPTION_PATTERN.search(combined_text))

        if has_senior and not has_entry:
            matched_senior = SENIOR_PATTERN.findall(combined_text)
            return False, f"Disqualified: Seniority keyword identified without entry-level exemption ({matched_senior})"

        return True, "Qualified: Junior/Entry-level role or no disqualifying senior keywords"

    def compute_freshness_score(
        self,
        posted_at: Union[str, datetime, float, int, None],
        now: Optional[datetime] = None
    ) -> Tuple[bool, int, str]:
        """
        Calculates freshness decay score and enforces 30-day hard expiration.
        
        Decay Schedule:
        - <= 24h: +5 pts (Max bonus)
        - 1 to 3 days: +4 pts
        - 3 to 7 days: +3 pts
        - 7 to 14 days: +2 pts
        - 14 to 30 days: +1 pt
        - > 30 days: Disqualified (is_valid=False)
        - Missing/Unspecified: +2 pts baseline default
        
        Returns:
            (is_valid: bool, score: int, reason: str)
        """
        current_time = now or datetime.now(timezone.utc)
        if current_time.tzinfo is None:
            current_time = current_time.replace(tzinfo=timezone.utc)

        if not posted_at:
            return True, 2, "Freshness unspecified: assigned baseline +2"

        # Parse posted_at into timezone-aware datetime
        post_dt: Optional[datetime] = None
        if isinstance(posted_at, (int, float)):
            post_dt = datetime.fromtimestamp(posted_at, tz=timezone.utc)
        elif isinstance(posted_at, datetime):
            post_dt = posted_at if posted_at.tzinfo else posted_at.replace(tzinfo=timezone.utc)
        elif isinstance(posted_at, str):
            clean_str = posted_at.strip()
            # Handle ISO formats
            for fmt in [
                "%Y-%m-%dT%H:%M:%S%z",
                "%Y-%m-%dT%H:%M:%S.%f%z",
                "%Y-%m-%dT%H:%M:%SZ",
                "%Y-%m-%d %H:%M:%S",
                "%Y-%m-%d",
            ]:
                try:
                    if fmt.endswith("Z"):
                        clean_str_z = clean_str if clean_str.endswith("Z") else f"{clean_str}Z"
                        post_dt = datetime.strptime(clean_str_z, fmt).replace(tzinfo=timezone.utc)
                    else:
                        post_dt = datetime.strptime(clean_str, fmt)
                        if post_dt.tzinfo is None:
                            post_dt = post_dt.replace(tzinfo=timezone.utc)
                    break
                except ValueError:
                    continue

        if not post_dt:
            return True, 2, "Unparseable date format: assigned baseline +2"

        delta = current_time - post_dt
        if delta < timedelta(0):
            # Future date / clock drift: treat as just posted
            return True, 5, "Posted within last 24h (+5)"

        days = delta.total_seconds() / 86400.0

        if days > 30.0:
            return False, 0, f"Disqualified: Posting is {days:.1f} days old (exceeds 30-day cutoff)"
        elif days <= 1.0:
            return True, 5, "Posted within last 24h (+5)"
        elif days <= 3.0:
            return True, 4, f"Posted {days:.1f} days ago (+4)"
        elif days <= 7.0:
            return True, 3, f"Posted {days:.1f} days ago (+3)"
        elif days <= 14.0:
            return True, 2, f"Posted {days:.1f} days ago (+2)"
        else:
            return True, 1, f"Posted {days:.1f} days ago (+1)"

    def score_candidate(
        self,
        candidate: Dict[str, Any],
        now: Optional[datetime] = None
    ) -> Tuple[bool, int, str]:
        """
        Evaluates and scores a candidate job opening against all semantic criteria.
        
        Scoring Model:
        - Seniority Filter: Hard disqualification if senior without entry exemption.
        - Freshness Expiration: Hard disqualification if > 30 days old.
        - Freshness Bonus: +1 to +5 pts.
        - Channel Authenticity: +3 pts for corporate ATS direct links.
        - Target Role Matching: +3 pts for explicit entry keywords in title.
        - Compensation Disclosure: +1 pt for verified salary range.
        
        Returns:
            (is_qualified: bool, total_score: int, diagnostic_reason: str)
        """
        title = candidate.get("title") or ""
        snippet = candidate.get("snippet") or candidate.get("description") or ""
        url = candidate.get("apply_url") or candidate.get("url") or ""
        posted_at = candidate.get("posted_at") or candidate.get("published_at") or candidate.get("date")

        # Step 1: Seniority filter
        is_qual, sen_reason = self.filter_seniority(title, snippet)
        if not is_qual:
            return False, 0, sen_reason

        # Step 2: Freshness score and 30-day cutoff
        is_fresh, fresh_score, fresh_reason = self.compute_freshness_score(posted_at, now=now)
        if not is_fresh:
            return False, 0, fresh_reason

        # Step 3: Bonus evaluations
        total_score = fresh_score

        # ATS channel bonus (+3)
        if self.is_ats_url(url):
            total_score += 3

        # Explicit entry level in title bonus (+3)
        if bool(ENTRY_EXEMPTION_PATTERN.search(title)):
            total_score += 3

        # Compensation disclosure bonus (+1)
        comp = candidate.get("compensation") or ""
        if comp or (candidate.get("salary_min") and candidate.get("salary_max")):
            total_score += 1

        return True, total_score, f"Qualified with score {total_score} ({fresh_reason})"
