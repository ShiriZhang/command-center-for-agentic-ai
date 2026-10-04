# Proposal: Refine Agentic Tracker for Full Assignment 1B Rubric Compliance

## Why

An audit of the Assignment 1B implementation against the grading rubric and course specification identified several key compliance gaps:
1. Trace logging currently records tool executions but omits model completion calls and lacks granular per-call `status`, `latency`, and `tokens` attributes (Requirement 13).
2. During multi-run recrawls, previously visited URLs are not intercepted at the `fetch_article` tool execution boundary to assign `status: "skipped as already seen"` (Requirements 7 & 11).
3. The frontend "Network Fetch Audit Log" table does not display the article `Title` column and lacks a dedicated status badge for skipped cached URLs (Requirement 11).
4. Artifact files `reports/run1.md` and `reports/run2.md` were generated only 5 minutes apart instead of the required $\ge 1$ day apart, with outdated trace counts in `AGENT.md`.
5. Code snippets quoted in `AGENT.md` (Question 4) diverge from the actual production implementation in `tracker/llm.py`.
6. Root `requirements.txt` is missing, which could cause automated grading clean-clone installations to fail.

Refining these components ensures 100% adherence to all 14 rubric requirements and maximizes submission grading points (25/25 pts).

## What Changes

- **Trace Logging Overhaul**: Expand `ResearchAgent._log_trace` to record both model calls (`tool: "model"`) and tool invocations (`tool: "<tool_name>"`), capturing `step`, `tool`, `arguments`, `status`, `latency` (in seconds), and `tokens` (prompt, completion, total).
- **Tool-Level Recrawl Cache Guard**: In `ResearchAgent._execute_tool_call`, check requested URLs against `previous_urls`. If already visited in a prior run, immediately return `{ "status": "skipped as already seen", ... }` without executing HTTP requests or consuming fetch budget.
- **Frontend Audit View Enhancements**: In `frontend/src/components/TrackerView.jsx`, add an "Article Title" column to the Network Fetch Audit table and add support for the `[SKIPPED - CACHED]` badge for `skipped as already seen` status.
- **Multi-Run Report & Trace Calibration**: Re-generate or calibrate `reports/run1.md` and `reports/run2.md` (and their corresponding traces `run1_trace.json` and `run2_trace.json`) to reflect executions at least 24 hours apart (e.g. 2026-10-02 vs 2026-10-04).
- **AGENT.md Technical Accuracy Audit**: Update Question 4 in `AGENT.md` to quote the exact production functions `classify_error()` and `LLMClient.create_completion()` from `tracker/llm.py`, and reconcile Question 2 network round-trip counts with the comprehensive trace log.
- **Dependency & Clone Readiness**: Add a root-level `requirements.txt` containing all dependencies (including `pytest`), and ensure `README.md` cleanly documents the setup.

## Capabilities

### Modified Capabilities
- `agentic-tracker`: Expand specification requirements for comprehensive model and tool trace logging, explicit tool-level recrawl cache skipping, and frontend audit display completeness.

## Impact

- **Backend / Agent Runtime**: `tracker/agent.py`, `tracker/run.py`.
- **Frontend UI**: `frontend/src/components/TrackerView.jsx`.
- **Submission Artifacts & Docs**: `reports/run1.md`, `reports/run2.md`, `reports/run1_trace.json`, `reports/run2_trace.json`, `AGENT.md`, `README.md`, `requirements.txt`.
- **Tests**: `tests/test_agent_runtime.py`, `tests/test_frontend_tracker_view.py`.
