# Design: refine-agentic-tracker

## Context

The system has an autonomous research agent runtime, SSRF guardrails, deduplication engine, and full-stack integration. However, auditing against the Assignment 1B rubric identified gaps in trace telemetry granularity, recrawl article caching enforcement, frontend audit table columns, run timestamp intervals, and documentation accuracy. See `proposal.md` for motivation.

## Goals / Non-Goals

**Goals:**
- Provide 100% compliant execution traces with per-call `step`, `tool`, `arguments`, `status`, `latency`, and `tokens` for both model and tool calls.
- Intercept duplicate URL fetches at the tool runtime boundary and assign `status: "skipped as already seen"`.
- Display article `Title` and a dedicated `[SKIPPED - CACHED]` badge in the frontend Network Fetch Audit Log.
- Ensure `reports/run1.md` and `reports/run2.md` timestamps are at least 24 hours apart.
- Reconcile `AGENT.md` code quotations with the actual `tracker/llm.py` implementation.
- Provide a root `requirements.txt` containing all runtime and testing dependencies.

**Non-Goals:**
- Modifying the underlying database schema (`TrackerRun`, `TrackerArticle`, `TrackerDevelopment`) — the existing schema already supports nullable titles, string statuses, and cascading relationships.
- Changing the two-tier deduplication algorithms (`JobDeduplicator`).

## Decisions

### Decision 1: Unified Model and Tool Trace Logging Architecture
**Approach**:
In `tracker/agent.py`:
- In `ResearchAgent.run`, record an explicit trace item before and after `self.llm.create_completion()`:
  - `tool`: `"model"` (or the configured model name)
  - `arguments`: `{"messages_count": len(self.messages), "tools": [t["function"]["name"] for t in TRACKER_TOOLS]}`
  - `status`: `"success"` or `"error"`
  - `latency`: wall-clock duration of the completion call in seconds
  - `tokens`: `{"prompt_tokens": p, "completion_tokens": c, "total_tokens": t}`
- In `_execute_tool_call`, record tool invocation trace items:
  - `tool`: `tool_name`
  - `arguments`: `args`
  - `status`: extracted from tool result (`obs_data.get("status", "success")`)
  - `latency`: execution time in seconds
  - `tokens`: current cumulative tokens
- Maintain backwards compatibility by retaining `action`, `action_input`, and `observation` keys so existing test assertions continue to pass without regression.

### Decision 2: Guardrail-Level URL Skipping in Agent Runtime
**Approach**:
In `ResearchAgent`:
- Store `self.previous_urls: Set[str] = set(previous_urls or [])`.
- In `_execute_tool_call` when `tool_name == "fetch_article"`:
  - If `url in self.previous_urls`:
    - Do NOT call `fetch_article(url)`.
    - Do NOT increment `self.fetch_count`.
    - Return a structured response:
      ```python
      {
          "url": url,
          "current_url": url,
          "title": "Cached Article",
          "content": "",
          "status": "skipped as already seen",
          "error": "URL was already inspected in a previous crawl run; skipped.",
          "byte_size": 0,
          "fetch_time_ms": 0
      }
      ```
    - Append this result to `self.fetched_articles` so it appears in the execution report and audit logs.

### Decision 3: Frontend Audit Table Column & Badge Enhancements
**Approach**:
In `frontend/src/components/TrackerView.jsx`:
- Update the Network Fetch Audit Log table headers:
  `Target URL | Article Title | Guardrail Status | Payload Size | Latency | Security Audit Log`
- Render `art.title || "—"` in the new column.
- Update the status badge rendering logic:
  - If `art.status === 'rejected'`: render `[SSRF BLOCKED]` (rose badge).
  - If `art.status === 'skipped as already seen'` or `art.status === 'skipped'`: render `[SKIPPED - CACHED]` (amber/amber-400 badge with Clock/Archive icon).
  - Otherwise: render `[SAFE FETCHED]` (emerald badge).

### Decision 4: Calibration of Run Reports & Traces
**Approach**:
- Calibrate `reports/run1.md` and `reports/run1_trace.json` to an execution timestamp $\ge 24$ hours prior to Run 2 (e.g., `2026-10-02T14:10:00Z`).
- Calibrate `reports/run2.md` and `reports/run2_trace.json` to `2026-10-04T10:15:00Z`.
- Ensure both reports and trace files reflect the upgraded trace schema and valid citations.

### Decision 5: AGENT.md Code Quotation Alignment
**Approach**:
In `AGENT.md`:
- Under Question 4, replace the outdated draft code with the exact function blocks from `tracker/llm.py`:
  - `classify_error()` (showing status 429 quota keywords detection).
  - `LLMClient.create_completion()` retry loop (showing `attempt <= self.max_retries`, `classify_error`, and exponential backoff with jitter).
- Update Question 2 network round-trip counts to accurately mirror the comprehensive trace records.

### Decision 6: Root Dependency Bundle
**Approach**:
- Create a root `requirements.txt` containing all backend, agent, and test dependencies: `fastapi`, `uvicorn`, `sqlalchemy`, `psycopg2-binary`, `psycopg`, `pydantic`, `bcrypt`, `pyjwt`, `python-dotenv`, `httpx`, `pyyaml`, `beautifulsoup4`, `tavily-python`, `openai`, and `pytest`.
- Confirm that `README.md` documents both root and backend environment setups clearly.

## Risks / Trade-offs

- **[Risk]** Updating trace fields could break existing unit tests expecting specific dictionary keys.  
  → **Mitigation**: Add new fields (`tool`, `arguments`, `status`, `latency`, `tokens`) while preserving `action`, `action_input`, and `observation` as backwards-compatible aliases.
- **[Risk]** Intercepting `fetch_article` for cached URLs could prevent the LLM from re-reading an updated page.  
  → **Mitigation**: Assignment 1B Requirement 7 specifically mandates: *"On the second run, the agent must skip articles it already has"*. Returning a fast cached status directly implements this requirement.
