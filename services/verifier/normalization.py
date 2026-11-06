"""
Pure code evidence verification and string normalization for Verifier service.
CSCI-GA.2630 Assignment 2
"""

import html
import re
from typing import Optional, Tuple
import unicodedata


def normalize_for_matching(text: str) -> str:
    """
    Applies the five required string normalization steps:
    1. HTML entity decoding (html.unescape)
    2. Unicode NFKC normalization (unicodedata.normalize)
    3. Whitespace collapse (re.sub)
    4. Documented outer trim (.strip())
    5. Lowercase (.lower())
    """
    if not text:
        return ""
    unescaped = html.unescape(text)
    nfkc = unicodedata.normalize("NFKC", unescaped)
    collapsed = re.sub(r"\s+", " ", nfkc)
    trimmed = collapsed.strip()
    return trimmed.lower()


def verify_evidence(
    verdict: str,
    evidence: Optional[str],
    page_text: str,
) -> Tuple[str, Optional[str]]:
    """
    Validates evidence according to strict assignment rules:
    - Supported verdicts must have a nonempty excerpt between 1 and 300 Unicode characters.
    - Normalized excerpt must be a substring of the normalized page text.
    - Blank, overlong, or absent excerpts downgrade verdict to 'unsupported' with evidence=None.
    - Non-supported verdicts ('unsupported', 'unreachable') must always have evidence=None.
    """
    if verdict != "supported":
        return verdict, None

    # Check evidence existence and raw length constraint (1..300)
    if evidence is None or not evidence.strip():
        return "unsupported", None

    if len(evidence) > 300:
        return "unsupported", None

    norm_evidence = normalize_for_matching(evidence)
    if not norm_evidence:
        return "unsupported", None

    norm_page = normalize_for_matching(page_text)
    if norm_evidence in norm_page:
        return "supported", evidence

    # Excerpt not present in normalized fetched text -> downgrade
    return "unsupported", None
