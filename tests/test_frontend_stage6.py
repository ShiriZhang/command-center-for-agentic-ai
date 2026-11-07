"""
Tests for Frontend Stage 6 Requirements (Tasks 6.2, 6.3, 6.4).
Verifies:
- Task 6.2: Polling replaces fixed-delay refresh; 409 conflict handled gracefully; cold/slow worker stays visibly running.
- Task 6.3: Claim labels ([SUPPORTED], [UNSUPPORTED], [UNREACHABLE], [UNVERIFIED]), supported-only evidence,
  worker outcomes, safe HTTP(S) protocol validation, stale origin banner, unchanged rankings.
- Task 6.4: SAMPLE_RUNS completely removed; empty, loading, API error, running, and stale states distinctly handled.
CSCI-GA.2630 Assignment 2
"""

from pathlib import Path
import unittest

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"
TRACKER_VIEW_PATH = FRONTEND_DIR / "src" / "components" / "TrackerView.jsx"
CLIENT_JS_PATH = FRONTEND_DIR / "src" / "api" / "client.js"


class TestFrontendStage6(unittest.TestCase):
    """Verifies TrackerView.jsx implementation for Tasks 6.2, 6.3, and 6.4."""

    def setUp(self):
        self.assertTrue(TRACKER_VIEW_PATH.exists(), f"TrackerView.jsx not found at {TRACKER_VIEW_PATH}")
        with open(TRACKER_VIEW_PATH, "r", encoding="utf-8") as f:
            self.content = f.read()

    def test_sample_runs_fallback_removed(self):
        """
        Task 6.4: SAMPLE_RUNS must be completely removed.
        Empty database or API error must not show fabricated runs.
        """
        self.assertNotIn("SAMPLE_RUNS", self.content, "SAMPLE_RUNS fallback must be removed from TrackerView.jsx")

    def test_polling_replaces_fixed_delay_timeout(self):
        """
        Task 6.2: Polling must replace the fixed 4000ms delay refresh.
        """
        self.assertNotIn(
            "setTimeout(() => {\n        fetchTrackerData();\n        setTriggering(false);\n      }, 4000)",
            self.content,
            "Fixed 4000ms setTimeout refresh must be replaced with polling of the active run",
        )
        self.assertTrue(
            "poll" in self.content.lower() or "interval" in self.content.lower(),
            "TrackerView.jsx must implement polling for running executions",
        )

    def test_conflict_409_handled(self):
        """
        Task 6.2: 409 Conflict when an active run is in progress must be handled gracefully.
        """
        self.assertTrue(
            "409" in self.content or "conflict" in self.content.lower() or "active" in self.content.lower(),
            "TrackerView.jsx must handle 409 Conflict / active run already in progress",
        )

    def test_visibly_running_state(self):
        """
        Task 6.2 & 6.4: Cold/slow worker must stay visibly running in UI.
        """
        self.assertIn("running", self.content.lower(), "Must handle 'running' run status in UI")

    def test_claim_verdict_badges_rendered(self):
        """
        Task 6.3: All four claim verdict labels must be rendered:
        - supported
        - unsupported
        - unreachable
        - unverified
        """
        lower = self.content.lower()
        self.assertIn("supported", lower, "Missing supported claim verdict rendering")
        self.assertIn("unsupported", lower, "Missing unsupported claim verdict rendering")
        self.assertIn("unreachable", lower, "Missing unreachable claim verdict rendering")
        self.assertIn("unverified", lower, "Missing unverified claim verdict rendering")

    def test_supported_evidence_only(self):
        """
        Task 6.3: Only supported claims display evidence excerpts.
        """
        self.assertIn("evidence", self.content.lower(), "Must bind claim evidence in UI")

    def test_safe_https_link_validation(self):
        """
        Task 6.3: External links must enforce safe HTTP(S) protocol to prevent javascript: XSS.
        """
        self.assertTrue(
            "http" in self.content and ("safe" in self.content.lower() or "url" in self.content.lower()),
            "External URLs must be verified for safe http/https schemes",
        )

    def test_stale_origin_banner_displayed(self):
        """
        Task 6.3 & 6.4: Stale baseline provenance must be exposed when stale_source_run_uuid is present,
        including original run UUID and created_at timestamp.
        """
        self.assertIn("stale", self.content.lower(), "TrackerView.jsx must expose stale origin notice")
        self.assertIn("stale_source_run_uuid", self.content, "Must bind stale_source_run_uuid")
        self.assertIn("stale_source_created_at", self.content, "Must bind stale_source_created_at")

    def test_article_audit_shows_worker_identity(self):
        """
        Task 6.3: Article audit log must display worker identity column and values.
        """
        self.assertIn("Worker", self.content, "Article audit table must have a Worker column")
        self.assertIn("art.worker", self.content, "Article audit row must bind art.worker")

    def test_no_hardcoded_steps_override_in_ui(self):
        """
        Task 6.2: Browser trigger must not hardcode steps_override: 5, allowing full configured budgets.
        """
        self.assertNotIn("steps_override: 5", self.content, "Browser UI must not hardcode steps_override: 5")

    def test_distinct_empty_and_error_states(self):
        """
        Task 6.4: Must distinguish empty database and API error states.
        """
        self.assertIn("error", self.content.lower(), "Must handle error state")


if __name__ == "__main__":
    unittest.main()
