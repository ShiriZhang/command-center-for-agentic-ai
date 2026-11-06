"""
Deterministic job deduplication utilities and fingerprinting functions.
CSCI-GA.2630 Assignment 2 - Shared Module
"""

import re
from typing import Optional, Set
from urllib.parse import urlparse

# Recognized corporate Applicant Tracking Systems (ATS)
ATS_DOMAINS = (
    "greenhouse.io",
    "lever.co",
    "ashbyhq.com",
    "myworkdayjobs.com",
    "smartrecruiters.com",
    "rippling-ats.com",
    "workable.com",
    "bamboohr.com",
)

# Known job board / aggregator platform domains
PLATFORM_DOMAINS = (
    "indeed.com",
    "builtin.com",
    "builtinnyc.com",
    "research.com",
    "simplify.jobs",
    "linkedin.com",
    "glassdoor.com",
    "ziprecruiter.com",
    "monster.com",
    "wellfound.com",
    "angellist.com",
    "levels.fyi",
    "handshake.com",
    "joinhandshake.com",
    "wayup.com",
    "dice.com",
    "careerbuilder.com",
    "jobvite.com",
    "simplyhired.com",
    "adzuna.com",
)

# Platform names that must NEVER be treated as a job Title or hiring Company
PLATFORM_NAMES = (
    "indeed",
    "built in",
    "builtin",
    "builtin nyc",
    "research.com",
    "simplify",
    "simplify jobs",
    "linkedin",
    "glassdoor",
    "ziprecruiter",
    "monster",
    "wellfound",
    "angellist",
    "levels.fyi",
    "handshake",
    "wayup",
    "dice",
    "careerbuilder",
)

# SEO headline phrases that must NEVER be assigned as a company name
SEO_COMPANY_BLACKLIST = re.compile(
    r"\b(now\s+hiring|\d+[\+,\s]*jobs?|job\s+openings?|search\s+jobs?|apply\s+to|best\s+companies|"
    r"explore\s+jobs?|browse\s+jobs?|find\s+jobs?|top\s+\d+|salaries|reviews|advice|salary\s+guide)\b",
    re.IGNORECASE,
)


def is_platform_url(url: str) -> bool:
    """Returns True if the URL belongs to a general aggregator / job board platform."""
    if not url:
        return False
    parsed = urlparse(url.lower())
    netloc = parsed.netloc
    return any(p in netloc for p in PLATFORM_DOMAINS)


def is_platform_name(name: str) -> bool:
    """Returns True if the given string is a platform name rather than a company or title."""
    if not name:
        return False
    clean = re.sub(r"[^a-z0-9\s.]", "", name.lower()).strip()
    return any(
        p == clean
        or f" {p} " in f" {clean} "
        or clean.endswith(f" {p}")
        or clean.startswith(f"{p} ")
        for p in PLATFORM_NAMES
    )


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
        text,
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
    Cleans and standardizes job titles by standardizing seniority abbreviations,
    stripping platform noise suffixes, and removing company prefixes if prepended.
    """
    # Strip platform suffixes like " - Indeed", " | Built In NYC", " - Simplify Jobs"
    for p in PLATFORM_NAMES:
        title = re.sub(rf"\s*[-|–]\s*{re.escape(p)}\b.*$", "", title, flags=re.IGNORECASE)
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
