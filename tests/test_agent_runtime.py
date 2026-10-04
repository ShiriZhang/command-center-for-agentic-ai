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
        # Trace contains model completion call + finish tool call
        self.assertEqual(len(result["trace"]), 2)
        self.assertEqual(result["trace"][0]["tool"], "model")
        self.assertEqual(result["trace"][1]["action"], "finish")

    def test_model_call_trace_logging(self):
        """
        Verify Requirement 13: Model calls are logged with step, tool, arguments,
        status, latency, and tokens.
        """
        mock_llm = MagicMock()
        mock_llm.cumulative_total_tokens = 1200

        finish_tc = self._create_mock_tool_call("call_1", "finish", {"report": "# Final Report"})
        mock_msg = MagicMock()
        mock_msg.content = "All done."
        mock_msg.tool_calls = [finish_tc]

        mock_usage = MagicMock()
        mock_usage.prompt_tokens = 500
        mock_usage.completion_tokens = 150
        mock_usage.total_tokens = 650

        mock_resp = MagicMock()
        mock_resp.usage = mock_usage
        mock_resp.choices = [MagicMock()]
        mock_resp.choices[0].message = mock_msg
        mock_llm.create_completion.return_value = mock_resp

        agent = ResearchAgent(config=self.config, llm_client=mock_llm)
        result = agent.run(max_steps=3)

        model_traces = [t for t in result["trace"] if t.get("tool") == "model"]
        self.assertTrue(len(model_traces) >= 1)
        m_trace = model_traces[0]
        self.assertEqual(m_trace["tool"], "model")
        self.assertEqual(m_trace["step"], 1)
        self.assertEqual(m_trace["status"], "success")
        self.assertIn("latency", m_trace)
        self.assertGreaterEqual(m_trace["latency"], 0.0)
        self.assertIn("tokens", m_trace)
        self.assertEqual(m_trace["tokens"]["prompt_tokens"], 500)
        self.assertEqual(m_trace["tokens"]["completion_tokens"], 150)
        self.assertEqual(m_trace["tokens"]["total_tokens"], 650)

    def test_tool_call_trace_logging(self):
        """
        Verify Requirement 13: Tool calls are logged with step, tool, arguments,
        status, latency, and tokens.
        """
        mock_llm = MagicMock()
        mock_llm.cumulative_total_tokens = 950

        search_tc = self._create_mock_tool_call("call_s", "search_web", {"query": "ml engineer", "max_results": 3})
        finish_tc = self._create_mock_tool_call("call_f", "finish", {"report": "# Final Report"})

        msg1 = MagicMock()
        msg1.content = "Searching..."
        msg1.tool_calls = [search_tc]

        msg2 = MagicMock()
        msg2.content = "Finishing..."
        msg2.tool_calls = [finish_tc]

        resp1 = MagicMock()
        resp1.usage = None
        resp1.choices = [MagicMock(message=msg1)]

        resp2 = MagicMock()
        resp2.usage = None
        resp2.choices = [MagicMock(message=msg2)]

        mock_llm.create_completion.side_effect = [resp1, resp2]

        agent = ResearchAgent(config=self.config, llm_client=mock_llm)
        with patch("tracker.agent.search_web") as mock_search:
            from tracker.tools.search import SearchResultList
            mock_search.return_value = SearchResultList([
                {"title": "Role 1", "snippet": "Snip", "url": "https://example.com/1", "source": "tavily"}
            ])
            result = agent.run(max_steps=5)

        # Find tool trace for search_web
        tool_traces = [t for t in result["trace"] if t.get("tool") == "search_web"]
        self.assertTrue(len(tool_traces) >= 1)
        st = tool_traces[0]
        self.assertEqual(st["tool"], "search_web")
        self.assertEqual(st["action"], "search_web")
        self.assertEqual(st["arguments"], {"query": "ml engineer", "max_results": 3})
        self.assertEqual(st["status"], "success")
        self.assertIn("latency", st)
        self.assertGreaterEqual(st["latency"], 0.0)
        self.assertIn("tokens", st)

    def test_skipped_as_already_seen_cache_guard(self):
        """
        Verify Requirement 7 & 11: In Run 2 recrawl, URLs present in previous_urls
        are intercepted with status: "skipped as already seen", preventing network
        requests and without incrementing fetch_count.
        """
        mock_llm = MagicMock()
        mock_llm.cumulative_total_tokens = 450

        seen_url = "https://example.com/cached-job-posting"
        fetch_tc = self._create_mock_tool_call("call_f", "fetch_article", {"url": seen_url})
        finish_tc = self._create_mock_tool_call("call_end", "finish", {"report": "# Final Report"})

        msg1 = MagicMock()
        msg1.content = "Attempting to inspect cached URL..."
        msg1.tool_calls = [fetch_tc]

        msg2 = MagicMock()
        msg2.content = "Concluded research."
        msg2.tool_calls = [finish_tc]

        resp1 = MagicMock()
        resp1.usage = None
        resp1.choices = [MagicMock(message=msg1)]

        resp2 = MagicMock()
        resp2.usage = None
        resp2.choices = [MagicMock(message=msg2)]

        mock_llm.create_completion.side_effect = [resp1, resp2]

        agent = ResearchAgent(config=self.config, llm_client=mock_llm)
        with patch("tracker.agent.fetch_article") as mock_fetch:
            result = agent.run(max_steps=5, previous_urls={seen_url})
            mock_fetch.assert_not_called()

        # Check fetch_count was NOT incremented
        self.assertEqual(agent.fetch_count, 0)
        self.assertEqual(result["fetch_count"], 0)

        # Check fetched_articles contains the skipped record
        skipped_arts = [a for a in agent.fetched_articles if a.get("url") == seen_url]
        self.assertEqual(len(skipped_arts), 1)
        self.assertEqual(skipped_arts[0]["status"], "skipped as already seen")

        # Check execution trace logs status: "skipped as already seen"
        fetch_traces = [t for t in result["trace"] if t.get("tool") == "fetch_article"]
        self.assertEqual(len(fetch_traces), 1)
        ft = fetch_traces[0]
        self.assertEqual(ft["tool"], "fetch_article")
        self.assertEqual(ft["status"], "skipped as already seen")
        self.assertEqual(ft["arguments"], {"url": seen_url})


if __name__ == "__main__":
    unittest.main()
