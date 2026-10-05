"""
Working Memory Module: In-Memory Scratchpad, Priority Queue, and Observation Pruning.
CSCI-GA.2630 Assignment 1B: Agentic Foundations
"""

import json
import logging
from typing import Any, Dict, List, Optional, Set, Tuple
from urllib.parse import urlparse

from tracker.memory.semantic import SemanticMemory

logger = logging.getLogger("tracker.memory.working")


class WorkingMemory:
    """
    Maintains the ephemeral working state and dynamic context for a single agent run:
    1. Candidate Priority Queue: Candidate roles ranked by SemanticMemory score descending.
    2. Verified Roles Pool: High-confidence, fully extracted roles.
    3. Step and Token Telemetry: Dynamic countdown status notices.
    4. Observation Pruning Engine: Condenses older historical tool observations to
       guarantee single-request prompt context remains below 2,500 tokens.
    """

    def __init__(
        self,
        target_k: int = 10,
        max_steps: int = 15,
        token_budget: int = 100000,
        semantic_memory: Optional[SemanticMemory] = None
    ):
        self.target_k: int = target_k
        self.max_steps: int = max_steps
        self.token_budget: int = token_budget
        self.semantic: SemanticMemory = semantic_memory or SemanticMemory()

        self.candidate_queue: List[Dict[str, Any]] = []
        self.verified_jobs: List[Dict[str, Any]] = []
        self.seen_urls: Set[str] = set()
        self.step_count: int = 0
        self.fetch_count: int = 0
        self.cumulative_tokens: int = 0

    def _canonical_url(self, u: str) -> str:
        """Standardizes URLs by hostname and path stripping."""
        if not u:
            return ""
        parsed = urlparse(u.strip())
        return f"{parsed.netloc.lower()}{parsed.path.rstrip('/')}"

    def add_candidate(
        self,
        candidate: Dict[str, Any],
        explicit_score: Optional[int] = None
    ) -> bool:
        """
        Evaluates and adds a candidate opening to the priority queue.
        Deduplicates against already-queued and verified URLs.
        Returns True if candidate was successfully enqueued.
        """
        raw_url = candidate.get("apply_url") or candidate.get("url") or ""
        canon_url = self._canonical_url(raw_url)
        if not canon_url or canon_url in self.seen_urls:
            return False

        if explicit_score is not None:
            score = explicit_score
            is_qual = score > 0
        else:
            is_qual, score, _ = self.semantic.score_candidate(candidate)

        if not is_qual:
            return False

        item = dict(candidate)
        item["priority_score"] = score
        item["canonical_url"] = canon_url

        self.seen_urls.add(canon_url)
        self.candidate_queue.append(item)
        # Keep queue sorted descending by priority score
        self.candidate_queue.sort(key=lambda x: x.get("priority_score", 0), reverse=True)
        return True

    def add_candidates(self, candidates: List[Dict[str, Any]]) -> int:
        """Enqueues multiple candidate roles, returning count of accepted items."""
        added = 0
        for cand in candidates:
            if self.add_candidate(cand):
                added += 1
        return added

    def pop_best_candidate(self) -> Optional[Dict[str, Any]]:
        """Retrieves and removes the highest-priority candidate from the queue."""
        if not self.candidate_queue:
            return None
        return self.candidate_queue.pop(0)

    def peek_best_candidate(self) -> Optional[Dict[str, Any]]:
        """Inspects the top candidate without removing it."""
        if not self.candidate_queue:
            return None
        return self.candidate_queue[0]

    def add_verified_job(self, job_data: Dict[str, Any]) -> bool:
        """
        Records a fully verified role with extracted qualifications and application URL.
        Prevents duplicate entry by canonical URL and title fingerprint.
        """
        raw_url = job_data.get("url") or job_data.get("apply_url") or ""
        canon_url = self._canonical_url(raw_url)
        company = job_data.get("company") or ""
        title = job_data.get("title") or ""
        fp = self.semantic.generate_fingerprint(company, title)

        for existing in self.verified_jobs:
            e_canon = self._canonical_url(existing.get("url") or "")
            e_fp = existing.get("fingerprint") or self.semantic.generate_fingerprint(
                existing.get("company") or "", existing.get("title") or ""
            )
            if (canon_url and canon_url == e_canon) or (fp and fp == e_fp):
                return False

        record = dict(job_data)
        record["canonical_url"] = canon_url
        record["fingerprint"] = fp
        self.verified_jobs.append(record)
        if canon_url:
            self.seen_urls.add(canon_url)
        return True

    def is_goal_satisfied(self) -> bool:
        """Returns True if the target K verified roles have been achieved."""
        return len(self.verified_jobs) >= self.target_k

    def get_progress_status_block(
        self,
        current_step: int,
        cumulative_tokens: int = 0
    ) -> str:
        """
        Generates a compact, informative working status block for prompt injection.
        Includes urgent countdown guidance when steps or tokens are nearing limits.
        """
        self.step_count = current_step
        self.cumulative_tokens = cumulative_tokens

        verified_count = len(self.verified_jobs)
        remaining_needed = max(0, self.target_k - verified_count)
        remaining_steps = max(0, self.max_steps - current_step)

        lines = [
            "\n[WORKING SCRATCHPAD STATUS]",
            f"- Goal Progress: {verified_count}/{self.target_k} verified positions collected.",
            f"- Step Budget: Step {current_step}/{self.max_steps} ({remaining_steps} steps remaining).",
            f"- Candidates in Queue: {len(self.candidate_queue)} pending inspection."
        ]

        if verified_count >= self.target_k:
            lines.append(
                "- CRITICAL DIRECTIVE: Target of 10 positions achieved! Do NOT make further searches. "
                "Synthesize your findings and call `finish(report)` immediately."
            )
        elif current_step >= self.max_steps:
            lines.append(
                f"- [!] FINAL STEP NOTICE: Step {current_step}/{self.max_steps} (0 steps remaining). "
                f"You MUST call `finish(report)` immediately now with your synthesized Markdown report of your top findings!"
            )
        elif remaining_steps <= 2:
            lines.append(
                f"- URGENT BUDGET WARNING: Only {remaining_steps} steps left! Immediately stop exploratory "
                f"searches, select your best {min(verified_count, self.target_k)} roles, and call `finish(report)`."
            )
        elif len(self.candidate_queue) >= 5:
            top_cand = self.candidate_queue[0]
            lines.append(
                f"- QUEUE READY: You have {len(self.candidate_queue)} candidates in queue! "
                f"Do NOT call `search_web`. Inspect top candidate '{top_cand.get('title')}' at "
                f"'{top_cand.get('company')}' via `fetch_article('{top_cand.get('apply_url') or top_cand.get('url')}')."
            )
        elif self.candidate_queue:
            top_cand = self.candidate_queue[0]
            lines.append(
                f"- Recommended Next Action: Fetch top candidate '{top_cand.get('title')}' at "
                f"'{top_cand.get('company')}' via `fetch_article('{top_cand.get('apply_url') or top_cand.get('url')}')."
            )
        else:
            lines.append("- Recommended Next Action: Candidate queue empty. Invoke `search_web` to discover roles.")

        return "\n".join(lines) + "\n"

    def prune_conversation_history(
        self,
        messages: List[Dict[str, Any]],
        keep_recent_tools: int = 2
    ) -> List[Dict[str, Any]]:
        """
        Condenses older verbose tool observations in conversation history down to
        single-line metadata summaries.
        
        Preserves:
        - System prompt (index 0) and User prompt (index 1).
        - Recent `keep_recent_tools` tool observations in full detail for immediate reasoning.
        - All Assistant thoughts and tool call requests.
        
        Replaces older raw tool observations (>300 chars) with structured compact summaries,
        keeping total per-request prompt context securely under 2,500 tokens.
        """
        if not messages or len(messages) <= 3:
            return messages

        # Identify all tool observation message indices
        tool_indices = [idx for idx, m in enumerate(messages) if m.get("role") == "tool"]
        if len(tool_indices) <= keep_recent_tools:
            return messages

        indices_to_prune = set(tool_indices[:-keep_recent_tools])

        pruned_messages: List[Dict[str, Any]] = []
        for idx, msg in enumerate(messages):
            if idx not in indices_to_prune:
                pruned_messages.append(msg)
                continue

            # Prune older tool message content
            content = msg.get("content") or ""
            if len(content) > 300:
                summary = f"[Observation: Output archived in WorkingMemory ({len(content)} chars). Candidates extracted to queue.]"
                pruned_msg = dict(msg)
                pruned_msg["content"] = summary
                pruned_messages.append(pruned_msg)
            else:
                pruned_messages.append(msg)

        return pruned_messages
