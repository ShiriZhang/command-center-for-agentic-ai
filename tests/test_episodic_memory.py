"""
Unit Tests for Episodic Memory, State Persistence, and Multi-Run Differentiation.
CSCI-GA.2630 Assignment 1B: Agentic Foundations
"""

import json
from pathlib import Path
import tempfile
import unittest

from tracker.memory.episodic import EpisodicMemory, RecrawlMemoryManager


class TestEpisodicMemory(unittest.TestCase):
    """
    Test suite for EpisodicMemory:
    - State serialization to JSON (reports/tracker_state.json)
    - URL registry and positive non-error cached role retrieval
    - Multi-run development classification (New / Still in Top K / Dropped)
    - Backward-compatibility alias
    """

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.state_file = Path(self.temp_dir.name) / "test_state.json"
        self.memory = EpisodicMemory(state_file_path=self.state_file)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_backward_compatibility_alias(self):
        """Verify RecrawlMemoryManager is an alias for EpisodicMemory."""
        self.assertIs(RecrawlMemoryManager, EpisodicMemory)

    def test_initial_state_empty(self):
        """Verify uninitialized episodic memory returns empty state without errors."""
        self.assertIsNone(self.memory.load_previous_state())
        self.assertEqual(len(self.memory.get_known_urls()), 0)
        self.assertEqual(len(self.memory.get_previous_top_k()), 0)
        self.assertFalse(self.memory.is_url_known("https://example.com/job1"))

    def test_save_and_load_state(self):
        """Verify state saving, URL accumulation, and deduplicated Top K loading."""
        urls = {"https://boards.greenhouse.io/co/1", "https://jobs.lever.co/co/2"}
        jobs = [
            {
                "title": "ML Engineer",
                "company": "Company A",
                "url": "https://boards.greenhouse.io/co/1",
                "snippet": "Job details 1"
            },
            {
                "title": "AI Engineer",
                "company": "Company B",
                "url": "https://jobs.lever.co/co/2",
                "snippet": "Job details 2"
            }
        ]
        self.memory.save_state(run_number=1, visited_urls=urls, top_k_jobs=jobs)

        state = self.memory.load_previous_state()
        self.assertIsNotNone(state)
        self.assertEqual(state["run_number"], 1)
        self.assertEqual(set(state["visited_urls"]), urls)
        self.assertEqual(len(state["top_k_jobs"]), 2)
        self.assertTrue(self.memory.is_url_known("https://boards.greenhouse.io/co/1"))
        self.assertTrue(self.memory.is_url_known("https://boards.greenhouse.io/co/1/"))  # Trailing slash test

    def test_get_cached_job_info_returns_positive_non_error_status(self):
        """Verify cached URL lookup returns status='cached_active' with error=None."""
        url = "https://boards.greenhouse.io/co/verified"
        jobs = [
            {
                "title": "Machine Learning Engineer - Early Career",
                "company": "DeepMind",
                "url": url,
                "snippet": "Verified foundation model role."
            }
        ]
        self.memory.save_state(run_number=1, visited_urls={url}, top_k_jobs=jobs)

        cached_info = self.memory.get_cached_job_info(url)
        self.assertIsNotNone(cached_info)
        self.assertEqual(cached_info["status"], "cached_active")
        self.assertTrue(cached_info["cached"])
        self.assertIsNone(cached_info["error"])  # MUST NOT report error
        self.assertIsNone(cached_info["error_message"])
        self.assertEqual(cached_info["title"], "Machine Learning Engineer - Early Career")
        self.assertEqual(cached_info["url"], url)

    def test_classify_multi_run_developments(self):
        """Verify correct partitioning into New, Still in Top K, and Dropped."""
        prev_top_k = [
            {
                "company": "Anthropic",
                "title": "AI Systems Engineer",
                "url": "https://jobs.lever.co/anthropic/1",
                "fingerprint": "anthropic:ai systems engineer"
            },
            {
                "company": "OpenAI",
                "title": "Research Engineer",
                "url": "https://boards.greenhouse.io/openai/1",
                "fingerprint": "openai:research engineer"
            }
        ]

        curr_top_k = [
            {
                # Retained
                "company": "Anthropic",
                "title": "AI Systems Engineer",
                "url": "https://jobs.lever.co/anthropic/1",
                "fingerprint": "anthropic:ai systems engineer"
            },
            {
                # New
                "company": "Scale AI",
                "title": "Software Engineer - Applied ML",
                "url": "https://boards.greenhouse.io/scaleai/2",
                "fingerprint": "scale ai:software engineer applied ml"
            }
        ]

        classified = self.memory.classify_multi_run_developments(prev_top_k, curr_top_k)

        # 1. New since last run
        new_jobs = classified["new_since_last_run"]
        self.assertEqual(len(new_jobs), 1)
        self.assertEqual(new_jobs[0]["company"], "Scale AI")
        self.assertEqual(new_jobs[0]["recrawl_badge"], "[NEW]")

        # 2. Still in Top 10
        still_jobs = classified["still_in_top_k"]
        self.assertEqual(len(still_jobs), 1)
        self.assertEqual(still_jobs[0]["company"], "Anthropic")
        self.assertEqual(still_jobs[0]["recrawl_badge"], "[STILL IN TOP 10]")

        # 3. Dropped
        dropped_jobs = classified["dropped"]
        self.assertEqual(len(dropped_jobs), 1)
        self.assertEqual(dropped_jobs[0]["company"], "OpenAI")
        self.assertEqual(dropped_jobs[0]["recrawl_badge"], "[DROPPED]")

    def test_reset_state(self):
        """Verify state file deletion on reset."""
        self.memory.save_state(run_number=1, visited_urls={"https://test.com"}, top_k_jobs=[])
        self.assertTrue(self.state_file.exists())
        self.memory.reset_state()
        self.assertFalse(self.state_file.exists())


if __name__ == "__main__":
    unittest.main()
