"""
Unit Tests for Reporter and CLI Runner.
CSCI-GA.2630 Assignment 1B: Agentic Foundations
"""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

from tracker.reporter import (
    generate_run1_report,
    generate_run2_report,
    save_report_and_trace
)
from tracker.run import authenticate_user, run_tracker


class TestReporterAndRunner(unittest.TestCase):
    """
    Test suite for report generation, trace logging, and CLI run lifecycle.
    """

    def setUp(self):
        self.sample_jobs = [
            {
                "title": "Machine Learning Engineer - Early Career",
                "company": "Anthropic",
                "url": "https://jobs.ashbyhq.com/anthropic/sample-1",
                "location": "San Francisco, CA",
                "compensation": "$180,000 - $240,000",
                "snippet": "Working on frontier safety and alignment evaluations."
            },
            {
                "title": "New Grad AI Systems Engineer",
                "company": "OpenAI",
                "url": "https://boards.greenhouse.io/openai/sample-2",
                "location": "New York, NY",
                "compensation": "$190,000 - $250,000",
                "snippet": "Scaling inference clusters and fine-tuning pipelines."
            }
        ]
        self.sample_trace = [
            {"step": 1, "action": "search_web", "action_input": {"query": "ml"}, "observation": "Found 5"},
            {"step": 2, "action": "finish", "action_input": {"report": "Done"}, "observation": "Complete"}
        ]

    def test_generate_run1_report_structure(self):
        """
        Verify that Run 1 report contains title, telemetry, job cards, and provenance.
        """
        meta = {"status": "complete", "step_count": 2, "fetch_count": 1, "tokens_spent": 1200}
        report = generate_run1_report(self.sample_jobs, self.sample_trace, meta)

        self.assertIn("(Run 1)", report)
        self.assertIn("Executive Summary", report)
        self.assertIn("Anthropic", report)
        self.assertIn("OpenAI", report)
        self.assertIn("https://jobs.ashbyhq.com/anthropic/sample-1", report)
        self.assertIn("Data Provenance & Crawl Audit Trail", report)

    def test_generate_run2_report_structure(self):
        """
        Verify that Run 2 report contains New, Still in Top K, and Dropped sections.
        """
        classified = {
            "new_since_last_run": [self.sample_jobs[0]],
            "still_in_top_k": [self.sample_jobs[1]],
            "dropped": [
                {
                    "title": "Old Deprecated ML Intern",
                    "company": "Stripe",
                    "url": "https://stripe.com/jobs/old",
                    "location": "Remote",
                    "snippet": "Role closed"
                }
            ]
        }
        meta = {"status": "complete", "step_count": 3, "fetch_count": 2, "tokens_spent": 1800}
        report = generate_run2_report(classified, self.sample_trace, meta)

        self.assertIn("(Run 2 - Recrawl)", report)
        self.assertIn("Recrawl Differential Summary", report)
        self.assertIn("🟢 New Since Last Run (1)", report)
        self.assertIn("🔵 Still in Top 10 (1)", report)
        self.assertIn("🔴 Dropped Positions (1)", report)
        self.assertIn("Stripe", report)

    def test_save_report_and_trace(self):
        """
        Verify save_report_and_trace writes markdown and json files to disk.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            rep_file, trace_file = save_report_and_trace(
                report_content="# Sample Report",
                trace_data=self.sample_trace,
                run_number=1,
                reports_dir=tmp_path
            )

            self.assertTrue(rep_file.exists())
            self.assertTrue(trace_file.exists())
            self.assertEqual(rep_file.name, "run1.md")
            self.assertEqual(trace_file.name, "run1_trace.json")

            with open(trace_file, "r", encoding="utf-8") as f:
                trace_json = json.load(f)
            self.assertEqual(trace_json["run_number"], 1)
            self.assertEqual(trace_json["total_steps"], 2)

    def test_authenticate_user_success(self):
        """
        Verify authenticate_user handles HTTP 200 response and extracts bearer token.
        """
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"access_token": "mock_jwt_token_123"}

        with patch("httpx.Client.post", return_value=mock_resp):
            token = authenticate_user("NYUgrader", "Courant2026!", "http://localhost:8000")
        self.assertEqual(token, "mock_jwt_token_123")

    def test_run_tracker_lifecycle(self):
        """
        Verify that run_tracker executes with mock agent and creates reports.
        """
        mock_agent_result = {
            "status": "complete",
            "halt_reason": None,
            "step_count": 2,
            "fetch_count": 1,
            "tokens_spent": 500,
            "report": "Mock synthesized report",
            "visited_urls": ["https://boards.greenhouse.io/anduril/1"],
            "trace": [
                {"step": 1, "action": "finish", "action_input": {}, "observation": "done"}
            ]
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            tmp_state = tmp_path / "test_state.json"
            with patch("tracker.run.ResearchAgent.run", return_value=mock_agent_result), \
                 patch("tracker.run.authenticate_user", return_value=None):
                # Test Run 1 with reset
                res1 = run_tracker(
                    reset=True,
                    steps_override=2,
                    skip_login=True,
                    reports_dir=tmp_path,
                    state_file=tmp_state
                )
                self.assertEqual(res1["run_number"], 1)
                self.assertTrue(Path(res1["report_path"]).exists())

                # Test Run 2 immediately after
                res2 = run_tracker(
                    reset=False,
                    steps_override=2,
                    skip_login=True,
                    reports_dir=tmp_path,
                    state_file=tmp_state
                )
                self.assertEqual(res2["run_number"], 2)
                self.assertTrue(Path(res2["report_path"]).exists())


if __name__ == "__main__":
    unittest.main()
