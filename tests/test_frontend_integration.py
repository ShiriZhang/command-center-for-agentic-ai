"""
Verification Tests for Frontend Navigation and Tracker Integration.
CSCI-GA.2630 Assignment 1B: Agentic Foundations

Validates:
1. Navbar.jsx provides the 'Intelligence Tracker' navigation tab.
2. App.jsx mounts TrackerView when currentTab === 'tracker'.
3. client.js exports all required tracker API methods.
4. HomeView.jsx provides launch link to the Agentic Tracker.
"""

import unittest
from pathlib import Path

FRONTEND_SRC = Path(__file__).resolve().parent.parent / "frontend" / "src"


class TestFrontendIntegration(unittest.TestCase):
    """
    Verifies frontend integration files, navigation tabs, and API client bindings.
    """

    def test_client_js_tracker_methods_exported(self):
        """
        Verify frontend/src/api/client.js exports all required tracker API methods.
        """
        client_js_path = FRONTEND_SRC / "api" / "client.js"
        self.assertTrue(client_js_path.exists())
        with open(client_js_path, "r", encoding="utf-8") as f:
            content = f.read()

        expected_methods = [
            "getTrackerRuns",
            "getTrackerRunById",
            "createTrackerRun",
            "triggerTracker",
            "getTrackerHistory",
            "clearTrackerRuns",
        ]
        for method in expected_methods:
            self.assertIn(method, content, f"Missing method {method} in client.js")

    def test_navbar_jsx_tracker_tab(self):
        """
        Verify frontend/src/components/Navbar.jsx contains Tracker navigation tab.
        """
        navbar_path = FRONTEND_SRC / "components" / "Navbar.jsx"
        self.assertTrue(navbar_path.exists())
        with open(navbar_path, "r", encoding="utf-8") as f:
            content = f.read()

        self.assertIn("tracker", content, "Navbar.jsx must support 'tracker' tab key")
        self.assertIn("Intelligence Tracker", content, "Navbar.jsx must display 'Intelligence Tracker' text")

    def test_app_jsx_tracker_view_mount(self):
        """
        Verify frontend/src/App.jsx imports TrackerView and mounts it.
        """
        app_path = FRONTEND_SRC / "App.jsx"
        self.assertTrue(app_path.exists())
        with open(app_path, "r", encoding="utf-8") as f:
            content = f.read()

        self.assertIn("TrackerView", content, "App.jsx must import TrackerView")
        self.assertIn("currentTab === 'tracker'", content, "App.jsx must render TrackerView when currentTab is 'tracker'")

    def test_homeview_jsx_tracker_launch(self):
        """
        Verify frontend/src/components/HomeView.jsx links to onNavigateToTracker.
        """
        homeview_path = FRONTEND_SRC / "components" / "HomeView.jsx"
        self.assertTrue(homeview_path.exists())
        with open(homeview_path, "r", encoding="utf-8") as f:
            content = f.read()

        self.assertIn("onNavigateToTracker", content, "HomeView.jsx must support onNavigateToTracker")
        self.assertIn("Launch Tracker", content, "HomeView.jsx must provide 'Launch Tracker' button")


if __name__ == "__main__":
    unittest.main()
