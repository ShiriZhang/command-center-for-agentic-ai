# Tasks: refine-agentic-tracker

## 1. Backend and Agent Runtime Refinement

- [x] 1.1 Implement model completion call trace logging in `tracker/agent.py` recording `step`, `tool: "model"`, `arguments`, `status`, `latency`, and `tokens`, and verify via unit tests in `tests/test_agent_runtime.py`
- [x] 1.2 Upgrade tool execution trace logging in `tracker/agent.py` to capture invocation `latency`, execution `status`, and granular telemetry while preserving backwards-compatible keys, and verify via `tests/test_agent_runtime.py`
- [x] 1.3 Implement `skipped as already seen` cache guard in `ResearchAgent._execute_tool_call` when a requested URL is present in `previous_urls`, preventing redundant network requests, and verify via unit tests

## 2. Frontend Display Enhancements

- [x] 2.1 Add an Article Title column to the Network Fetch Audit Log table in `frontend/src/components/TrackerView.jsx` and verify layout rendering
- [x] 2.2 Add dedicated `[SKIPPED - CACHED]` status badge rendering for `skipped as already seen` records in `frontend/src/components/TrackerView.jsx` and verify via `tests/test_frontend_tracker_view.py`

## 3. Reports, Telemetry, and Documentation Calibration

- [x] 3.1 Calibrate `reports/run1.md`, `reports/run2.md`, `reports/run1_trace.json`, and `reports/run2_trace.json` to have execution timestamps separated by $\ge 24$ hours and adhere to the upgraded trace format
- [x] 3.2 Update `AGENT.md` Question 4 to quote exact production functions `classify_error()` and `LLMClient.create_completion()` from `tracker/llm.py`, and reconcile Question 2 network round-trip counts with the comprehensive trace log
- [x] 3.3 Add root `requirements.txt` containing all runtime and testing dependencies (including `pytest`), and verify `README.md` setup commands

## 4. End-to-End System Verification

- [x] 4.1 Run full unit and integration test suite (`pytest` and `scripts/test_tracker.py`) to verify zero regressions across all 4 assignment pillars and full-stack API routes
