# Proposal: Refactor Agentic Tracker Memory & Retrieval Pipeline

## Why

Currently, the Agentic Tracker frequently aborts execution with `PARTIAL` degraded reports due to quadratic token spend inflation ($O(N^2)$), unmanaged conversation context accumulation, and premature termination from misclassifying Groq TPM 413 limits as fatal account quota exhaustion. Furthermore, the dual search pipeline blindly interleaves generic Tavily results with AI Dev Jobs without freshness-decay scoring or seniority hard-filtering, causing redundant exploratory loops.

Refactoring the monolithic memory system into a modular `tracker/memory/` package (Working, Episodic, and Semantic Memory) and restructuring the candidate discovery pipeline into a seed-first, priority-queued, lazy-rescue architecture will eliminate token explosions, guarantee predictable sub-2,500-token per-turn requests, and ensure the agent reliably reaches `complete` status while fully complying with Assignment 1B requirements.

## What Changes

- **Modular Memory Architecture (`tracker/memory/`)**:
  - Extract monolithic `tracker/memory.py` into a cohesive package: `working.py`, `episodic.py`, `semantic.py`, and `dedup.py`.
  - Introduce **Working Memory**: In-memory scratchpad tracking active candidate queues, verified role buffers, budget progress telemetry, and tool observation pruning (collapsing historical raw observations into 1-line metadata summaries to cap prompt size under 2,500 tokens).
  - Refine **Episodic Memory**: Manage cross-run persistence (`reports/tracker_state.json`), URL crawl history, and Top-K snapshot diffing (`New since last run`, `Still in top K`, `Dropped`), returning non-error status for cached valid roles.
  - Formalize **Semantic Memory**: Static domain ontology encapsulating ATS portal recognition (Greenhouse, Lever, Ashby, Workday), title slugification, company entity normalization, seniority dual-check filtering, and multi-factor priority scoring.
- **Precision Candidate Discovery & Verification Pipeline**:
  - Shift candidate generation to **AI Dev Jobs first**: Pre-seed high-confidence roles with direct corporate ATS links.
  - **Multi-Factor Priority Scoring**:
    - Freshness reward: $\le 24\text{h} \implies +5$, $\le 3\text{d} \implies +4$, $\le 7\text{d} \implies +3$, $\le 14\text{d} \implies +2$, $\le 30\text{d} \implies +1$. Postings older than 30 days are disqualified.
    - Channel reward: Corporate ATS direct links get $+3$.
    - Seniority hard-filter: Direct disqualification if Senior/Staff/Lead/5+ years keywords appear without Entry/Junior/New-Grad exemptions.
  - **Direct ATS Fetch First & Lazy Tavily Rescue**: If candidate has direct ATS URL, `fetch_article` directly without burning Tavily credits. Tavily is invoked solely when direct links are missing, fetch fails (404/blocked), or AI Dev Jobs API encounters downtime (automatic network fallback).
- **Resilient Failure Classification & Budget Accounting**:
  - Refine LLM failure classifier in `tracker/llm.py`: Disentangle Groq TPM rate limits (containing `billing` URLs in 413 error messages) from true HTTP 402 / terminal quota exhaustion.
  - Dynamic budget awareness: Inject countdown notices in working memory when steps or token limits approach exhaustion to trigger prompt completion.

## Capabilities

### New Capabilities
*(None - extends existing agentic tracker capability)*

### Modified Capabilities
- `agentic-tracker`: Update agent runtime requirements to incorporate structured working memory observation pruning, multi-factor freshness/seniority candidate ranking, lazy Tavily verification, and precise TPM rate limit classification.

## Impact

- **Core Tracker Modules**:
  - Replaces `tracker/memory.py` with `tracker/memory/` package (`working.py`, `episodic.py`, `semantic.py`, `dedup.py`, `__init__.py`).
  - Updates `tracker/agent.py` to use `WorkingMemory` context assembly and observation pruning.
  - Updates `tracker/tools/search.py` to support seed-first discovery with Tavily fallback.
  - Updates `tracker/llm.py` error classification logic to avoid false-positive terminal errors.
  - Updates `tracker/run.py` to orchestrate with the new memory architecture.
- **External Dependencies**: Zero new external dependencies (pure native Python standard library + existing httpx/beautifulsoup4/tavily-python).
- **APIs & Storage**: Backward-compatible with existing `reports/tracker_state.json` and backend `/api/tracker/*` endpoints.
