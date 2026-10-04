"""
Unit Tests for Native Agent State Machine and Budget Enforcement.
CSCI-GA.2630 Assignment 1B: Agentic Foundations
"""

import json
import unittest
from unittest.mock import MagicMock, patch

from tracker.agent import ResearchAgent
from tracker.config import TrackerConfig, load_tracker_config


class TestAgentRuntime(unittest.TestCase):
    """
    Test suite verifying handwritten agent state machine, budget enforcement,
    and partial report synthesis.
    """

    def setUp(self):
        self.config = load_tracker_config()

    def _create_mock_tool_call(self, call_id: str, fn_name: str, fn_args: dict):
        tc = MagicMock()
        tc.id = call_id
        tc.type = "function"
        tc.function.name = fn_name
        tc.function.arguments = json.dumps(fn_args)
        return tc

    def test_step_budget_enforcement_and_partial_report(self):
        """
        Verify that agent halts strictly when max_steps is reached,
        producing a report marked status='partial'.
        """
        mock_llm = MagicMock()
        mock_llm.cumulative_total_tokens = 500

        # Model constantly issues search_web calls without calling finish
        search_tc = self._create_mock_tool_call("call_1", "search_web", {"query": "ml engineer"})
        mock_msg = MagicMock()
        mock_msg.content = "Searching for roles..."
        mock_msg.tool_calls = [search_tc]

        mock_resp = MagicMock()
        mock_resp.choices = [MagicMock()]
        mock_resp.choices[0].message = mock_msg
        mock_llm.create_completion.return_value = mock_resp

        # Initialize agent with max_steps = 2
        agent = ResearchAgent(config=self.config, llm_client=mock_llm)
        agent.max_steps = 2

        with patch("tracker.agent.search_web") as mock_search:
            from tracker.tools.search import SearchResultList
            mock_search.return_value = SearchResultList([
                {"title": "OpenAI Role", "snippet": "Research engineer", "url": "https://openai.com/careers/1", "source": "tavily"}
            ])
            result = agent.run(max_steps=2)

        self.assertEqual(result["status"], "partial")
        self.assertIn("step budget", result["halt_reason"].lower())
        self.assertEqual(result["step_count"], 2)
        # Must include PARTIAL banner in the synthesized report
        self.assertIn("PARTIAL", result["report"])
        self.assertIn("Discovered & Verified Opportunities", result["report"])

    def test_fetch_budget_enforcement(self):
        """
        Verify that agent enforces max_fetches limit and ceases fetching when exhausted.
        """
        mock_llm = MagicMock()
        mock_llm.cumulative_total_tokens = 300

        fetch_tc = self._create_mock_tool_call("call_f", "fetch_article", {"url": "https://corp.com/job"})
        mock_msg = MagicMock()
        mock_msg.content = "Fetching job..."
        mock_msg.tool_calls = [fetch_tc]

        mock_resp = MagicMock()
        mock_resp.choices = [MagicMock()]
        mock_resp.choices[0].message = mock_msg
        mock_llm.create_completion.return_value = mock_resp

        agent = ResearchAgent(config=self.config, llm_client=mock_llm)
        agent.max_fetches = 2
        agent.max_steps = 10

        with patch("tracker.agent.fetch_article") as mock_fetch:
            mock_fetch.return_value = {
                "url": "https://corp.com/job",
                "title": "ML Role",
                "content": "Job description text",
                "status": "fetched",
                "byte_size": 200,
                "fetch_time_ms": 50
            }
            result = agent.run(max_steps=5)

        self.assertEqual(result["status"], "partial")
        self.assertIn("fetch budget", result["halt_reason"].lower())
        self.assertEqual(agent.fetch_count, 2)
        self.assertIn("PARTIAL", result["report"])

    def test_token_budget_enforcement(self):
        """
        Verify that agent halts when cumulative tokens exceed token_budget.
        """
        mock_llm = MagicMock()
        # Pretend LLM already spent 150,000 tokens (budget is 100,000)
        mock_llm.cumulative_total_tokens = 150000

        agent = ResearchAgent(config=self.config, llm_client=mock_llm)
        agent.token_budget = 100000

        result = agent.run(max_steps=5)
        self.assertEqual(result["status"], "partial")
        self.assertIn("token spend budget", result["halt_reason"].lower())

    def test_clean_completion_via_finish(self):
        """
        Verify that agent returns status='complete' when finish(report) is invoked.
        """
        mock_llm = MagicMock()
        mock_llm.cumulative_total_tokens = 800

        report_markdown = "# Top 10 ML Roles\n1. Role at Anthropic..."
        finish_tc = self._create_mock_tool_call("call_fin", "finish", {"report": report_markdown})
        mock_msg = MagicMock()
        mock_msg.content = "Concluded research."
        mock_msg.tool_calls = [finish_tc]

        mock_resp = MagicMock()
        mock_resp.choices = [MagicMock()]
        mock_resp.choices[0].message = mock_msg
        mock_llm.create_completion.return_value = mock_resp

        agent = ResearchAgent(config=self.config, llm_client=mock_llm)
        result = agent.run(max_steps=5)

        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["report"], report_markdown)
        self.assertEqual(len(result["trace"]), 1)
        self.assertEqual(result["trace"][0]["action"], "finish")


if __name__ == "__main__":
    unittest.main()
