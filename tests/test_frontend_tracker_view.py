"""
Verification Tests for Frontend TrackerView Component.
CSCI-GA.2630 Assignment 1B: Agentic Foundations

Validates:
1. Zero-Trust Security Policy: Strictly prohibits dangerouslySetInnerHTML to prevent Stored XSS (PDF Req 7).
2. Badge Rendering: Confirms presence of [NEW], [STILL IN TOP 10], and [DROPPED] badge classes and text.
3. Controls: Confirms existence of 'Run Tracker Now' trigger button and '--reset' toggle.
4. Audit & History: Confirms Run History selector and Network Fetch Audit table structures.
"""

import unittest
from pathlib import Path

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"
TRACKER_VIEW_PATH = FRONTEND_DIR / "src" / "components" / "TrackerView.jsx"


class TestFrontendTrackerView(unittest.TestCase):
    """
    Verifies frontend TrackerView JSX code structure and security compliance.
    """

    def setUp(self):
        self.assertTrue(TRACKER_VIEW_PATH.exists(), f"TrackerView.jsx not found at {TRACKER_VIEW_PATH}")
        with open(TRACKER_VIEW_PATH, "r", encoding="utf-8") as f:
            self.content = f.read()

    def test_zero_trust_prohibits_dangerously_set_inner_html(self):
        """
        CRITICAL SECURITY REQUIREMENT (PDF Req 7 & Design Dec 7):
        Strictly prohibit dangerouslySetInnerHTML in TrackerView to neutralize Stored-XSS attacks.
        """
        self.assertNotIn(
            "dangerouslySetInnerHTML",
            self.content,
            "CRITICAL VULNERABILITY: TrackerView.jsx contains dangerouslySetInnerHTML! Must use pure text nodes."
        )

    def test_differential_badges_implemented(self):
        """
        Verify that all 3 multi-run badge states are rendered:
        - [NEW]
        - [STILL IN TOP 10]
        - [DROPPED]
        """
        self.assertIn("[NEW]", self.content, "Missing [NEW] status badge")
        self.assertIn("[STILL IN TOP 10]", self.content, "Missing [STILL IN TOP 10] status badge")
        self.assertIn("[DROPPED]", self.content, "Missing [DROPPED] status badge")

    def test_run_tracker_now_trigger_button(self):
        """
        Verify presence of 'Run Tracker Now' trigger button and '--reset' option.
        """
        self.assertIn("Run Tracker Now", self.content, "Missing 'Run Tracker Now' trigger button")
        self.assertIn("--reset", self.content, "Missing '--reset' flag option")
        self.assertIn("handleTriggerRun", self.content, "Missing trigger handler function")

    def test_run_history_and_fetch_audit_elements(self):
        """
        Verify presence of Run History selector and Network Fetch Audit table.
        """
        self.assertIn("Execution Run History", self.content, "Missing Execution Run History section")
        self.assertIn("Network Fetch Audit Log", self.content, "Missing Network Fetch Audit Log table")
        self.assertIn("SSRF Guardrail", self.content, "Missing SSRF Guardrail audit column/label")

    def test_source_provenance_links(self):
        """
        Verify that job cards render clickable primary source URLs with safe rel attributes.
        """
        self.assertIn("primary_url", self.content, "Missing primary_url field binding")
        self.assertIn('rel="noopener noreferrer"', self.content, "Links must have rel='noopener noreferrer' for safety")

    def test_audit_table_article_title_column(self):
        """
        Verify presence of Article Title column in Network Fetch Audit Log table (Requirement 13).
        """
        self.assertIn("Article Title", self.content, "Missing Article Title column in Network Fetch Audit Log table")
        self.assertIn("art.title", self.content, "Missing art.title field binding in table rows")

    def test_skipped_cached_badge_rendered(self):
        """
        Verify Requirement 7 & 11: Dedicated [SKIPPED - CACHED] status badge is rendered
        for articles with status 'skipped as already seen'.
        """
        self.assertIn("[SKIPPED - CACHED]", self.content, "Missing [SKIPPED - CACHED] badge in audit table")
        self.assertIn("skipped as already seen", self.content, "Missing 'skipped as already seen' branch handling")


if __name__ == "__main__":
    unittest.main()
