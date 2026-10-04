"""
Unit Tests for LLM Client Wrapper and Failure Classifier.
CSCI-GA.2630 Assignment 1B: Agentic Foundations
"""

import unittest
from unittest.mock import MagicMock, patch

from openai import (
    AuthenticationError,
    RateLimitError,
    InternalServerError,
)
import httpx

from tracker.llm import (
    LLMClient,
    TerminalLLMError,
    TransientLLMError,
    classify_error,
)


class TestLLMClient(unittest.TestCase):
    """
    Test suite for LLMClient failure classification, exponential backoff, and token tracking.
    """

    def _make_http_response(self, status_code: int, content: bytes) -> httpx.Response:
        request = httpx.Request("POST", "https://api.test.com/v1/chat/completions")
        return httpx.Response(status_code=status_code, content=content, request=request)

    def test_classify_error_terminal_status_codes(self):
        """
        Verify that 401, 402, 403, and quota errors are classified as terminal.
        """
        # 1. 401 Authentication Error
        resp_401 = self._make_http_response(401, b'{"error": {"message": "Invalid API key"}}')
        err_401 = AuthenticationError("Invalid API key", response=resp_401, body=None)
        is_term, reason, code = classify_error(err_401)
        self.assertTrue(is_term)
        self.assertEqual(code, 401)

        # 2. 429 with Quota Exhaustion
        resp_quota = self._make_http_response(429, b'{"error": {"message": "You exceeded your current quota"}}')
        err_quota = RateLimitError("You exceeded your current quota", response=resp_quota, body=None)
        is_term, reason, code = classify_error(err_quota)
        self.assertTrue(is_term)
        self.assertIn("quota", reason.lower())

    def test_classify_error_transient_rate_limit(self):
        """
        Verify standard 429 (RPM throttle) is classified as transient.
        """
        resp_429 = self._make_http_response(429, b'{"error": {"message": "Rate limit reached for requests per minute"}}')
        err_429 = RateLimitError("Rate limit reached for requests per minute", response=resp_429, body=None)
        is_term, reason, code = classify_error(err_429)
        self.assertFalse(is_term)
        self.assertEqual(code, 429)

    def test_terminal_authentication_failure_zero_retries(self):
        """
        Requirement 5 Verification:
        When upstream returns HTTP 401, client MUST fail fast immediately with ZERO retries.
        """
        client = LLMClient(api_key="bogus_test_key", max_retries=3, base_delay=0.01)

        resp_401 = self._make_http_response(401, b'{"error": {"message": "Unauthorized key"}}')
        mock_auth_err = AuthenticationError("Unauthorized key", response=resp_401, body=None)

        mock_create = MagicMock(side_effect=mock_auth_err)
        client.client.chat.completions.create = mock_create

        with self.assertRaises(TerminalLLMError) as ctx:
            client.create_completion([{"role": "user", "content": "hi"}])

        self.assertIn("[TERMINAL FAILURE]", str(ctx.exception))
        self.assertEqual(ctx.exception.status_code, 401)
        # CRITICAL ASSERTION: exactly 1 call was made (0 retries!)
        self.assertEqual(mock_create.call_count, 1)

    def test_terminal_quota_exhaustion_zero_retries(self):
        """
        Requirement 5 Verification:
        When upstream returns quota exhaustion, client MUST halt immediately with ZERO retries.
        """
        client = LLMClient(api_key="valid_key", max_retries=3, base_delay=0.01)

        resp_quota = self._make_http_response(429, b'{"error": {"message": "Account balance is too low"}}')
        mock_quota_err = RateLimitError("Account balance is too low", response=resp_quota, body=None)

        mock_create = MagicMock(side_effect=mock_quota_err)
        client.client.chat.completions.create = mock_create

        with self.assertRaises(TerminalLLMError) as ctx:
            client.create_completion([{"role": "user", "content": "hi"}])

        self.assertIn("[TERMINAL FAILURE]", str(ctx.exception))
        # Zero retries: must stop after first attempt
        self.assertEqual(mock_create.call_count, 1)

    def test_transient_rate_limit_backoff_and_recovery(self):
        """
        Verify transient 429 is retried with backoff and succeeds on subsequent attempt.
        """
        client = LLMClient(api_key="valid_key", max_retries=3, base_delay=0.01)

        resp_429 = self._make_http_response(429, b'{"error": {"message": "Rate limit exceeded, please retry"}}')
        mock_transient_err = RateLimitError("Rate limit exceeded, please retry", response=resp_429, body=None)

        # Mock successful response
        mock_success_response = MagicMock()
        mock_success_response.choices = [MagicMock()]
        mock_success_response.choices[0].message.content = "Success after retry"
        mock_success_response.usage.prompt_tokens = 20
        mock_success_response.usage.completion_tokens = 10
        mock_success_response.usage.total_tokens = 30

        # Fails once with transient 429, succeeds on attempt 2
        mock_create = MagicMock(side_effect=[mock_transient_err, mock_success_response])
        client.client.chat.completions.create = mock_create

        with patch("time.sleep") as mock_sleep:
            res = client.create_completion([{"role": "user", "content": "test"}])

        self.assertEqual(res.choices[0].message.content, "Success after retry")
        self.assertEqual(mock_create.call_count, 2)
        self.assertEqual(mock_sleep.call_count, 1)
        self.assertEqual(client.cumulative_total_tokens, 30)

    def test_transient_exhaustion_raises_transient_error(self):
        """
        Verify that exceeding max_retries on transient errors raises TransientLLMError.
        """
        client = LLMClient(api_key="valid_key", max_retries=2, base_delay=0.01, enable_fallback=False)

        resp_503 = self._make_http_response(503, b'{"error": {"message": "Service unavailable"}}')
        mock_server_err = InternalServerError("Service unavailable", response=resp_503, body=None)

        mock_create = MagicMock(side_effect=mock_server_err)
        client.client.chat.completions.create = mock_create

        with patch("time.sleep"):
            with self.assertRaises(TransientLLMError):
                client.create_completion([{"role": "user", "content": "hi"}])

        # Initial call + 2 retries = 3 calls total
        self.assertEqual(mock_create.call_count, 3)

    def test_live_chat_completion_with_active_key(self):
        """
        Live verification of LLM client using configured credentials.
        """
        client = LLMClient(max_retries=2, base_delay=0.1)
        res = client.create_completion(
            messages=[{"role": "user", "content": "Return the single word: VERIFIED"}],
            max_tokens=20
        )
        self.assertIsNotNone(res)
        msg = res.choices[0].message
        content_or_reasoning = (msg.content or "") + (getattr(msg, "reasoning", "") or "")
        self.assertTrue(len(content_or_reasoning) > 0, "Model should return non-empty response")
        self.assertGreater(client.cumulative_total_tokens, 0, "Tokens should be tracked")


if __name__ == "__main__":
    unittest.main()
