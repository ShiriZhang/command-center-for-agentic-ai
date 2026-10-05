"""
Hierarchical Native Memory Package for Agentic Tracker.
CSCI-GA.2630 Assignment 1B: Agentic Foundations
"""

from tracker.memory.dedup import (
    ATS_DOMAINS,
    JobDeduplicator,
    slugify,
    are_companies_matching,
    clean_job_title,
    generate_fingerprint,
    is_ats_url,
    compute_token_jaccard_similarity,
)
from tracker.memory.episodic import (
    RecrawlMemoryManager,
    EpisodicMemory,
)
from tracker.memory.semantic import (
    SemanticMemory,
)
from tracker.memory.working import (
    WorkingMemory,
)

__all__ = [
    "ATS_DOMAINS",
    "JobDeduplicator",
    "RecrawlMemoryManager",
    "EpisodicMemory",
    "SemanticMemory",
    "WorkingMemory",
    "slugify",
    "are_companies_matching",
    "clean_job_title",
    "generate_fingerprint",
    "is_ats_url",
    "compute_token_jaccard_similarity",
]
