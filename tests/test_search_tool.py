"""
Unit Tests for search_web Tool and Candidate Discovery Seeding.
CSCI-GA.2630 Assignment 1B: Agentic Foundations
"""

import unittest
from unittest.mock import patch, MagicMock

from tracker.tools.search import (
    SearchResultList,
    search_tavily,
    discover_aidevboard_candidates,
    search_web
)


class TestSearchTool(unittest.TestCase):
    """
    Test suite for search_web, Tavily integration, and AI Dev Jobs candidate discovery.
    """

    def test_search_result_list_dual_interface(self):
        """
        Verify SearchResultList satisfies both list-indexing/iteration contracts
        and dictionary-access contracts (res['results'], res['query'], res.to_dict()).
        """
        raw_items = [
            {"title": "Role A", "snippet": "Snippet A", "url": "https://company.com/job1", "source": "tavily"},
            {"title": "Role B", "snippet": "Snippet B", "url": "https://company.com/job2", "source": "aidevboard"},
        ]
        s_list = SearchResultList(raw_items, query="test query")

        # 1. List interface
        self.assertEqual(len(s_list), 2)
        self.assertEqual(s_list[0]["title"], "Role A")
        self.assertEqual(s_list[1]["title"], "Role B")
        self.assertTrue(isinstance(s_list, list))
        extracted_titles = [item["title"] for item in s_list]
        self.assertEqual(extracted_titles, ["Role A", "Role B"])

        # 2. Dictionary-like interface
        self.assertEqual(s_list["query"], "test query")
        self.assertEqual(s_list["total_results"], 2)
        self.assertEqual(len(s_list["results"]), 2)
        self.assertEqual(s_list.get("query"), "test query")
        self.assertEqual(len(s_list.get("results")), 2)

        # 3. Serialization
        dict_rep = s_list.to_dict()
        self.assertIn("query", dict_rep)
        self.assertIn("results", dict_rep)
        self.assertEqual(len(dict_rep["results"]), 2)

    def test_missing_tavily_api_key_terminal_failure(self):
        """
        Verify that search_tavily raises a terminal ValueError if no API key is provided.
        """
        with patch("tracker.tools.search.config.tavily_api_key", None), \
             patch.dict("os.environ", {}, clear=True):
            with self.assertRaises(ValueError) as ctx:
                search_tavily("test", api_key=None)
            self.assertIn("[TERMINAL FAILURE]", str(ctx.exception))

    def test_aidevboard_candidates_extraction(self):
        """
        Verify candidate discovery extracts direct ATS apply_url and normalizes fields.
        """
        mock_api_response = {
            "jobs": [
                {
                    "title": "Junior Machine Learning Engineer",
                    "company_name": "OpenAI Partner",
                    "experience_level": "entry_level",
                    "description": "Looking for entry level ML engineers with PyTorch experience.",
                    "tags": ["python", "pytorch", "ml"],
                    "apply_url": "https://boards.greenhouse.io/partner/jobs/12345",
                    "url": "https://aidevboard.com/job/sample-id-1",
                    "salary_min": 120000,
                    "salary_max": 150000,
                    "location": "New York, NY"
                }
            ]
        }

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = mock_api_response

        with patch("httpx.Client.get", return_value=mock_resp):
            candidates = discover_aidevboard_candidates(query="entry level ml engineer", max_results=3)

        self.assertEqual(len(candidates), 1)
        cand = candidates[0]
        # Must prioritize direct Greenhouse ATS URL over aggregator URL
        self.assertEqual(cand["url"], "https://boards.greenhouse.io/partner/jobs/12345")
        self.assertIn("OpenAI Partner", cand["title"])
        self.assertIn("Snippet", "Snippet" if cand["snippet"] else "")
        self.assertIn("120,000", cand["snippet"])
        self.assertEqual(cand["source"], "aidevboard")

    def test_search_web_url_deduplication(self):
        """
        Verify that search_web deduplicates results across sources by canonical URL.
        """
        mock_tavily_results = [
            {"title": "Role 1", "snippet": "Snippet 1", "url": "https://job-boards.greenhouse.io/corp/jobs/101", "source": "tavily"}
        ]
        mock_aidevboard_results = [
            {"title": "Role 1 Duplicate", "snippet": "Snippet 1 dup", "url": "https://job-boards.greenhouse.io/corp/jobs/101/", "source": "aidevboard"},
            {"title": "Role 2 Unique", "snippet": "Snippet 2", "url": "https://jobs.ashbyhq.com/corp2/202", "source": "aidevboard"}
        ]

        with patch("tracker.tools.search.search_tavily", return_value=mock_tavily_results), \
             patch("tracker.tools.search.discover_aidevboard_candidates", return_value=mock_aidevboard_results):
            results = search_web("ml jobs", max_results=5)

        # The duplicate greenhouse URL should be merged/filtered out
        self.assertEqual(len(results), 2)
        urls = [r["url"] for r in results]
        self.assertEqual(urls[0], "https://job-boards.greenhouse.io/corp/jobs/101")
        self.assertEqual(urls[1], "https://jobs.ashbyhq.com/corp2/202")

    def test_live_or_mocked_normalized_fields(self):
        """
        Verify that every result returned by search_web contains normalized
        title, snippet, url, and source fields.
        """
        results = search_web("entry level machine learning engineer 2026", max_results=4)
        self.assertGreater(len(results), 0, "search_web should return at least 1 result")

        for r in results:
            self.assertIn("title", r)
            self.assertIn("snippet", r)
            self.assertIn("url", r)
            self.assertIn("source", r)
            self.assertTrue(r["title"], "title must not be empty")
            self.assertTrue(r["snippet"], "snippet must not be empty")
            self.assertTrue(r["url"].startswith("http"), "url must start with http or https")


if __name__ == "__main__":
    unittest.main()
