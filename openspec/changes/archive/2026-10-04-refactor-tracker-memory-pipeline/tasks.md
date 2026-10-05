# Tasks

## 1. Memory Package Scaffolding & Semantic Memory

- [x] 1.1 Scaffold `tracker/memory/` package with `__init__.py` and migrate `JobDeduplicator` into `tracker/memory/dedup.py`, verifying existing `tests/test_memory_dedup.py` passes without regressions.
- [x] 1.2 Implement `SemanticMemory` in `tracker/memory/semantic.py` encapsulating ATS domain rules, seniority dual-filter (Senior excluded unless Entry exempt), and freshness decay scoring (with >30 day hard expiration), verifying with unit tests in `tests/test_semantic_memory.py`.

## 2. Working Memory & Episodic Memory

- [x] 2.1 Implement `EpisodicMemory` in `tracker/memory/episodic.py` managing cross-run state persistence in `reports/tracker_state.json`, URL registry, and multi-run diff classification with non-error cached status, verifying with `tests/test_episodic_memory.py`.
- [x] 2.2 Implement `WorkingMemory` in `tracker/memory/working.py` providing the in-memory scratchpad, candidate priority queue, verified roles buffer, and observation pruning to cap context under 2,500 tokens, verifying with `tests/test_working_memory.py`.

## 3. Retrieval Pipeline Refactoring

- [x] 3.1 Refactor `tracker/tools/search.py` to support seed-first candidate discovery from AI Dev Jobs, priority queue ranking via `SemanticMemory`, lazy Tavily rescue querying, and transparent fallback on seed API outages, verifying with `tests/test_search_tool.py`.
- [x] 3.2 Update tool dispatching in `tracker/agent.py` and `tracker/tools/fetch.py` to integrate with `WorkingMemory` and `EpisodicMemory`, verifying that direct ATS links are fetched without redundant search calls via `tests/test_fetch_tool.py`.

## 4. LLM Classifier & Runtime Loop Integration

- [x] 4.1 Refine `classify_error()` in `tracker/llm.py` to disentangle Groq 413 / TPM rate limits containing billing URLs from terminal account quota failures, verifying with mock error tests in `tests/test_llm_client.py`.
- [x] 4.2 Integrate `WorkingMemory` and `EpisodicMemory` into `ResearchAgent` (`tracker/agent.py`) and `tracker/run.py`, verifying that an end-to-end run completes with `status: complete` within budget via `python -m tracker.run --steps 12`.
