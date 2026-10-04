"""
Native Handwritten Agent Runtime State Machine.
Implements the autonomous research loop: search -> fetch -> observe -> decide -> synthesize
without external agent frameworks (LangChain, CrewAI, AutoGen).

CSCI-GA.2630 Assignment 1B: Agentic Foundations
"""

from datetime import datetime, timezone
import json
import logging
import os
import sys
import time
from typing import Any, Dict, List, Optional, Set, Tuple

from tracker.config import TrackerConfig, config as default_config
from tracker.llm import (
    LLMClient,
    TerminalLLMError,
    TransientLLMError,
    TRACKER_TOOLS,
    default_client
)
from tracker.tools.fetch import fetch_article
from tracker.tools.search import search_web
from tracker.tools.finish import finish

logger = logging.getLogger("tracker.agent")


class AgentState:
    """Agent state machine phases."""
    INITIALIZING = "INITIALIZING"
    DECIDING = "DECIDING"
    EXECUTING_TOOL = "EXECUTING_TOOL"
    OBSERVING = "OBSERVING"
    SYNTHESIZING_PARTIAL = "SYNTHESIZING_PARTIAL"
    FINISHED = "FINISHED"


class ResearchAgent:
    """
    Autonomous research agent for discovering and ranking Top 10 newest entry-level / new grad AI/ML roles.
    Enforces strict step, fetch, token, and timeout budgets natively.
    """

    def __init__(
        self,
        config: Optional[TrackerConfig] = None,
        llm_client: Optional[LLMClient] = None
    ):
        self.config = config or default_config
        self.llm = llm_client or default_client

        # Budgets
        self.max_steps = self.config.limits.max_steps
        self.max_fetches = self.config.limits.max_fetches
        self.token_budget = self.config.limits.token_budget
        self.timeout_seconds = self.config.limits.timeout_seconds

        # Runtime counters
        self.step_count: int = 0
        self.fetch_count: int = 0
        self.start_time: float = 0.0

        # Memory and trace
        self.visited_urls: Set[str] = set()
        self.fetched_articles: List[Dict[str, Any]] = []
        self.search_history: List[Dict[str, Any]] = []
        self.extracted_jobs: List[Dict[str, Any]] = []
        self.trace: List[Dict[str, Any]] = []
        self.messages: List[Dict[str, Any]] = []

        # Terminal state
        self.status: str = "running"
        self.halt_reason: Optional[str] = None
        self.final_report: str = ""

    def _build_system_prompt(self, previous_urls: Optional[Set[str]] = None) -> str:
        cached_clause = ""
        if previous_urls:
            cached_sample = list(previous_urls)[:8]
            cached_clause = (
                f"\nNOTE - RECRAWL MEMORY: You have already inspected {len(previous_urls)} URLs in prior runs "
                f"(e.g. {cached_sample}). DO NOT re-fetch these URLs unless seeking updated status. "
                "Discover new opportunities and compare them against previous findings.\n"
            )

        return (
            f"You are an autonomous Research Analyst Agent tracking: {self.config.topic}.\n"
            f"Target Goal: Identify and rank the Top {self.config.K} newest entry-level and new grad AI/ML roles.\n\n"
            f"POLICY INSTRUCTIONS:\n{self.config.instructions}\n"
            f"{cached_clause}\n"
            "STRICT PROVENANCE & ANTI-HALLUCINATION RULES:\n"
            "1. Every role MUST have an authentic corporate ATS or application URL verified via search or fetch.\n"
            "2. Never fabricate titles, salaries, qualifications, or company details.\n"
            "3. Use `search_web` to discover opportunities, then `fetch_article` to inspect actual qualifications and details.\n"
            "4. When you have collected and verified sufficient high-quality roles (or budget is low), call `finish(report)`.\n"
            "5. Structure the report in clean GitHub Flavored Markdown with job title, company, URL, location, and requirements."
        )

    def _log_trace(self, action: str, action_input: Any, observation: Any, thought: str = "") -> None:
        """Records an atomic research step in the auditable execution trace."""
        elapsed = round(time.time() - self.start_time, 2)
        record = {
            "step": self.step_count,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "elapsed_seconds": elapsed,
            "thought": thought,
            "action": action,
            "action_input": action_input,
            "observation": observation,
            "cumulative_tokens": self.llm.cumulative_total_tokens,
            "fetch_count": self.fetch_count
        }
        self.trace.append(record)

    def _check_budgets(self) -> Tuple[bool, Optional[str]]:
        """
        Enforces Rule 4 resource limits.
        Returns: (is_exhausted, reason)
        """
        if self.step_count >= self.max_steps:
            return True, f"Maximum step budget reached ({self.step_count}/{self.max_steps})"

        if self.fetch_count >= self.max_fetches:
            return True, f"Maximum fetch budget reached ({self.fetch_count}/{self.max_fetches})"

        if self.llm.cumulative_total_tokens >= self.token_budget:
            return True, f"Token spend budget reached ({self.llm.cumulative_total_tokens}/{self.token_budget})"

        elapsed = time.time() - self.start_time
        if elapsed >= self.timeout_seconds:
            return True, f"Overall execution timeout exceeded ({elapsed:.1f}s >= {self.timeout_seconds}s)"

        return False, None

    def _execute_tool_call(self, tool_name: str, args: Dict[str, Any]) -> Tuple[Any, bool]:
        """
        Executes a tool call requested by the LLM.
        Returns: (result_data, is_finish)
        """
        if tool_name == "search_web":
            query = args.get("query", "")
            limit = args.get("max_results", 5)
            search_res = search_web(query, max_results=limit)
            self.search_history.append({"query": query, "count": len(search_res)})
            # Record candidates for provenance
            for item in search_res:
                self.extracted_jobs.append(item)
            return search_res.to_dict(), False

        elif tool_name == "fetch_article":
            url = args.get("url", "")
            if self.fetch_count >= self.max_fetches:
                return {
                    "status": "rejected",
                    "error": f"Fetch budget exhausted ({self.fetch_count}/{self.max_fetches}). Cannot fetch more URLs."
                }, False

            self.fetch_count += 1
            self.visited_urls.add(url)
            fetch_res = fetch_article(url)
            self.fetched_articles.append(fetch_res)
            return fetch_res, False

        elif tool_name == "finish":
            report_text = args.get("report", "")
            fin_res = finish(report_text)
            self.final_report = report_text
            self.status = "complete"
            return fin_res, True

        else:
            return {"error": f"Unknown tool '{tool_name}'"}, False

    def _synthesize_partial_report(self, reason: str) -> str:
        """
        Synthesizes a best-effort partial report when budgets are exhausted.
        """
        lines = [
            f"# {self.config.topic}",
            "",
            f"> [!WARNING]",
            f"> **Report Status: PARTIAL** — Autonomous research halted due to budget constraint: {reason}.",
            f"> Executed **{self.step_count}** steps, **{self.fetch_count}** article fetches, consuming **{self.llm.cumulative_total_tokens}** tokens.",
            "",
            "## Discovered & Verified Opportunities (Best Effort)",
            ""
        ]

        # Aggregate unique roles from extracted jobs and fetched articles
        seen_urls = set()
        ranked_roles = []

        for art in self.fetched_articles:
            if art.get("status") == "fetched" and art.get("url") not in seen_urls:
                seen_urls.add(art["url"])
                ranked_roles.append({
                    "title": art.get("title") or "Verified Opening",
                    "url": art["url"],
                    "snippet": art.get("content", "")[:300] + "..." if art.get("content") else "Fetched directly from source."
                })

        for job in self.extracted_jobs:
            u = job.get("url", "")
            if u and u not in seen_urls:
                seen_urls.add(u)
                ranked_roles.append({
                    "title": job.get("title") or "Candidate Opening",
                    "url": u,
                    "snippet": job.get("snippet", "")
                })

        if not ranked_roles:
            lines.append("No roles could be verified before budget exhaustion.")
        else:
            for idx, r in enumerate(ranked_roles[:self.config.K], 1):
                lines.append(f"### {idx}. {r['title']}")
                lines.append(f"- **Source URL**: [{r['url']}]({r['url']})")
                lines.append(f"- **Summary**: {r['snippet']}")
                lines.append("")

        lines.extend([
            "---",
            "## Data Provenance & Audit Log",
            f"- Total URLs Checked: {len(self.visited_urls)}",
            f"- Total Search Queries: {len(self.search_history)}",
            f"- Generated at: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}"
        ])

        return "\n".join(lines)

    def run(
        self,
        max_steps: Optional[int] = None,
        previous_urls: Optional[Set[str]] = None
    ) -> Dict[str, Any]:
        """
        Executes the autonomous handwritten agent loop until finish() is called
        or a budget is exhausted.
        
        Returns:
            Dict containing status, halt_reason, step_count, fetch_count, tokens, report, trace.
        """
        self.start_time = time.time()
        effective_max_steps = max_steps or self.max_steps
        self.step_count = 0
        self.fetch_count = 0
        self.status = "running"
        self.halt_reason = None
        self.final_report = ""

        # Initialize conversation state
        sys_prompt = self._build_system_prompt(previous_urls)
        self.messages = [
            {"role": "system", "content": sys_prompt},
            {
                "role": "user",
                "content": f"Begin research on '{self.config.topic}'. Discover, inspect, and rank the top {self.config.K} newest opportunities. Enforce strict provenance."
            }
        ]

        logger.info(f"Starting ResearchAgent loop (max_steps={effective_max_steps}, max_fetches={self.max_fetches})")

        while self.step_count < effective_max_steps:
            self.step_count += 1

            # 1. Budget Enforcement Check before model invocation
            exhausted, reason = self._check_budgets()
            if exhausted:
                logger.warning(f"Budget reached: {reason}. Triggering partial report synthesis.")
                self.status = "partial"
                self.halt_reason = reason
                self.final_report = self._synthesize_partial_report(reason)
                self._log_trace("halt_budget_exhausted", {"reason": reason}, "Synthesized partial report")
                break

            # 2. DECIDE: Query LLM for next action
            try:
                response = self.llm.create_completion(
                    messages=self.messages,
                    tools=TRACKER_TOOLS,
                    tool_choice="auto"
                )
            except TerminalLLMError as term_err:
                logger.error(f"Terminal LLM failure during agent step {self.step_count}: {term_err}")
                self.status = "error"
                self.halt_reason = str(term_err)
                self.final_report = self._synthesize_partial_report(f"Terminal error: {term_err}")
                self._log_trace("terminal_error", {"error": str(term_err)}, "Agent terminated")
                break
            except Exception as e:
                logger.error(f"Unrecoverable LLM call error: {e}")
                self.status = "error"
                self.halt_reason = str(e)
                self.final_report = self._synthesize_partial_report(f"LLM exception: {e}")
                break

            msg = response.choices[0].message
            content = msg.content or ""
            tool_calls = getattr(msg, "tool_calls", None)

            # Record assistant turn in conversation
            assistant_turn: Dict[str, Any] = {
                "role": "assistant",
                "content": content
            }
            if tool_calls:
                assistant_turn["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": tc.type,
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments
                        }
                    }
                    for tc in tool_calls
                ]
            self.messages.append(assistant_turn)

            # 3. If no tool calls made, model provided a text observation or conclusion
            if not tool_calls:
                thought = content.strip()
                self._log_trace("reasoning", {}, thought, thought=thought)

                # If model produced a comprehensive markdown report in content
                if "# " in content and "http" in content:
                    logger.info("Model concluded research with inline report.")
                    self.final_report = content
                    self.status = "complete"
                    break

                # Prompt model to proceed with tool execution
                self.messages.append({
                    "role": "user",
                    "content": "Please continue by calling `search_web`, `fetch_article`, or `finish(report)`."
                })
                continue

            # 4. EXECUTING_TOOL & OBSERVING
            should_terminate = False
            for tc in tool_calls:
                t_name = tc.function.name
                try:
                    t_args = json.loads(tc.function.arguments) if isinstance(tc.function.arguments, str) else tc.function.arguments
                except Exception:
                    t_args = {}

                logger.info(f"[Step {self.step_count}] Executing tool '{t_name}' with args {t_args}")
                obs_data, is_finish = self._execute_tool_call(t_name, t_args)

                # Format observation back into messages for LLM context
                obs_str = json.dumps(obs_data, ensure_ascii=False)
                # Truncate large tool outputs in LLM conversation to conserve token budget
                if len(obs_str) > 4000:
                    obs_str = obs_str[:4000] + "... [truncated to conserve token budget]"

                self.messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": obs_str
                })

                self._log_trace(
                    action=t_name,
                    action_input=t_args,
                    observation=obs_data if len(str(obs_data)) < 500 else f"Output length: {len(str(obs_data))} chars",
                    thought=content
                )

                if is_finish:
                    logger.info("Agent called finish() tool. Research complete.")
                    should_terminate = True
                    break

            if should_terminate:
                break

        # Fallback if step budget was exhausted at the loop boundary
        if self.step_count >= effective_max_steps and not self.final_report:
            reason = f"Step budget exhausted ({self.step_count}/{effective_max_steps})"
            self.status = "partial"
            self.halt_reason = reason
            self.final_report = self._synthesize_partial_report(reason)
            self._log_trace("halt_budget_exhausted", {"reason": reason}, "Synthesized partial report")

        return {
            "status": self.status,
            "halt_reason": self.halt_reason,
            "step_count": self.step_count,
            "fetch_count": self.fetch_count,
            "tokens_spent": self.llm.cumulative_total_tokens,
            "report": self.final_report,
            "visited_urls": list(self.visited_urls),
            "trace": self.trace
        }


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Run Native Agentic Tracker")
    parser.add_argument("--steps", type=int, default=5, help="Step budget limit for test run")
    args = parser.parse_args()

    agent = ResearchAgent()
    out = agent.run(max_steps=args.steps)
    print(f"\nStatus: {out['status']}")
    print(f"Steps: {out['step_count']}, Fetches: {out['fetch_count']}, Tokens: {out['tokens_spent']}")
    print("\n--- REPORT PREVIEW ---")
    print(out["report"][:600] + ("..." if len(out["report"]) > 600 else ""))
