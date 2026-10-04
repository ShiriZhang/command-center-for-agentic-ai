"""
Unit Tests for Tracker Tools CLI Dispatcher (__main__.py).
CSCI-GA.2630 Assignment 1B: Agentic Foundations
"""

import io
import json
import unittest
from unittest.mock import patch

from tracker.tools.__main__ import dispatch_tool


class TestToolsCLIDispatcher(unittest.TestCase):
    """
    Verifies standalone CLI tool execution via python -m tracker.tools.
    """

    def test_dispatch_fetch_article_ssrf_rejection(self):
        """
        Verify CLI dispatch of fetch_article strictly rejects loopback IP.
        """
        captured_stdout = io.StringIO()
        with patch("sys.stdout", captured_stdout):
            exit_code = dispatch_tool(["fetch_article", "http://127.0.0.1:8000/admin"])

        self.assertEqual(exit_code, 0)
        output_data = json.loads(captured_stdout.getvalue())
        self.assertEqual(output_data["status"], "rejected")
        self.assertIn("loopback", output_data["error"])

    def test_dispatch_fetch_article_mocked(self):
        """
        Verify CLI dispatch of fetch_article outputs formatted JSON for safe URLs.
        """
        mock_result = {
            "url": "https://example.com",
            "title": "Example Domain",
            "content": "Clean domain text",
            "status": "fetched",
            "error": None,
            "byte_size": 100,
            "fetch_time_ms": 50
        }

        captured_stdout = io.StringIO()
        with patch("tracker.tools.__main__.fetch_article", return_value=mock_result), \
             patch("sys.stdout", captured_stdout):
            exit_code = dispatch_tool(["fetch_article", "https://example.com"])

        self.assertEqual(exit_code, 0)
        output_data = json.loads(captured_stdout.getvalue())
        self.assertEqual(output_data["status"], "fetched")
        self.assertEqual(output_data["title"], "Example Domain")

    def test_dispatch_search_web_mocked(self):
        """
        Verify CLI dispatch of search_web passes query and limit and prints valid JSON.
        """
        from tracker.tools.search import SearchResultList
        mock_items = [
            {"title": "AI Role 1", "snippet": "Snippet 1", "url": "https://corp.com/job1", "source": "tavily"},
            {"title": "AI Role 2", "snippet": "Snippet 2", "url": "https://corp.com/job2", "source": "aidevboard"}
        ]
        mock_res = SearchResultList(mock_items, query="machine learning")

        captured_stdout = io.StringIO()
        with patch("tracker.tools.__main__.search_web", return_value=mock_res) as mock_search, \
             patch("sys.stdout", captured_stdout):
            exit_code = dispatch_tool(["search_web", "machine learning", "2"])

        self.assertEqual(exit_code, 0)
        mock_search.assert_called_once_with("machine learning", max_results=2)
        output_data = json.loads(captured_stdout.getvalue())
        self.assertEqual(output_data["query"], "machine learning")
        self.assertEqual(len(output_data["results"]), 2)

    def test_dispatch_finish(self):
        """
        Verify CLI dispatch of finish outputs completion JSON.
        """
        captured_stdout = io.StringIO()
        with patch("sys.stdout", captured_stdout):
            exit_code = dispatch_tool(["finish", "My final synthesized report summary."])

        self.assertEqual(exit_code, 0)
        output_data = json.loads(captured_stdout.getvalue())
        self.assertEqual(output_data["status"], "finished")
        self.assertIn("My final synthesized report", output_data["report"])

    def test_dispatch_no_args_returns_error(self):
        """
        Verify that running CLI with no arguments prints help and returns exit code 1.
        """
        captured_stdout = io.StringIO()
        with patch("sys.stdout", captured_stdout):
            exit_code = dispatch_tool([])
        self.assertEqual(exit_code, 1)


if __name__ == "__main__":
    unittest.main()
