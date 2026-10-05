"""
Unit Test Suite for fetch_article SSRF Guardrails, Content Sanitization,
Episodic Memory Cache Interception, and Direct ATS Fetching.
CSCI-GA.2630 Assignment 1B: Agentic Foundations
"""

import sys
import unittest
from unittest.mock import patch, MagicMock
from pathlib import Path

# Add project root to sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from tracker.tools.fetch import fetch_article, validate_url_ssrf, clean_html_to_text
from tracker.memory.episodic import EpisodicMemory
from tracker.memory.working import WorkingMemory
from tracker.agent import ResearchAgent


class TestFetchArticleGuardrails(unittest.TestCase):

    def test_reject_loopback_ipv4(self):
        """Verify that loopback 127.0.0.1 is strictly rejected before socket connection."""
        res = fetch_article("http://127.0.0.1:8000/admin")
        self.assertEqual(res["status"], "rejected")
        self.assertIn("loopback", res["error"].lower())

    def test_reject_localhost_hostname(self):
        """Verify that 'localhost' resolving to 127.0.0.1 is strictly rejected."""
        res = fetch_article("http://localhost:8000/healthz")
        self.assertEqual(res["status"], "rejected")
        self.assertIn("loopback", res["error"].lower())

    def test_reject_cloud_metadata_link_local(self):
        """Verify that AWS/Cloud metadata address 169.254.169.254 is rejected."""
        res = fetch_article("http://169.254.169.254/latest/meta-data")
        self.assertEqual(res["status"], "rejected")
        self.assertTrue("link-local" in res["error"].lower() or "blocked" in res["error"].lower())

    def test_reject_private_rfc1918_addresses(self):
        """Verify that private IP ranges (10.0.0.0/8, 192.168.0.0/16) are rejected."""
        res_class_a = fetch_article("http://10.1.2.3:8080/internal")
        self.assertEqual(res_class_a["status"], "rejected")
        self.assertIn("private", res_class_a["error"].lower())

        res_class_c = fetch_article("http://192.168.1.1/router")
        self.assertEqual(res_class_c["status"], "rejected")
        self.assertIn("private", res_class_c["error"].lower())

    def test_reject_non_http_schemes(self):
        """Verify that file:// and ftp:// are rejected at the scheme validation step."""
        is_safe, error, _ = validate_url_ssrf("file:///etc/passwd")
        self.assertFalse(is_safe)
        self.assertIn("forbidden scheme", error.lower())

        is_safe_ftp, error_ftp, _ = validate_url_ssrf("ftp://example.com")
        self.assertFalse(is_safe_ftp)
        self.assertIn("forbidden scheme", error_ftp.lower())

    def test_html_script_decomposition(self):
        """Verify that malicious script tags seeded in untrusted pages are stripped."""
        malicious_html = """
        <html>
            <head><title>Test Job Posting</title></head>
            <body>
                <h1>Staff Research Engineer</h1>
                <script>alert('Stored XSS Vulnerability'); window.location='http://attacker.com';</script>
                <p>We are hiring an ML Engineer in New York.</p>
                <style>body { display: none; }</style>
            </body>
        </html>
        """
        title, clean_text = clean_html_to_text(malicious_html)
        self.assertEqual(title, "Test Job Posting")
        self.assertIn("Staff Research Engineer", clean_text)
        self.assertIn("We are hiring an ML Engineer", clean_text)
        # Ensure script code is NOT present in text
        self.assertNotIn("alert", clean_text)
        self.assertNotIn("attacker.com", clean_text)
        self.assertNotIn("display: none", clean_text)

    def test_fetch_legitimate_public_url(self):
        """Verify that public internet URLs pass SSRF validation and fetch properly."""
        res = fetch_article("https://example.com")
        self.assertEqual(res["status"], "fetched")
        self.assertIsNone(res["error"])
        self.assertGreater(res["byte_size"], 0)
        self.assertIn("Example Domain", res["title"])
        self.assertIn("Example Domain", res["content"])

    def test_fetch_article_with_episodic_memory_cache_hit(self):
        """
        Verify that URLs already recorded in EpisodicMemory are intercepted
        with status 'cached_active' and error=None without making network calls.
        """
        mock_episodic = MagicMock()
        mock_episodic.is_url_known.return_value = True
        mock_episodic.get_cached_job_info.return_value = {
            "url": "https://boards.greenhouse.io/openai/jobs/101",
            "title": "Machine Learning Engineer",
            "content": "Deep learning research role.",
            "status": "cached_active",
            "cached": True,
            "error": None
        }

        with patch("httpx.Client.get") as mock_get:
            res = fetch_article("https://boards.greenhouse.io/openai/jobs/101", episodic_memory=mock_episodic)
            mock_get.assert_not_called()

        self.assertEqual(res["status"], "cached_active")
        self.assertIsNone(res["error"])
        self.assertEqual(res["title"], "Machine Learning Engineer")

    def test_direct_ats_link_fetching_without_search(self):
        """
        Verify that direct ATS URLs (Greenhouse, Lever, Ashby) can be fetched
        directly via fetch_article without requiring intermediate search calls.
        """
        html_payload = """
        <html>
            <head><title>Anthropic - Research Engineer</title></head>
            <body>
                <h1>Research Engineer</h1>
                <p>Location: San Francisco, CA. Building trustworthy AI systems.</p>
            </body>
        </html>
        """
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = html_payload.encode("utf-8")
        mock_resp.headers = {}
        mock_resp.encoding = "utf-8"

        with patch("tracker.tools.fetch.validate_url_ssrf", return_value=(True, None, "1.2.3.4")), \
             patch("httpx.Client.get", return_value=mock_resp):
            res = fetch_article("https://jobs.lever.co/anthropic/456")

        self.assertEqual(res["status"], "fetched")
        self.assertIsNone(res["error"])
        self.assertIn("Anthropic - Research Engineer", res["title"])
        self.assertIn("trustworthy AI systems", res["content"])

    def test_agent_dispatch_intercepts_cached_url_without_fetch_budget_decrement(self):
        """
        Verify that ResearchAgent._execute_tool_call intercepts cached URLs via EpisodicMemory,
        records them into WorkingMemory, and preserves the fetch budget.
        """
        agent = ResearchAgent()
        cached_url = "https://boards.greenhouse.io/scaleai/jobs/cached-1"
        agent.episodic_memory.known_urls.add(cached_url)

        res, is_finish = agent._execute_tool_call("fetch_article", {"url": cached_url})

        self.assertEqual(res["status"], "skipped as already seen")
        self.assertIsNone(res["error"])
        self.assertEqual(agent.fetch_count, 0)
        self.assertFalse(is_finish)
        # Working memory should have recorded the verified role
        self.assertEqual(len(agent.working_memory.verified_jobs), 1)

    def test_agent_dispatch_direct_ats_fetch_updates_working_memory(self):
        """
        Verify that ResearchAgent._execute_tool_call on a direct ATS URL
        fetches the URL, increments fetch_count, and registers the verified role in WorkingMemory.
        """
        agent = ResearchAgent()
        ats_url = "https://boards.greenhouse.io/corp/jobs/999"

        html_payload = """
        <html><head><title>Junior AI Engineer</title></head>
        <body><p>Role requirements and details.</p></body></html>
        """
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = html_payload.encode("utf-8")
        mock_resp.headers = {}
        mock_resp.encoding = "utf-8"

        with patch("tracker.tools.fetch.validate_url_ssrf", return_value=(True, None, "1.2.3.4")), \
             patch("httpx.Client.get", return_value=mock_resp):
            res, is_finish = agent._execute_tool_call("fetch_article", {"url": ats_url})

        self.assertEqual(res["status"], "fetched")
        self.assertIsNone(res["error"])
        self.assertEqual(agent.fetch_count, 1)
        self.assertEqual(len(agent.working_memory.verified_jobs), 1)
        self.assertEqual(agent.working_memory.verified_jobs[0]["title"], "Junior AI Engineer")


if __name__ == "__main__":
    unittest.main()
