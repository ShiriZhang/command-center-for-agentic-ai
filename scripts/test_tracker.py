"""
================================================================================
CSCI-GA.2630 Assignment 1B: Agentic Foundations
Automated Verification Script for Autonomous Agentic Tracker
================================================================================

Exercises and verifies the four core architectural pillars mandated by the specification:
1. SSRF Guardrail Attacks:
   - Loopback IPs (127.0.0.1, localhost)
   - RFC 1918 Private ranges (10.0.0.1, 192.168.1.1, 172.16.0.1)
   - Cloud Link-Local Metadata (169.254.169.254)
   - Disallowed Schemes (ftp://, file://, gopher://)
   - Hop-by-Hop Redirect SSRF bounce defense

2. Bogus API Key Terminal Handling:
   - Upstream 401 Unauthorized / AuthenticationError
   - Immediate Fail-Fast with ZERO retries (no infinite backoff loops)

3. Budget Exhaustion & Partial Reporting:
   - Step budget enforcement (max_steps cap)
   - Graceful termination producing report with status "partial"
   - Telemetry logging of halt reason and token/step usage

4. Two-Run Recrawl Differentiation:
   - Run 1 (Initial Crawl) vs Run 2 (Differential Recrawl)
   - Persistence of visited URLs and state caching
   - Three-way classification:
     * "New since last run"
     * "Still in top K"
     * "Dropped"
   - Markdown report synthesis with distinct sections and provenance citations
================================================================================
"""

import os
import sys
import socket
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
BACKEND_DIR = PROJECT_ROOT / "backend"
sys.path.insert(0, str(BACKEND_DIR))

# Reconfigure stdout for cross-platform UTF-8 support
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from tracker.tools.fetch import fetch_article
from tracker.llm import LLMClient, TerminalLLMError
from tracker.agent import ResearchAgent
from tracker.config import config, LimitsConfig

from tracker.memory import RecrawlMemoryManager
from tracker.reporter import generate_run1_report, generate_run2_report
from openai import AuthenticationError


# ==============================================================================
# 1. SSRF Guardrail Attacks Test Suite
# ==============================================================================

class TestSSRFGuardrailAttacks(unittest.TestCase):
    """
    Exercises multi-vector network SSRF attacks against fetch_article.
    """

    def test_loopback_rejection(self):
        """Verifies rejection of loopback IPv4 and localhost."""
        for target in ["http://127.0.0.1:8000/admin", "http://127.0.0.1", "http://localhost:8000/secret"]:
            res = fetch_article(target)
            self.assertEqual(res["status"], "rejected", f"Failed to reject loopback: {target}")
            self.assertIn("Guardrail rejection", res["error"])

    def test_private_rfc1918_rejection(self):
        """Verifies rejection of private network subnets (10.x, 172.16.x, 192.168.x)."""
        private_ips = [
            "http://10.0.0.1/internal-api",
            "http://192.168.1.1/router-console",
            "http://172.16.0.1/finance-db"
        ]
        for target in private_ips:
            res = fetch_article(target)
            self.assertEqual(res["status"], "rejected", f"Failed to reject RFC 1918 IP: {target}")
            self.assertIn("Guardrail rejection", res["error"])

    def test_link_local_cloud_metadata_rejection(self):
        """Verifies rejection of AWS/GCP/Azure link-local metadata address."""
        target = "http://169.254.169.254/latest/meta-data/"
        res = fetch_article(target)
        self.assertEqual(res["status"], "rejected")
        self.assertIn("link-local", res["error"].lower())

    def test_disallowed_schemes_rejection(self):
        """Verifies rejection of non-http(s) schemes (ftp, file, gopher)."""
        disallowed = [
            "ftp://files.example.com/dump.sql",
            "file:///etc/passwd",
            "gopher://127.0.0.1:70/"
        ]
        for target in disallowed:
            res = fetch_article(target)
            self.assertEqual(res["status"], "rejected", f"Failed to reject disallowed scheme: {target}")
            self.assertIn("scheme", res["error"].lower())

    def test_hop_by_hop_redirect_ssrf_blocked(self):
        """
        Verifies Hop-by-Hop redirect inspection prevents redirect bounce attacks.
        Public URL redirects to internal 127.0.0.1 -> second hop DNS blocks connection.
        """
        import httpx

        mock_redirect_resp = MagicMock()
        mock_redirect_resp.status_code = 302
        mock_redirect_resp.headers = {"Location": "http://127.0.0.1:8000/internal-admin"}

        # Patch httpx.Client to return a 302 redirect on first request
        with patch("httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client_cls.return_value.__enter__.return_value = mock_client
            mock_client.get.return_value = mock_redirect_resp

            real_getaddrinfo = socket.getaddrinfo
            def fake_dns(host, port, *args, **kwargs):
                if host == "public-redirector.com":
                    return [(2, 1, 6, "", ("93.184.216.34", port))]
                return real_getaddrinfo(host, port, *args, **kwargs)

            with patch("socket.getaddrinfo", side_effect=fake_dns):
                res = fetch_article("http://public-redirector.com/link")
                
                # Must reject when following Location to 127.0.0.1
                self.assertEqual(res["status"], "rejected")
                self.assertIn("loopback", res["error"].lower())



# ==============================================================================
# 2. Bogus API Key Terminal Handling Test Suite
# ==============================================================================

class TestBogusAPIKeyTerminalHandling(unittest.TestCase):
    """
    Exercises LLM failure classifier and verifies fail-fast termination on invalid credentials.
    """

    def test_missing_api_key_terminal_fail_fast(self):
        """Verifies that missing API key halts immediately with TerminalLLMError before request."""
        client = LLMClient(api_key="missing_key", provider="openrouter")
        with self.assertRaises(TerminalLLMError) as ctx:
            client.create_completion([{"role": "user", "content": "Hello"}])
        self.assertIn("Missing API key", str(ctx.exception))
        self.assertEqual(client.call_count, 0)

    def test_bogus_api_key_zero_retries(self):
        """
        Verifies that upstream HTTP 401 AuthenticationError triggers immediate
        fail-fast termination with ZERO retries (Requirement 5).
        """
        client = LLMClient(
            api_key="sk-bogus-invalid-key-99999",
            provider="openrouter",
            max_retries=3
        )

        # Mock OpenAI chat completions to raise AuthenticationError (HTTP 401)
        mock_openai_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 401
        auth_err = AuthenticationError("Invalid API key provided", response=mock_resp, body=None)
        mock_openai_client.chat.completions.create.side_effect = auth_err
        client.client = mock_openai_client

        with self.assertRaises(TerminalLLMError) as ctx:
            client.create_completion([{"role": "user", "content": "Hello"}])

        self.assertEqual(ctx.exception.status_code, 401)
        # CRITICAL: Verify exactly 1 call was made (0 retries!)
        self.assertEqual(client.call_count, 1)


# ==============================================================================
# 3. Budget Exhaustion & Partial Reporting Test Suite
# ==============================================================================

class TestBudgetExhaustionAndPartialReporting(unittest.TestCase):
    """
    Exercises agent state machine step budgeting and verifies partial report generation.
    """

    def test_step_budget_exhaustion_halts_gracefully(self):
        """
        Configures agent with max_steps=2.
        Verifies agent halts when step budget is reached with status='partial'
        and reason='step_budget_exhausted'.
        """
        mock_cfg = config.model_copy(update={"limits": LimitsConfig(max_steps=2, max_fetches=5, token_budget=100000)})

        agent = ResearchAgent(config=mock_cfg)

        # Mock LLM to continuously propose search_web calls
        tool_call_mock = MagicMock()
        tool_call_mock.id = "call_step"
        tool_call_mock.function.name = "search_web"
        tool_call_mock.function.arguments = '{"query": "entry level machine learning jobs"}'

        mock_msg = MagicMock()
        mock_msg.role = "assistant"
        mock_msg.content = "Searching web..."
        mock_msg.tool_calls = [tool_call_mock]

        mock_choice = MagicMock()
        mock_choice.message = mock_msg

        mock_completion = MagicMock()
        mock_completion.choices = [mock_choice]
        mock_completion.usage = MagicMock(prompt_tokens=50, completion_tokens=30, total_tokens=80)

        agent.llm.client = MagicMock()
        agent.llm.client.chat.completions.create.return_value = mock_completion

        # Mock search tool execution so it returns candidate roles
        from tracker.tools.search import SearchResultList
        with patch("tracker.agent.search_web") as mock_search:
            mock_search.return_value = SearchResultList([
                {"title": "MLE New Grad", "company": "Tech Corp", "url": "https://tech.com/jobs/1", "snippet": "ML"}
            ])
            result = agent.run(max_steps=2)

        # Assert agent halted due to budget
        self.assertEqual(result["status"], "partial")
        self.assertIn("step budget reached", result["halt_reason"].lower())
        self.assertEqual(result["step_count"], 2)

        # Verify partial report synthesis
        report_md = generate_run1_report(
            jobs=[],
            trace=result["trace"],
            metadata={
                "status": result["status"],
                "halt_reason": result["halt_reason"],
                "step_count": result["step_count"],
                "fetch_count": result["fetch_count"],
                "tokens_spent": result["tokens_spent"]
            }
        )
        self.assertIn("PARTIAL", report_md.upper())
        self.assertIn("budget constraint", report_md.lower())


# ==============================================================================
# 4. Two-Run Recrawl Differentiation Test Suite
# ==============================================================================

class TestTwoRunRecrawlDifferentiation(unittest.TestCase):
    """
    Exercises multi-run memory persistence, URL caching, and three-way classification.
    """

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.state_file = Path(self.temp_dir.name) / "test_tracker_state.json"
        self.memory = RecrawlMemoryManager(state_file_path=self.state_file)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_two_run_recrawl_workflow(self):
        """
        Simulates Run 1 followed by Run 2.
        Verifies:
        1. Run 1 persists state and visited URLs.
        2. Run 2 loads cached URLs.
        3. Multi-run classification produces [NEW], [STILL IN TOP 10], and [DROPPED].
        4. Run 2 report contains all three distinct sections.
        """
        # --- [RUN 1: Initial Crawl] ---
        run1_jobs = [
            {
                "title": "Machine Learning Engineer - Early Career",
                "company": "DeepMind",
                "url": "https://deepmind.google/jobs/mle-1",
                "location": "New York, NY",
                "snippet": "PyTorch and Transformers",
                "compensation": "$160k"
            },
            {
                "title": "AI Systems Engineer (New Grad)",
                "company": "Anthropic",
                "url": "https://anthropic.com/jobs/sys-1",
                "location": "San Francisco, CA",
                "snippet": "CUDA and inference clusters",
                "compensation": "$175k"
            }
        ]
        run1_urls = {"https://deepmind.google/jobs/mle-1", "https://anthropic.com/jobs/sys-1"}

        self.memory.save_state(
            run_number=1,
            visited_urls=run1_urls,
            top_k_jobs=run1_jobs,
            metadata={"status": "complete", "step_count": 5, "fetch_count": 4, "tokens_spent": 12000}
        )
        self.assertTrue(self.state_file.exists())

        # --- [RUN 2: Differential Recrawl] ---
        # Agent loads previous state
        known_urls = self.memory.get_known_urls()
        self.assertEqual(len(known_urls), 2)
        self.assertIn("https://deepmind.google/jobs/mle-1", known_urls)

        # In Run 2:
        # DeepMind is retained [STILL IN TOP 10]
        # Scale AI is discovered [NEW]
        # Anthropic was dropped [DROPPED]
        run2_current_top_k = [
            {
                "title": "Machine Learning Engineer - Early Career",
                "company": "DeepMind",
                "url": "https://deepmind.google/jobs/mle-1",
                "location": "New York, NY",
                "snippet": "PyTorch and Transformers",
                "compensation": "$160k"
            },
            {
                "title": "Research Engineer (University Grad)",
                "company": "Scale AI",
                "url": "https://scale.com/jobs/res-1",
                "location": "San Francisco, CA",
                "snippet": "Evaluation harness and synthetic data",
                "compensation": "$165k"
            }
        ]

        prior_top_k = self.memory.get_previous_top_k()
        classified = self.memory.classify_multi_run_developments(
            previous_top_k=prior_top_k,
            current_top_k=run2_current_top_k
        )

        # Assert Three-way Classification
        self.assertEqual(len(classified["new_since_last_run"]), 1)
        self.assertEqual(classified["new_since_last_run"][0]["company"], "Scale AI")
        self.assertEqual(classified["new_since_last_run"][0]["status"], "New since last run")

        self.assertEqual(len(classified["still_in_top_k"]), 1)
        self.assertEqual(classified["still_in_top_k"][0]["company"], "DeepMind")
        self.assertEqual(classified["still_in_top_k"][0]["status"], "Still in top K")

        self.assertEqual(len(classified["dropped"]), 1)
        self.assertEqual(classified["dropped"][0]["company"], "Anthropic")
        self.assertEqual(classified["dropped"][0]["status"], "Dropped")

        # Verify Run 2 Report Generation
        report2_md = generate_run2_report(
            classified=classified,
            trace=[],
            metadata={"status": "complete", "step_count": 4, "fetch_count": 2, "tokens_spent": 9500}
        )

        self.assertIn("New Since Last Run", report2_md)
        self.assertIn("Still in Top 10", report2_md)
        self.assertIn("Dropped Positions", report2_md)
        self.assertIn("Scale AI", report2_md)
        self.assertIn("DeepMind", report2_md)
        self.assertIn("Anthropic", report2_md)


# ==============================================================================
# Standalone Runner Function
# ==============================================================================

def run_all_verification_tests() -> bool:
    """Executes all 4 exercise test suites and formats console output."""
    print("\n" + "=" * 70)
    print("  CSCI-GA.2630 A1B: AGENTIC TRACKER AUTOMATED VERIFICATION SUITE")
    print("=" * 70)

    suites = [
        ("Pillar 1: SSRF Guardrail Attacks", TestSSRFGuardrailAttacks),
        ("Pillar 2: Bogus API Key Terminal Handling", TestBogusAPIKeyTerminalHandling),
        ("Pillar 3: Budget Exhaustion & Partial Reporting", TestBudgetExhaustionAndPartialReporting),
        ("Pillar 4: Two-Run Recrawl Differentiation", TestTwoRunRecrawlDifferentiation),
    ]

    total_tests = 0
    total_failures = 0
    total_errors = 0

    for title, suite_cls in suites:
        print(f"\n[Running] {title}...")
        suite = unittest.defaultTestLoader.loadTestsFromTestCase(suite_cls)
        runner = unittest.TextTestRunner(verbosity=1, stream=sys.stdout)
        res = runner.run(suite)
        total_tests += res.testsRun
        total_failures += len(res.failures)
        total_errors += len(res.errors)

    print("\n" + "=" * 70)
    print(f"  VERIFICATION RESULTS: {total_tests} Tests Executed")
    if total_failures == 0 and total_errors == 0:
        print("  STATUS: ALL PILLARS VERIFIED SUCCESSFULLY [PASS] ✓")
        print("=" * 70 + "\n")
        return True
    else:
        print(f"  STATUS: FAILED ({total_failures} failures, {total_errors} errors) [FAIL] ✗")
        print("=" * 70 + "\n")
        return False


if __name__ == "__main__":
    success = run_all_verification_tests()
    sys.exit(0 if success else 1)
