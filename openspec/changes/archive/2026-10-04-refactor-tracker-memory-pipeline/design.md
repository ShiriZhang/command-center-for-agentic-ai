# Technical Design: Modular Memory Architecture and Precision Discovery Pipeline

## Context

See `proposal.md` for background and motivation. Currently, the agent runtime in `tracker/agent.py` stores the entire interaction history linearly in `self.messages`, with raw tool observations often exceeding 10,000 characters per step. When cumulative tokens reach the 100k budget, or when single-request tokens exceed Groq's 8,000 TPM limit (returning HTTP 413 containing billing URLs, which `tracker/llm.py` misclassifies as fatal account quota exhaustion), the agent terminates with a `PARTIAL` report.

The monolithic `tracker/memory.py` tightly couples recrawl state with deduplication, lacking a clean abstraction for working scratchpad state and domain knowledge rules. Furthermore, `tracker/tools/search.py` performs a naive 50/50 round-robin interleaving between Tavily and AI Dev Jobs without evaluating posting freshness or filtering out senior roles upfront.

## Goals / Non-Goals

**Goals:**
- Decouple memory into a native `tracker/memory/` package with clear interfaces: `WorkingMemory`, `EpisodicMemory`, `SemanticMemory`, and `JobDeduplicator`.
- Implement observation pruning in `WorkingMemory` to guarantee per-request prompt context remains below 2,500 tokens throughout 15 steps.
- Implement an explicit Priority Queue for candidate roles driven by a multi-factor scoring rubric: freshness decay (up to +5, >30 days hard expiry), ATS direct channel bonus (+3), and seniority hard-filtering.
- Refactor the retrieval flow: seed directly from AI Dev Jobs, fetch direct ATS links immediately, invoke Tavily lazily for rescue/missing links, and fall back to broad keyword search on seed API outages.
- Fix the error classification logic in `tracker/llm.py` to prevent Groq 413 / TPM rate limits from triggering immediate terminal aborts.

**Non-Goals:**
- Introducing external agent frameworks or vector databases (Mem0, LangChain, Chroma, Pinecone) - explicitly prohibited by Assignment 1B Requirement 1.
- Altering the backend API schema or authentication rules (FastAPI and React command center remain untouched).
- Modifying the core CLI entry point signatures (`python -m tracker.run`, `python -m tracker.tools ...`).

## Decisions

### Decision 1: Native In-Memory Working Memory vs. External Frameworks (Mem0 / Vector Stores)
- **Choice**: Implement a native Python `WorkingMemory` class in `tracker/memory/working.py`.
- **Rationale**: Assignment 1B Requirement 1 states *"Validation, budgets, and state are what's being graded, and a framework hides all three."* Mem0 or vector databases introduce hidden background LLM calls, lack trace transparency (violating Requirement 13), add heavy dependencies that threaten clean clone evaluation, and require embedding models unavailable on free tiers like Groq. A pure Python state machine is completely transparent, zero-cost, and deterministic.
- **Alternatives Considered**:
  - *Mem0 Python SDK*: Rejected due to framework policy violation, hidden token usage, and lack of free embedding endpoints.
  - *FIFO Sliding Window*: Rejected because dropping early history discards previously discovered candidate URLs and verified roles.

### Decision 2: Multi-Factor Priority Queue vs. Mechanical Interleaving
- **Choice**: Structure `candidate_queue` in `WorkingMemory` as a priority queue ranked by `SemanticMemory.score_candidate()`.
- **Rationale**: Rather than taking 5 results blindly from Tavily and 5 from AI Dev Jobs, candidates are evaluated against three objective metrics:
  1. **Freshness Score**:
     - $\le 24\text{ hours} \implies +5$
     - $1\text{ to } 3\text{ days} \implies +4$
     - $3\text{ to } 7\text{ days} \implies +3$
     - $7\text{ to } 14\text{ days} \implies +2$
     - $14\text{ to } 30\text{ days} \implies +1$
     - $> 30\text{ days} \implies \text{Disqualified (filtered out)}$
  2. **Channel Authenticity**: $+3$ for direct corporate ATS links (`greenhouse.io`, `lever.co`, `ashbyhq.com`, `myworkdayjobs.com`).
  3. **Seniority Exclusion**: Roles matching senior tokens (`senior`, `sr.`, `lead`, `staff`, `principal`, `director`, `5+ years`) without entry exemptions (`entry`, `junior`, `new grad`, `early career`, `intern`) are immediately rejected.
- **Alternatives Considered**:
  - *Unranked FIFO Queue*: Discards time sensitivity and causes the agent to waste budget fetching stale roles from weeks ago.

### Decision 3: Seed-First Direct ATS Fetch with Lazy Tavily Rescue
- **Choice**: Prioritize AI Dev Jobs for initial candidate discovery. If a candidate has a valid ATS URL, fetch it directly. Invoke Tavily only when:
  1. The candidate role lacks a direct ATS application link.
  2. Direct fetching fails (404, blocked by guardrail, or anti-bot challenge).
  3. AI Dev Jobs API encounters a network outage (HTTP 5xx / timeout).
- **Rationale**: Direct fetching avoids wasting Tavily API credits (capped at 1,000 monthly credits) on jobs where the ATS portal is already known, while keeping Tavily available as a high-precision rescue tool and backup discovery engine.
- **Alternatives Considered**:
  - *Mandatory Dual Search for Every Role*: Excessive latency, doubles network round trips, and quickly burns Tavily credits.

### Decision 4: Disentangling Groq 413 / Billing Rate Limits in LLM Failure Classification
- **Choice**: Refine `classify_error()` in `tracker/llm.py` so that matching `billing` inside error text only classifies as terminal if the HTTP status code is 402 or the error explicitly indicates account credit depletion (e.g. `insufficient_funds`, `insufficient_quota`), while status code 413 or token-per-minute errors (`rate_limit_exceeded` with TPM references) are treated as transient or payload errors.
- **Rationale**: Groq appends `Upgrade to Dev Tier today at https://console.groq.com/settings/billing` to standard 413 request size and 8,000 TPM limit messages. Matching `"billing"` blindly causes false-positive terminal halts.

## Risks / Trade-offs

- **[Risk]**: AI Dev Jobs API changes response structure or experiences prolonged downtime.
  → **Mitigation**: Implement strict try/except blocks in `discover_aidevboard_candidates()`; on any exception or non-200 response, automatically log a fallback notice and invoke `search_tavily()` with targeted query templates (`entry level machine learning engineer greenhouse 2026`).
- **[Risk]**: Observation pruning removes critical qualification context required for final report synthesis.
  → **Mitigation**: In `WorkingMemory`, extract structured role summaries (Title, Company, Location, Compensation, Requirements snippet) into `verified_jobs` *before* collapsing raw observation strings in `messages`.
- **[Risk]**: Timezone drift between local system time and job post timestamps causes inaccurate freshness scoring.
  → **Mitigation**: Normalize all ISO 8601 timestamps to UTC before calculating $\Delta t$. If a job posting lacks a publication date, assign a baseline default score (+2) rather than disqualifying it.
