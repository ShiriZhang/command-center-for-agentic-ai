"""
LLM Client Wrapper supporting OpenRouter and Groq with Resilient Failure Classification.
CSCI-GA.2630 Assignment 1B: Agentic Foundations
"""

import json
import logging
import os
import random
import time
from typing import Any, Dict, List, Optional, Tuple, Union

from openai import (
    OpenAI,
    APIStatusError,
    AuthenticationError,
    PermissionDeniedError,
    RateLimitError,
    APITimeoutError,
    APIConnectionError,
    InternalServerError,
    NotFoundError,
)

from tracker.config import config

logger = logging.getLogger("tracker.llm")


# ==============================================================================
# 1. Custom Exception Hierarchy
# ==============================================================================

class LLMError(Exception):
    """Base exception for Tracker LLM interactions."""
    pass


class TerminalLLMError(LLMError):
    """
    Fatal, unrecoverable failure (e.g., HTTP 401 Bad Credentials, HTTP 402 Payment Required,
    HTTP 403 Forbidden, or Account Quota Exhaustion).
    Terminates immediately with zero retries as mandated by Course Requirement 5.
    """
    def __init__(
        self,
        message: str,
        status_code: Optional[int] = None,
        provider: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None
    ):
        super().__init__(message)
        self.status_code = status_code
        self.provider = provider
        self.details = details or {}


class TransientLLMError(LLMError):
    """
    Recoverable, temporary failure (e.g., HTTP 429 per-minute rate limit, 503 gateway unavailable).
    Subject to exponential backoff and jitter.
    """
    def __init__(
        self,
        message: str,
        status_code: Optional[int] = None,
        retry_after: Optional[float] = None
    ):
        super().__init__(message)
        self.status_code = status_code
        self.retry_after = retry_after


# ==============================================================================
# 2. Tool Definitions for OpenAI Function Calling
# ==============================================================================

TOOL_SEARCH_WEB = {
    "type": "function",
    "function": {
        "name": "search_web",
        "description": "Searches the web for recent entry-level and new grad AI/ML engineering roles using Tavily and verified candidate job boards.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Target search query, e.g. 'entry level machine learning engineer greenhouse 2026'"
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of search results to return (default: 5)"
                }
            },
            "required": ["query"]
        }
    }
}

TOOL_FETCH_ARTICLE = {
    "type": "function",
    "function": {
        "name": "fetch_article",
        "description": "Fetches and extracts clean text content from a job posting or career URL with SSRF guardrails and redirect inspection.",
        "parameters": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "Absolute HTTP or HTTPS URL to fetch"
                }
            },
            "required": ["url"]
        }
    }
}

TOOL_FINISH = {
    "type": "function",
    "function": {
        "name": "finish",
        "description": "Concludes the agentic research loop and outputs the synthesized report in Markdown.",
        "parameters": {
            "type": "object",
            "properties": {
                "report": {
                    "type": "string",
                    "description": "Complete synthesized markdown report containing Top 10 roles, source citations, and analysis"
                }
            },
            "required": ["report"]
        }
    }
}

TRACKER_TOOLS = [TOOL_SEARCH_WEB, TOOL_FETCH_ARTICLE, TOOL_FINISH]


# ==============================================================================
# 3. Failure Classification Logic
# ==============================================================================

def classify_error(err: Exception) -> Tuple[bool, str, Optional[int]]:
    """
    Classifies an upstream LLM exception into:
        (is_terminal: bool, reason: str, status_code: Optional[int])
        
    Terminal Criteria (Zero Retries):
    - HTTP 401: AuthenticationError (Invalid/Missing API Key)
    - HTTP 402: Payment Required / Insufficient Credits
    - HTTP 403: Forbidden / Permission Denied
    - HTTP 404: NotFoundError (Model removed or unavailable)
    - RateLimitError (429) containing account quota exhaustion keywords ('quota', 'credit', 'billing', 'insufficient_quota')
    
    Transient Criteria (Exponential Backoff):
    - RateLimitError (429 per-minute rate limit without account exhaustion)
    - APITimeoutError / APIConnectionError (TCP socket timeout / connection dropped)
    - InternalServerError (HTTP 500, 502, 503, 504)
    """
    status_code = getattr(err, "status_code", None)
    err_str = str(err).lower()

    # 1. Explicit Terminal Status Codes
    if isinstance(err, AuthenticationError) or status_code == 401:
        return True, "Invalid or unauthorized API key (HTTP 401)", 401

    if status_code == 402:
        return True, "Payment required or credit balance exhausted (HTTP 402)", 402

    if isinstance(err, PermissionDeniedError) or status_code == 403:
        return True, "Permission denied (HTTP 403)", 403

    if isinstance(err, NotFoundError) or status_code == 404:
        return True, f"Model or resource not found (HTTP 404): {err}", 404

    # 2. Check for Rate Limit & Payload Limit Throttles (TPM / RPM / HTTP 413)
    # Groq appends 'https://console.groq.com/settings/billing' to standard 413 and TPM limit notices.
    # These are transient rate or payload limit throttles, NOT fatal account credit depletion.
    is_tpm_or_rate_limit = any(
        term in err_str
        for term in [
            "tpm",
            "rpm",
            "tokens per minute",
            "requests per minute",
            "tokens per day",
            "rate_limit_exceeded",
            "rate limit reached",
            "rate limit exceeded",
            "try again in",
            "please try again",
        ]
    )

    if status_code == 413 or "413" in err_str or "request too large" in err_str or "request entity too large" in err_str:
        return False, f"Request payload too large (HTTP 413, retryable with pruned context): {err}", 413

    if is_tpm_or_rate_limit:
        return False, f"Rate limit exceeded (TPM/RPM throttle, retryable): {err}", status_code or 429

    # 3. Check for Genuine Account Quota Exhaustion masquerading as 429
    # Only treat as fatal if it represents true credit depletion, not a console upgrade URL in a rate limit message
    genuine_quota_keywords = [
        "insufficient_quota",
        "insufficient funds",
        "exceeded your current quota",
        "balance is too low",
        "credit balance is too low",
        "account deactivated",
        "quota exceeded",
    ]
    if any(kw in err_str for kw in genuine_quota_keywords):
        return True, f"Account quota or credit limit exhausted: {err}", status_code or 429

    # Generic check for quota or billing only when not part of a console billing URL
    if ("quota" in err_str or "billing" in err_str) and "console.groq.com" not in err_str and "settings/billing" not in err_str:
        return True, f"Account quota or billing error: {err}", status_code or 429

    # 4. Standard 429 Rate Limit (Transient per-minute throttle)
    if isinstance(err, RateLimitError) or status_code == 429:
        return False, "Rate limit exceeded (HTTP 429), retryable", 429

    # 5. Network and Gateway Transient Errors
    if isinstance(err, (APITimeoutError, APIConnectionError)):
        return False, f"Network connection / timeout error ({type(err).__name__})", status_code

    if isinstance(err, InternalServerError) or (status_code and 500 <= status_code < 600):
        return False, f"Upstream server error (HTTP {status_code})", status_code

    # Generic unclassified status error
    if isinstance(err, APIStatusError):
        if status_code and status_code < 500:
            return True, f"Client API error (HTTP {status_code}): {err}", status_code
        return False, f"Server API error (HTTP {status_code}): {err}", status_code

    # Fallback: treat unexpected Python exceptions as terminal
    return True, f"Unexpected error: {err}", status_code


# ==============================================================================
# 4. Unified LLM Client
# ==============================================================================

class LLMClient:
    """
    Robust OpenAI-compatible LLM client wrapper supporting OpenRouter and Groq
    with token tracking, failure classification, and exponential backoff.
    """

    def __init__(
        self,
        provider: Optional[str] = None,
        model_name: Optional[str] = None,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        temperature: Optional[float] = None,
        max_retries: int = 3,
        base_delay: float = 1.0,
        enable_fallback: bool = True
    ):
        self.provider = provider or config.model.provider
        self.base_url = base_url or config.model.base_url
        self.model_name = model_name or config.model.name
        self.temperature = temperature if temperature is not None else config.model.temperature
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.enable_fallback = enable_fallback

        # Resolve credentials
        if api_key:
            self.api_key = api_key
        elif self.provider == "openrouter":
            self.api_key = config.openrouter_api_key or os.getenv("OPENROUTER_API_KEY", "")
        elif self.provider == "groq":
            self.api_key = config.groq_api_key or os.getenv("GROQ_API_KEY", "")
        else:
            self.api_key = os.getenv("LLM_API_KEY", "")

        # Cumulative token spend tracking
        self.cumulative_prompt_tokens: int = 0
        self.cumulative_completion_tokens: int = 0
        self.cumulative_total_tokens: int = 0
        self.call_count: int = 0

        # Primary OpenAI Client
        self._init_client()

    def _init_client(self) -> None:
        if not self.api_key:
            logger.warning(f"No API key provided for LLM provider '{self.provider}'.")
        self.client = OpenAI(
            base_url=self.base_url,
            api_key=self.api_key or "missing_key",
            timeout=30.0
        )

    def _get_fallback_client(self) -> Optional[Tuple[OpenAI, str]]:
        """Initializes fallback client (e.g. Groq when OpenRouter fails)."""
        fallback_cfg = config.model.fallback
        if not fallback_cfg:
            return None

        fb_key = config.groq_api_key or os.getenv("GROQ_API_KEY", "")
        if not fb_key:
            return None

        fb_client = OpenAI(
            base_url=fallback_cfg.base_url,
            api_key=fb_key,
            timeout=30.0
        )
        return fb_client, fallback_cfg.name

    def create_completion(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Union[str, Dict[str, Any]] = "auto",
        temperature: Optional[float] = None,
        max_tokens: int = 2048,
    ) -> Any:
        """
        Executes a Chat Completion request with exponential backoff on transient errors
        and immediate fail-fast termination on terminal errors.
        """
        if not self.api_key or self.api_key == "missing_key":
            raise TerminalLLMError(
                f"[TERMINAL FAILURE] Missing API key for provider '{self.provider}'. "
                "Configure it in your root .env file.",
                status_code=401,
                provider=self.provider
            )

        temp = temperature if temperature is not None else self.temperature
        kwargs: Dict[str, Any] = {
            "model": self.model_name,
            "messages": messages,
            "temperature": temp,
            "max_tokens": max_tokens,
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = tool_choice

        attempt = 0
        while attempt <= self.max_retries:
            try:
                self.call_count += 1
                response = self.client.chat.completions.create(**kwargs)

                # Record token spend
                if response.usage:
                    p_tok = response.usage.prompt_tokens or 0
                    c_tok = response.usage.completion_tokens or 0
                    t_tok = response.usage.total_tokens or (p_tok + c_tok)
                    self.cumulative_prompt_tokens += p_tok
                    self.cumulative_completion_tokens += c_tok
                    self.cumulative_total_tokens += t_tok

                return response

            except Exception as exc:
                is_terminal, reason, status_code = classify_error(exc)

                # Requirement 5: Terminal failures halt immediately with ZERO retries
                if is_terminal:
                    logger.error(f"[TERMINAL LLM FAILURE] Provider '{self.provider}' halted: {reason}")
                    raise TerminalLLMError(
                        f"[TERMINAL FAILURE] {reason}",
                        status_code=status_code,
                        provider=self.provider,
                        details={"original_error": str(exc)}
                    ) from exc

                # Transient failure: check retry budget
                attempt += 1
                if attempt > self.max_retries:
                    # Attempt failover to secondary provider if configured
                    if self.enable_fallback:
                        fallback_data = self._get_fallback_client()
                        if fallback_data:
                            fb_client, fb_model = fallback_data
                            logger.warning(
                                f"Exhausted {self.max_retries} retries on '{self.provider}'. "
                                f"Failing over to fallback provider with model '{fb_model}'..."
                            )
                            kwargs["model"] = fb_model
                            try:
                                return fb_client.chat.completions.create(**kwargs)
                            except Exception as fb_exc:
                                logger.error(f"Fallback provider also failed: {fb_exc}")

                    raise TransientLLMError(
                        f"Transient error exceeded maximum retries ({self.max_retries}): {exc}",
                        status_code=status_code
                    ) from exc

                # Exponential backoff with random jitter
                backoff = min(20.0, self.base_delay * (2 ** (attempt - 1)) + random.uniform(0.1, 0.5))
                logger.warning(
                    f"Transient failure on '{self.provider}' ({reason}). "
                    f"Backing off for {backoff:.2f}s (Attempt {attempt}/{self.max_retries})..."
                )
                time.sleep(backoff)


# Default module client instance
default_client = LLMClient()
