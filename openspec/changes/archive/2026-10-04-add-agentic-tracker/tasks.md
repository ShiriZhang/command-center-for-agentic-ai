# Tasks: Add Agentic Tracker

## 1. Tracker Scaffolding and Policy Configuration

- [x] 1.1 Create tracker module structure (`tracker/`) and define `config.yaml` with topic, K=10, limits, allowed schemes/hosts, and OpenRouter default model configuration. Verify configuration parses via python script.
- [x] 1.2 Implement `tracker/config.py` using Pydantic/dataclasses to load and validate `config.yaml` and `.env` variables (`OPENROUTER_API_KEY`, `TAVILY_API_KEY`). Verify with a unit test.

## 2. Standalone Tools and Security Guardrails

- [x] 2.1 Implement `fetch_article(url)` in `tracker/tools/fetch.py` with DNS pre-resolution SSRF guardrail (rejecting loopback `127.0.0.1`, private ranges `10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`, and link-local `169.254.0.0/16`), 10s timeout, 1MB size limit, and HTML-to-text extraction. Verify guardrail blocks `http://127.0.0.1` and passes public URLs.
- [x] 2.2 Implement `search_web(query)` in `tracker/tools/search.py` supporting Tavily Search API with candidate discovery integration for `https://aidevboard.com/api/v1/jobs`. Verify search results return normalized title, snippet, and URL fields.
- [x] 2.3 Implement CLI dispatcher in `tracker/tools/__main__.py` enabling standalone tool execution without model (`python -m tracker.tools fetch_article <url>`). Verify execution from terminal.

## 3. Agent Runtime Loop and Failure Classifier

- [x] 3.1 Implement LLM client wrapper in `tracker/llm.py` supporting OpenRouter and Groq via OpenAI SDK, with failure classification: exponential backoff for transient 429 rate limits and fail-fast termination for terminal 401/402/quota failures. Verify terminal failure stops immediately without retries.
- [x] 3.2 Implement handwritten agent state machine in `tracker/agent.py` (`search -> fetch -> observe -> decide -> synthesize`) enforcing `max_steps`, `max_fetches`, and `token_budget` limits and generating partial reports upon budget exhaustion. Verify agent stops when step budget is reached.

## 4. Recrawl Memory and Report Synthesis

- [x] 4.1 Implement recrawl memory manager in `tracker/memory.py` with two-tier deduplication (normalized company/title fingerprint + LLM semantic disambiguation) to persist visited URLs and canonical developments, and classify items into `New since last run`, `Still in top K`, and `Dropped`. Verify deduplication logic between mock Run 1 and Run 2 data.
- [x] 4.2 Implement report synthesizer, trace logger, and CLI runner (`python -m tracker.run`) in `tracker/reporter.py` and `tracker/run.py` supporting user login, automatic Run 1/Run 2 detection, and `--reset` flag. Verify output reports `reports/run1.md` and `reports/run2.md` match specifications.

## 5. Backend Database Models and Tracker Endpoints

- [x] 5.1 Define SQLAlchemy models `TrackerRun`, `TrackerArticle`, and `TrackerDevelopment` in `backend/app/models.py` and register database migration/lifespan table creation. Verify database tables exist in Neon PostgreSQL.
- [x] 5.2 Implement Pydantic schemas in `backend/app/schemas.py` and endpoints `GET /api/tracker/runs`, `POST /api/tracker/runs`, `POST /api/tracker/trigger`, and `GET /api/tracker/history` in `backend/app/routes/tracker.py` with JWT Bearer authentication and Rule 3 authorization. Verify authenticated access succeeds and unauthenticated access returns 401.

## 6. Frontend Command Center Tracker UI

- [x] 6.1 Create `TrackerView.jsx` in `frontend/src/components/` rendering Top 10 Job cards (`[NEW]`, `[STILL IN TOP 10]`, `[DROPPED]`), Run History, Fetch Audit table, and a "Run Tracker Now" trigger button using strict plain text rendering to neutralize Stored-XSS. Verify components render sample job data safely without `dangerouslySetInnerHTML`.
- [x] 6.2 Integrate `TrackerView` into `frontend/src/App.jsx` and `Navbar.jsx`, adding API client methods in `frontend/src/api/client.js`. Verify navigation and live data loading from backend endpoints.

## 7. Verification, AGENT.md, and Handoff Documentation

- [x] 7.1 Implement automated verification script `scripts/test_tracker.py` exercising SSRF guardrail attacks, bogus API key terminal handling, budget exhaustion, and two-run recrawl differentiation. Verify all tests pass.
- [x] 7.2 Run two distinct tracker executions to produce deliverables `reports/run1.md`, `reports/run2.md`, and corresponding trace logs. Verify reports contain verified source provenance.
- [x] 7.3 Author `AGENT.md` answering the 5 required system questions and update `README.md` with exact startup and runner commands. Verify README commands run cleanly.
