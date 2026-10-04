# Proposal: Add Agentic Tracker (Assignment 1B)

## Why

In Assignment 1, we built a secure, decoupled full-stack foundation with identity management. Assignment 1B requires "furnishing the empty room" by constructing the first intelligent, autonomous command-center tool: an **Agentic Tracker** for **Top 10 Newest Entry-level / New Grad AI & ML Engineering Roles**. Rather than using generic agent frameworks, this tracker implements a native Python research loop (`search -> fetch -> observe -> decide -> synthesize`) with cross-run memory, budget enforcement, network guardrails (SSRF protection), and zero-trust plain text UI rendering to defend against Stored XSS.

## What Changes

- **Agent Runtime & Tools**:
  - Implement a handwritten, framework-free agent loop in Python adhering to `config.yaml` policies and budget limits (`max_steps`, `max_fetches`, token/cost limits).
  - Provide standard standalone tools callable via CLI without LLM: `search_web(query)` (powered by Tavily API and AI Dev Jobs API), `fetch_article(url)` (with DNS/SSRF guardrail and size limits), and `finish(report)`.
  - Default LLM engine integration via OpenRouter API (OpenAI-compatible) with fallback flexibility to Groq API.
  - Implement failure classification: exponential backoff for transient 429 rate limits, and fail-fast termination for terminal failures (invalid keys, exhausted quotas).
- **Recrawl & State Persistence**:
  - Store run state, articles fetched, and ranked developments across runs in Neon PostgreSQL via backend API endpoints.
  - On subsequent runs (Run 2+), skip cached URLs, identify overlapping role postings across sources, and categorize findings into `New since last run`, `Still in top K`, and `Dropped`.
- **Backend API Extensions**:
  - Add authenticated endpoints `/api/tracker/runs` (GET, POST) and `/api/tracker/history` (GET) protected by A1 JWT Bearer token authentication.
- **Frontend Command Center UI**:
  - Add an "Intelligence Tracker" view behind the A1 authenticated session displaying:
    - Ranked Top 10 Job Developments with provenance links and category badges.
    - Run History Timeline (timestamps, tokens, latency, status changes).
    - Fetch Audit Table (URLs, statuses: fetched, skipped, rejected).
  - Enforce strict plain text rendering for all web content to eliminate Stored XSS vulnerabilities.

## Capabilities

### New Capabilities
- `agentic-tracker`: Autonomous web research agent runtime, budget controls, SSRF security guardrails, multi-run recrawl state tracking, and full-stack command center integration.

### Modified Capabilities
*(None - existing `auth-foundation` requirements remain unchanged)*

## Impact

- **Backend**: New database models (`TrackerRun`, `TrackerArticle`, `TrackerDevelopment`) and router (`/api/tracker/*`).
- **Dependencies**: New Python packages (`tavily-python`, `openai` SDK for OpenRouter/Groq, `beautifulsoup4`, `pyyaml`).
- **Frontend**: New UI components (`TrackerView.jsx`, subcomponents) integrated into `App.jsx` and Navbar.
- **Verification**: New standalone CLI runner (`python -m tracker.run`), automated test suites, and grading deliverable generators (`reports/run1.md`, `reports/run2.md`, trace logs, and `AGENT.md`).
