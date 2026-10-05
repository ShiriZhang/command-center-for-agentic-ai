"""
search_web Tool supporting Seed-First AI Dev Jobs Discovery, Semantic Scoring,
and Lazy Tavily Rescue Querying with Resilient Fallback.
CSCI-GA.2630 Assignment 1B: Agentic Foundations
"""

import json
import logging
import os
import re
import sys
from typing import Any, Dict, List, Optional, Union
from urllib.parse import urlparse

import httpx
from tavily import TavilyClient

from tracker.config import config
from tracker.memory.semantic import SemanticMemory

logger = logging.getLogger("tracker.tools.search")


class SearchResultList(list):
    """
    A list of search result items that simultaneously supports:
    1. Standard list operations: iteration, indexing (results[0]), len(results).
    2. Dictionary access: results['results'], results['total_results'], results['query'].
    3. Serialization helper: results.to_dict().
    
    This ensures complete compatibility with both list-expecting and dict-expecting callers.
    """
    def __init__(self, items: List[Dict[str, Any]], query: str = ""):
        super().__init__(items)
        self.query = query
        self.total_results = len(items)

    def __getitem__(self, key: Union[int, slice, str]) -> Any:
        if isinstance(key, str):
            if key == "results":
                return list(self)
            if key == "query":
                return self.query
            if key == "total_results":
                return self.total_results
            raise KeyError(f"Invalid key '{key}' on SearchResultList. Permitted: 'results', 'query', 'total_results'")
        return super().__getitem__(key)

    def get(self, key: str, default: Any = None) -> Any:
        if key == "results":
            return list(self)
        if key == "query":
            return self.query
        if key == "total_results":
            return self.total_results
        return default

    def to_dict(self) -> Dict[str, Any]:
        return {
            "query": self.query,
            "total_results": self.total_results,
            "results": list(self)
        }


def search_tavily(
    query: str,
    max_results: int = 5,
    api_key: Optional[str] = None
) -> List[Dict[str, Any]]:
    """
    Executes an open web search using the Tavily Search API.
    
    Returns normalized list of results with fields:
    title, snippet, url, source, score.
    """
    key = api_key or config.tavily_api_key or os.getenv("TAVILY_API_KEY")
    if not key:
        raise ValueError(
            "[TERMINAL FAILURE] TAVILY_API_KEY is missing. "
            "Configure it in your root .env file or environment variables."
        )

    client = TavilyClient(api_key=key)
    try:
        response = client.search(
            query=query,
            max_results=max(1, min(max_results, 20)),
            search_depth="basic"
        )
    except Exception as e:
        logger.error(f"Tavily search failed: {e}")
        raise

    raw_results = response.get("results", []) if isinstance(response, dict) else []
    normalized: List[Dict[str, Any]] = []

    for item in raw_results:
        raw_url = item.get("url", "").strip()
        if not raw_url:
            continue

        raw_title = item.get("title", "").strip()
        raw_snippet = item.get("content", "").strip()

        # Clean multiple spaces/newlines
        clean_title = re.sub(r"\s+", " ", raw_title)
        clean_snippet = re.sub(r"\s+", " ", raw_snippet)

        normalized.append({
            "title": clean_title or "Untitled Search Result",
            "snippet": clean_snippet or "No snippet provided.",
            "url": raw_url,
            "source": "tavily",
            "score": item.get("score")
        })

    return normalized


def search_tavily_rescue(
    company: str,
    title: str,
    max_results: int = 3,
    api_key: Optional[str] = None
) -> List[Dict[str, Any]]:
    """
    Executes a high-precision targeted Tavily rescue search to locate the direct
    application/ATS portal page for a candidate role when direct link is missing or fetch failed.
    """
    clean_company = re.sub(r"[^\w\s-]", "", company).strip()
    clean_title = re.sub(r"[^\w\s-]", "", title).strip()
    query = f'"{clean_company}" "{clean_title}" apply careers (greenhouse OR lever OR ashby)'
    logger.info(f"Initiating lazy Tavily rescue search for '{clean_company} - {clean_title}'")
    return search_tavily(query=query, max_results=max_results, api_key=api_key)


def discover_aidevboard_candidates(
    query: str = "",
    max_results: int = 5,
    api_url: str = "https://aidevboard.com/api/v1/jobs"
) -> List[Dict[str, Any]]:
    """
    Candidate discovery integration from AI Dev Jobs API (https://aidevboard.com/api/v1/jobs).
    Seeds high-quality candidate job postings with direct ATS career portal links (Greenhouse, Ashby, Lever).
    Handles API outages gracefully by logging fallback notices and returning an empty list.
    
    Returns normalized list of results with fields:
    title, snippet, url, source, company, apply_url, date_posted, salary, relevance_score.
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) FNMS-Tracker/1.0",
        "Accept": "application/json"
    }

    try:
        with httpx.Client(timeout=10.0, verify=True) as client:
            resp = client.get(api_url, params={"per_page": 50}, headers=headers)
            if resp.status_code != 200:
                logger.warning(
                    f"AI Dev Jobs API outage: HTTP {resp.status_code}. "
                    "Transparent fallback to Tavily web search activated."
                )
                return []
            data = resp.json()
    except Exception as e:
        logger.warning(
            f"AI Dev Jobs API connection error/timeout: {e}. "
            "Transparent fallback to Tavily web search activated."
        )
        return []

    jobs = data.get("jobs", []) if isinstance(data, dict) else []
    if not jobs:
        return []

    # Tokenize query for lightweight relevance scoring
    query_tokens = [tok.lower() for tok in re.findall(r"\w+", query) if len(tok) > 2]
    candidate_results: List[Dict[str, Any]] = []

    for job in jobs:
        title = (job.get("title") or "").strip()
        company = (job.get("company_name") or "").strip()
        exp_level = (job.get("experience_level") or "").strip().lower()
        desc = (job.get("description") or "").strip()
        tags = [t.lower() for t in job.get("tags") or []]
        apply_url = (job.get("apply_url") or "").strip()
        board_url = (job.get("url") or "").strip()
        date_posted = (job.get("posted_at") or job.get("date_posted") or "").strip()

        # Target direct corporate ATS URL if available, fallback to board URL
        target_url = apply_url or board_url
        if not target_url:
            continue

        searchable_text = f"{title} {company} {' '.join(tags)} {desc[:500]}".lower()

        # Compute match score: check query tokens + entry level/new grad keywords
        score = 0
        for token in query_tokens:
            if token in searchable_text:
                score += 2

        # Bonus for entry level / junior / new grad indications
        if any(kw in searchable_text for kw in ["entry", "junior", "new grad", "early career", "intern", "associate"]):
            score += 3
        if exp_level in ("entry", "junior", "entry_level"):
            score += 3

        # Must have at least basic AI/ML relevance if query is role-focused
        if any(kw in searchable_text for kw in ["ai", "ml", "machine learning", "data", "deep learning", "engineer", "scientist"]):
            score += 1

        # Compose clean descriptive snippet
        loc = job.get("location") or "Remote / Unspecified"
        salary_str = ""
        salary_val = ""
        if job.get("salary_min") and job.get("salary_max"):
            salary_val = f"${job['salary_min']:,} - ${job['salary_max']:,}"
            salary_str = f" | Compensation: {salary_val}"
        
        clean_desc = re.sub(r"\s+", " ", desc[:300])
        snippet = (
            f"Company: {company} | Level: {exp_level or 'Not specified'} | Location: {loc}{salary_str}. "
            f"Overview: {clean_desc}..."
        )

        full_title = f"{company} - {title}" if company and company not in title else title

        candidate_results.append({
            "title": full_title,
            "snippet": snippet,
            "url": target_url,
            "source": "aidevboard",
            "company": company,
            "apply_url": apply_url,
            "date_posted": date_posted,
            "salary": salary_val,
            "relevance_score": score
        })

    # Sort candidates by relevance score descending
    candidate_results.sort(key=lambda x: x.get("relevance_score", 0), reverse=True)
    return candidate_results[:max_results]


def search_web(
    query: str,
    max_results: int = 5,
    include_candidates: bool = True,
    semantic_memory: Optional[SemanticMemory] = None
) -> SearchResultList:
    """
    Unified web search tool integrating Seed-First AI Dev Jobs candidate discovery
    with Tavily Search API, SemanticMemory prioritization, and resilient fallback.
    
    Parameters:
        query: Search keywords or query string.
        max_results: Maximum number of merged results to return.
        include_candidates: Whether to seed target job discoveries from aidevboard.com.
        semantic_memory: Optional SemanticMemory instance for scoring and qualification filtering.
        
    Returns:
        SearchResultList containing normalized dict items with fields:
        'title', 'snippet', 'url', 'source', 'priority_score'.
    """
    semantic = semantic_memory or SemanticMemory()
    candidate_results: List[Dict[str, Any]] = []
    tavily_results: List[Dict[str, Any]] = []

    # Step 1: Seed-first candidate discovery from AI Dev Jobs
    if include_candidates:
        try:
            raw_cands = discover_aidevboard_candidates(query, max_results=max_results * 2)
            for cand in raw_cands:
                is_qual, score, _ = semantic.score_candidate(cand)
                if is_qual:
                    item = dict(cand)
                    item["priority_score"] = score
                    candidate_results.append(item)
            # Sort candidate discoveries by priority_score descending
            candidate_results.sort(key=lambda x: x.get("priority_score", 0), reverse=True)
        except Exception as e:
            logger.warning(f"Error during candidate discovery: {e}. Falling back to Tavily.")

    # Step 2: Query Tavily when needed:
    # - If candidate seeding is disabled
    # - Or if candidate seeding yielded fewer than max_results (supplement or fallback)
    need_tavily = (not include_candidates) or (len(candidate_results) < max_results)

    if need_tavily:
        try:
            tavily_count = max_results if not candidate_results else max(2, max_results - len(candidate_results))
            tav_items = search_tavily(query, max_results=tavily_count)
            for item in tav_items:
                is_qual, score, _ = semantic.score_candidate(item)
                item_dict = dict(item)
                item_dict["priority_score"] = score if is_qual else 0
                tavily_results.append(item_dict)
        except Exception as e:
            logger.warning(f"Tavily search unavailable: {e}")

    # Step 3: Canonical URL Deduplication & Priority Merge
    seen_urls = set()
    merged: List[Dict[str, Any]] = []

    def _canonical_url(u: str) -> str:
        if not u:
            return ""
        parsed = urlparse(u.strip())
        return f"{parsed.netloc.lower()}{parsed.path.rstrip('/')}"

    # Combine candidates: seed discoveries first, then Tavily results
    # Rank overall candidate pool:
    # 1. Qualified items first (priority_score > 0)
    # 2. Priority score descending
    # 3. Direct ATS source (aidevboard with ATS) prioritized
    all_candidates = candidate_results + tavily_results
    all_candidates.sort(
        key=lambda x: (
            1 if x.get("priority_score", 0) > 0 else 0,
            x.get("priority_score", 0),
            1 if x.get("source") == "aidevboard" else 0
        ),
        reverse=True
    )

    for item in all_candidates:
        raw_url = item.get("url") or item.get("apply_url") or ""
        canon = _canonical_url(raw_url)
        if not canon or canon in seen_urls:
            continue
        seen_urls.add(canon)
        merged.append(item)
        if len(merged) >= max_results:
            break

    return SearchResultList(merged, query=query)


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    if len(sys.argv) < 2:
        print("Usage: python -m tracker.tools.search <query> [max_results]")
        sys.exit(1)

    search_query = sys.argv[1]
    limit = int(sys.argv[2]) if len(sys.argv) > 2 else 5
    res = search_web(search_query, max_results=limit)
    print(json.dumps(res.to_dict(), indent=2, ensure_ascii=False))
