"""
Unit Tests for Recrawl Memory and Two-Tier Deduplication Engine.
CSCI-GA.2630 Assignment 1B: Agentic Foundations
"""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from tracker.memory import (
    JobDeduplicator,
    RecrawlMemoryManager,
    generate_fingerprint,
    compute_token_jaccard_similarity,
    is_ats_url,
)


class TestMemoryAndDeduplication(unittest.TestCase):
    """
    Test suite for two-tier deduplication, ATS link promotion,
    and multi-run development classification (New / Still in Top K / Dropped).
    """

    def test_fingerprint_normalization(self):
        """
        Verify that corporate suffixes and location/requisition parentheticals are normalized.
        """
        fp1 = generate_fingerprint("Meta, Inc.", "Research Engineer - Early Career (NYC)")
        fp2 = generate_fingerprint("Meta", "Research Engineer - Early Career [Req #1234]")
        self.assertEqual(fp1, fp2)
        self.assertEqual(fp1, "meta:research engineer early career")

    def test_is_ats_url(self):
        """
        Verify identification of recognized corporate ATS domains.
        """
        self.assertTrue(is_ats_url("https://boards.greenhouse.io/openai/jobs/123"))
        self.assertTrue(is_ats_url("https://jobs.ashbyhq.com/anthropic/456"))
        self.assertTrue(is_ats_url("https://jobs.lever.co/scaleai/789"))
        self.assertFalse(is_ats_url("https://aidevboard.com/job/sample-uuid"))
        self.assertFalse(is_ats_url("https://linkedin.com/jobs/view/123"))

    def test_tier_1_deterministic_deduplication_and_ats_promotion(self):
        """
        Verify Tier 1 merges identical jobs without LLM calls and promotes ATS URLs.
        """
        mock_llm = MagicMock()
        dedup = JobDeduplicator(llm_client=mock_llm)

        job_board = {
            "title": "Machine Learning Engineer - New Grad",
            "company": "Anduril Industries",
            "url": "https://aidevboard.com/job/anduril-1",
            "location": "Costa Mesa, CA",
            "snippet": "Entry level ML opening."
        }
        job_ats = {
            "title": "Machine Learning Engineer - New Grad",
            "company": "Anduril",
            "url": "https://boards.greenhouse.io/andurilindustries/jobs/5233989007",
            "location": "Costa Mesa, CA",
            "snippet": "Direct corporate ATS posting."
        }

        merged_list = dedup.deduplicate_job_list([job_board, job_ats])

        # Exactly 1 canonical record
        self.assertEqual(len(merged_list), 1)
        canonical = merged_list[0]
        # ATS Greenhouse link promoted to primary URL
        self.assertEqual(canonical["url"], "https://boards.greenhouse.io/andurilindustries/jobs/5233989007")
        # Aggregator link preserved in supporting_sources
        self.assertIn("https://aidevboard.com/job/anduril-1", canonical["supporting_sources"])
        # CRITICAL ASSERTION: Zero LLM calls made (Tier 1 fast path)
        self.assertEqual(mock_llm.create_completion.call_count, 0)

    def test_tier_2_llm_disambiguation_positive(self):
        """
        Verify Tier 2 fuzzy match invokes LLM and successfully merges equivalent roles.
        """
        mock_llm = MagicMock()
        mock_resp = MagicMock()
        mock_resp.choices = [MagicMock()]
        mock_resp.choices[0].message.content = json.dumps({
            "is_same_role": True,
            "reason": "MLE and Machine Learning Engineer are exact synonyms at Meta",
            "canonical_title": "Machine Learning Engineer, Infrastructure"
        })
        mock_llm.create_completion.return_value = mock_resp

        dedup = JobDeduplicator(llm_client=mock_llm)

        job1 = {
            "title": "Machine Learning Engineer, Infrastructure",
            "company": "Meta",
            "url": "https://www.metacareers.com/v2/jobs/101",
            "snippet": "Infra AI systems"
        }
        job2 = {
            "title": "Machine Learning Engineer - Infra Systems",
            "company": "Meta",
            "url": "https://boards.greenhouse.io/meta/jobs/102",
            "snippet": "AI infra"
        }

        merged = dedup.deduplicate_job_list([job1, job2])
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["title"], "Machine Learning Engineer, Infrastructure")
        self.assertEqual(mock_llm.create_completion.call_count, 1)

    def test_tier_2_llm_disambiguation_negative(self):
        """
        Verify Tier 2 preserves distinct roles when LLM determines they are separate tracks.
        """
        mock_llm = MagicMock()
        mock_resp = MagicMock()
        mock_resp.choices = [MagicMock()]
        mock_resp.choices[0].message.content = json.dumps({
            "is_same_role": False,
            "reason": "One is engineering and the other is a research scientist position",
            "canonical_title": ""
        })
        mock_llm.create_completion.return_value = mock_resp

        dedup = JobDeduplicator(llm_client=mock_llm)

        job1 = {
            "title": "Software Engineer - Early Career",
            "company": "Google",
            "url": "https://google.com/jobs/1",
            "snippet": "SWE role"
        }
        job2 = {
            "title": "Research Scientist - Early Career",
            "company": "Google",
            "url": "https://google.com/jobs/2",
            "snippet": "Research scientist role"
        }

        merged = dedup.deduplicate_job_list([job1, job2])
        # Preserved as 2 distinct roles
        self.assertEqual(len(merged), 2)

    def test_multi_run_classification(self):
        """
        Verify multi-run development classification into:
        'New since last run', 'Still in top K', and 'Dropped'.
        """
        manager = RecrawlMemoryManager()

        job_a = {"company": "Company A", "title": "Role A", "url": "https://a.com"}
        job_b = {"company": "Company B", "title": "Role B", "url": "https://b.com"}
        job_c = {"company": "Company C", "title": "Role C", "url": "https://c.com"}
        job_d = {"company": "Company D", "title": "Role D", "url": "https://d.com"}

        # Run 1 Top K: [A, B, C]
        run1_top_k = [job_a, job_b, job_c]
        # Run 2 Top K: [B, C, D] (A dropped, D added)
        run2_top_k = [job_b, job_c, job_d]

        classification = manager.classify_multi_run_developments(
            previous_top_k=run1_top_k,
            current_top_k=run2_top_k
        )

        # 1. New since last run should be [D]
        self.assertEqual(len(classification["new_since_last_run"]), 1)
        self.assertEqual(classification["new_since_last_run"][0]["title"], "Role D")
        self.assertEqual(classification["new_since_last_run"][0]["recrawl_badge"], "[NEW]")

        # 2. Still in top K should be [B, C]
        self.assertEqual(len(classification["still_in_top_k"]), 2)
        retained_titles = [r["title"] for r in classification["still_in_top_k"]]
        self.assertIn("Role B", retained_titles)
        self.assertIn("Role C", retained_titles)
        self.assertEqual(classification["still_in_top_k"][0]["recrawl_badge"], "[STILL IN TOP 10]")

        # 3. Dropped should be [A]
        self.assertEqual(len(classification["dropped"]), 1)
        self.assertEqual(classification["dropped"][0]["title"], "Role A")
        self.assertEqual(classification["dropped"][0]["recrawl_badge"], "[DROPPED]")

    def test_state_persistence_and_reset(self):
        """
        Verify JSON state persistence, URL union accumulation, and clean reset.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            state_path = Path(tmpdir) / "test_state.json"
            mgr = RecrawlMemoryManager(state_file_path=state_path)

            self.assertIsNone(mgr.load_previous_state())

            # Save Run 1
            mgr.save_state(
                run_number=1,
                visited_urls={"https://test1.com", "https://test2.com"},
                top_k_jobs=[{"company": "Comp1", "title": "Job1", "url": "https://test1.com"}]
            )

            loaded = mgr.load_previous_state()
            self.assertIsNotNone(loaded)
            self.assertEqual(loaded["run_number"], 1)
            self.assertEqual(len(loaded["visited_urls"]), 2)

            # Save Run 2 (accumulate new URL)
            mgr.save_state(
                run_number=2,
                visited_urls={"https://test3.com"},
                top_k_jobs=[{"company": "Comp2", "title": "Job2", "url": "https://test3.com"}]
            )
            loaded2 = mgr.load_previous_state()
            self.assertEqual(loaded2["run_number"], 2)
            self.assertEqual(len(loaded2["visited_urls"]), 3)

            # Reset state
            mgr.reset_state()
            self.assertIsNone(mgr.load_previous_state())


if __name__ == "__main__":
    unittest.main()
