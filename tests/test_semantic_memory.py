"""
Unit Tests for Semantic Memory, Seniority Filtering, and Multi-Factor Scoring.
CSCI-GA.2630 Assignment 1B: Agentic Foundations
"""

from datetime import datetime, timezone, timedelta
import unittest

from tracker.memory.semantic import SemanticMemory


class TestSemanticMemory(unittest.TestCase):
    """
    Test suite for SemanticMemory:
    - Seniority keyword filtering and entry exemption
    - Time-decay freshness scoring and 30-day expiration
    - ATS domain identification
    - Comprehensive candidate priority scoring
    """

    def setUp(self):
        self.semantic = SemanticMemory()
        self.now = datetime(2026, 10, 4, 12, 0, 0, tzinfo=timezone.utc)

    def test_seniority_filter_disqualifications(self):
        """Verify that pure senior, staff, lead, and 5+ years positions are disqualified."""
        disqualified_titles = [
            "Senior Machine Learning Engineer",
            "Lead AI Infrastructure Engineer",
            "Staff Deep Learning Scientist",
            "Principal ML Architect",
            "Director of Artificial Intelligence",
            "VP of Engineering - Generative AI",
            "Machine Learning Engineer (5+ years experience required)"
        ]
        for title in disqualified_titles:
            is_qual, reason = self.semantic.filter_seniority(title)
            self.assertFalse(is_qual, f"Expected '{title}' to be disqualified. Reason given: {reason}")
            self.assertIn("Seniority keyword", reason)

    def test_seniority_filter_entry_exemptions(self):
        """Verify that positions containing entry-level tokens are preserved even if senior words appear."""
        qualified_titles = [
            "Machine Learning Engineer - New Grad 2026",
            "Entry Level Software Engineer (AI/ML Focus)",
            "Junior Data Scientist",
            "Early Career Research Engineer",
            "AI Systems Engineer Intern",
            # Exemption cases where 'senior' appears in context
            "New Grad Machine Learning Engineer - Senior Capstone Preferred",
            "Associate Applied AI Researcher"
        ]
        for title in qualified_titles:
            is_qual, reason = self.semantic.filter_seniority(title)
            self.assertTrue(is_qual, f"Expected '{title}' to be qualified. Reason given: {reason}")

    def test_freshness_decay_scoring_schedule(self):
        """Verify step-down decay schedule: <=24h (+5), <=3d (+4), <=7d (+3), <=14d (+2), <=30d (+1)."""
        # 12 hours ago (within 24h)
        t_12h = self.now - timedelta(hours=12)
        valid, score, _ = self.semantic.compute_freshness_score(t_12h, now=self.now)
        self.assertTrue(valid)
        self.assertEqual(score, 5)

        # 2 days ago (within 3d)
        t_2d = self.now - timedelta(days=2)
        valid, score, _ = self.semantic.compute_freshness_score(t_2d, now=self.now)
        self.assertTrue(valid)
        self.assertEqual(score, 4)

        # 5 days ago (within 7d)
        t_5d = self.now - timedelta(days=5)
        valid, score, _ = self.semantic.compute_freshness_score(t_5d, now=self.now)
        self.assertTrue(valid)
        self.assertEqual(score, 3)

        # 10 days ago (within 14d)
        t_10d = self.now - timedelta(days=10)
        valid, score, _ = self.semantic.compute_freshness_score(t_10d, now=self.now)
        self.assertTrue(valid)
        self.assertEqual(score, 2)

        # 20 days ago (within 30d)
        t_20d = self.now - timedelta(days=20)
        valid, score, _ = self.semantic.compute_freshness_score(t_20d, now=self.now)
        self.assertTrue(valid)
        self.assertEqual(score, 1)

    def test_freshness_30_day_hard_expiration_cutoff(self):
        """Verify that postings older than 30 days are disqualified."""
        t_35d = self.now - timedelta(days=35)
        valid, score, reason = self.semantic.compute_freshness_score(t_35d, now=self.now)
        self.assertFalse(valid)
        self.assertEqual(score, 0)
        self.assertIn("exceeds 30-day cutoff", reason)

    def test_freshness_missing_date_fallback(self):
        """Verify that unspecified post date returns baseline +2 without disqualification."""
        valid, score, _ = self.semantic.compute_freshness_score(None, now=self.now)
        self.assertTrue(valid)
        self.assertEqual(score, 2)

    def test_candidate_scoring_priority(self):
        """Verify end-to-end candidate scoring rubric with channel and title bonuses."""
        # Top-tier candidate: Fresh (<=24h: +5), Direct ATS (+3), Entry in title (+3), Salary disclosed (+1) = 12
        top_job = {
            "title": "New Grad Machine Learning Engineer (2026)",
            "company": "Scale AI",
            "apply_url": "https://boards.greenhouse.io/scaleai/jobs/123",
            "posted_at": (self.now - timedelta(hours=6)).isoformat(),
            "salary_min": 150000,
            "salary_max": 180000
        }
        is_qual, score, _ = self.semantic.score_candidate(top_job, now=self.now)
        self.assertTrue(is_qual)
        self.assertEqual(score, 12)

        # Senior candidate rejected outright
        senior_job = {
            "title": "Senior AI Infrastructure Engineer",
            "company": "Anthropic",
            "apply_url": "https://jobs.lever.co/anthropic/456",
            "posted_at": (self.now - timedelta(hours=2)).isoformat()
        }
        is_qual, score, reason = self.semantic.score_candidate(senior_job, now=self.now)
        self.assertFalse(is_qual)
        self.assertEqual(score, 0)
        self.assertIn("Seniority keyword", reason)

        # Stale candidate (>30 days) rejected outright
        stale_job = {
            "title": "Junior ML Engineer",
            "company": "DeepMind",
            "apply_url": "https://deepmind.google/careers/789",
            "posted_at": (self.now - timedelta(days=45)).isoformat()
        }
        is_qual, score, reason = self.semantic.score_candidate(stale_job, now=self.now)
        self.assertFalse(is_qual)
        self.assertEqual(score, 0)
        self.assertIn("exceeds 30-day cutoff", reason)


if __name__ == "__main__":
    unittest.main()
