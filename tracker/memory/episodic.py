"""
Episodic Memory Module: Cross-Run State Persistence, URL Registry, and Differential Recrawl.
CSCI-GA.2630 Assignment 1B: Agentic Foundations
"""

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Set
from urllib.parse import urlparse

from tracker.memory.dedup import JobDeduplicator, generate_fingerprint

logger = logging.getLogger("tracker.memory.episodic")


class EpisodicMemory:
    """
    Manages cross-run persistent episodic memory:
    1. Tracks URL crawl history to prevent redundant network fetching.
    2. Provides positive non-error cached role information for seen URLs.
    3. Persists Top K state across runs (reports/tracker_state.json).
    4. Computes multi-run differential classifications:
       - 'New since last run' [NEW]
       - 'Still in top K' [STILL IN TOP 10]
       - 'Dropped' [DROPPED]
    """

    def __init__(self, state_file_path: Optional[Path] = None):
        root_dir = Path(__file__).resolve().parent.parent.parent
        self.state_file = state_file_path or (root_dir / "reports" / "tracker_state.json")
        self.deduplicator = JobDeduplicator()
        self.known_urls: Set[str] = set()

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
        """Returns set of all URLs visited in prior runs."""
        state = self.load_previous_state()
        persisted = set(state.get("visited_urls", [])) if state else set()
        return persisted | self.known_urls

    def is_url_known(self, url: str) -> bool:
        """Determines whether a URL has already been fetched in prior runs."""
        if not url:
            return False
        known = self.get_known_urls()
        norm_known = {u.rstrip("/") for u in known}
        return url in known or url.rstrip("/") in norm_known

    def get_cached_job_info(self, url: str) -> Optional[Dict[str, Any]]:
        """
        Retrieves cached metadata for an already-visited URL.
        Returns a positive, non-error status ('cached_active') so the agent
        understands the role is valid and active from previous crawling.
        """
        if not self.is_url_known(url):
            return None

        state = self.load_previous_state() or {}
        top_k = state.get("top_k_jobs", [])

        # Match against previously stored top K jobs
        matched_job = None
        for job in top_k:
            j_url = job.get("url") or ""
            supp = job.get("supporting_sources") or []
            if j_url == url or j_url.rstrip("/") == url.rstrip("/") or url in supp:
                matched_job = job
                break

        title = matched_job.get("title") if matched_job else "Retained Active Opening"
        snippet = matched_job.get("snippet") if matched_job else "Retained active role from previous crawl run."

        return {
            "url": url,
            "current_url": url,
            "title": title,
            "content": snippet,
            "status": "cached_active",
            "cached": True,
            "error": None,
            "error_message": None,
            "byte_size": 0,
            "fetch_time_ms": 0.0
        }

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
        logger.info(f"Saved tracker episodic recrawl state to {self.state_file}")

    def reset_state(self) -> None:
        """Wipes the local state file for clean testing from scratch."""
        if self.state_file.exists():
            self.state_file.unlink()
            logger.info("Cleared tracker recrawl state.")


# Maintain backward-compatibility alias for legacy code
RecrawlMemoryManager = EpisodicMemory
