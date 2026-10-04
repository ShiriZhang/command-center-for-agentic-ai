# Design: Agentic Tracker Architecture

## Context

See [proposal.md](proposal.md) for motivation and problem statement.
The current platform has a robust A1 authentication and user management foundation (FastAPI + Neon PostgreSQL + React/Vite/Tailwind). This design specifies the architecture for adding the Agentic Tracker (Assignment 1B) into this ecosystem.

## Goals / Non-Goals

**Goals:**
- Implement a handwritten, framework-free agent loop (`search -> fetch -> observe -> decide -> synthesize`) that runs as an authenticated client of the A1 platform.
- Support OpenRouter API as the primary model provider with seamless configuration fallback to Groq API via standard OpenAI-compatible client abstractions.
- Integrate Tavily API for open-web research alongside the AI Dev Jobs REST API for curated candidate seeding.
- Enforce strict SSRF guardrails on `fetch_article` with DNS resolution inspection, blocking loopback, private, and link-local IP ranges.
- Persist state across runs (Run 1 vs Run 2) in Neon PostgreSQL via authenticated backend endpoints (`/api/tracker/*`), categorizing results into `New since last run`, `Still in top K`, and `Dropped`.
- Support user-authenticated CLI execution with automatic run-number detection and `--reset` flag.
- Provide a responsive React dashboard in the A1 Command Center with a "Run Tracker" trigger button, strictly using plain text rendering to neutralize Stored XSS attacks.

**Non-Goals:**
- Automated job application or resume submission.
- Scraping sites requiring authentication or captcha circumvention.

## Decisions

### 1. Model Provider Abstraction: OpenRouter & Groq via OpenAI SDK
- **Decision**: Use the official `openai` Python SDK configured with dynamic `base_url` and `api_key` loaded from environment variables and `config.yaml`.
- **Key Strategy**: Pure online mode. Requires valid `OPENROUTER_API_KEY` and `TAVILY_API_KEY`. If keys are missing or invalid, the system halts immediately with a clear terminal failure message (satisfying Requirement 5).
- **Rationale**: Both OpenRouter (`https://openrouter.ai/api/v1`) and Groq (`https://api.groq.com/openai/v1`) implement standard OpenAI Chat Completions with Tool Calling. OpenRouter provides access to frontier models (e.g., `google/gemini-2.0-flash-exp:free`, `meta-llama/llama-3.3-70b-instruct:free`, or DeepSeek) while Groq provides ultra-low latency. Switching providers requires zero code changes—only editing `config.yaml`.

### 2. Dual-Source Search Strategy: Tavily + AI Dev Jobs API
- **Decision**: Implement `search_web(query)` utilizing Tavily Search API as the primary search engine, while allowing the agent loop to seed target role discoveries from `https://aidevboard.com/api/v1/jobs`.
- **Rationale**: Tavily provides agent-optimized open web search for direct corporate ATS career portals (Greenhouse, Lever, Ashby, Workday), guaranteeing standard CLI compatibility (`python -m tracker.tools search_web <query>`). AI Dev Jobs API provides rich structured job metadata.

### 3. Hop-by-Hop SSRF & Ingestion Guardrail Architecture
- **Decision**: In `fetch_article(url)`:
  1. Parse URL scheme: strictly enforce `http` or `https`.
  2. Resolve hostname to IPv4/IPv6 via `socket.getaddrinfo()`.
  3. Validate against Python `ipaddress` objects: reject `is_loopback`, `is_private`, `is_link_local`, `is_reserved`, `is_multicast`.
  4. **Hop-by-Hop Redirect Defense**: Disable automatic redirection in HTTP client (`follow_redirects=False`). When receiving HTTP 301/302/307/308, manually extract the `Location` target and re-execute full scheme validation and DNS IP resolution before following (max 3 hops). This completely blocks redirect-based SSRF bounce attacks (e.g., redirecting to `127.0.0.1` or `169.254.169.254`).
  5. Enforce a 10-second request timeout and 1MB response byte limit.
  6. Extract readable text using `beautifulsoup4` without executing JavaScript.
- **Rationale**: Prevents internal port scanning, cloud metadata extraction, and memory exhaustion denial-of-service.

### 4. Recrawl State Storage & User-Authenticated Backend Client
- **Decision**:
  - Add tables `tracker_runs`, `tracker_articles`, and `tracker_developments` in Neon PostgreSQL linked to the authenticated `User` with `ondelete="CASCADE"`. Account deletion automatically and completely purges all associated tracker records without orphan data.
  - Expose `GET /api/tracker/runs`, `POST /api/tracker/runs`, `POST /api/tracker/trigger`, and `GET /api/tracker/history` in FastAPI.
  - **User Authentication**: Every execution of Tracker requires a registered user account (such as `NYUgrader`). The CLI prompts for credentials or accepts `--username / --password` (with `.env` fallback), logs in via `POST /api/auth/login`, retrieves a JWT Bearer token, and scopes all tracker records to that user.
  - Multi-tenant isolation is strictly maintained under A1 Rule 3. Calling `--reset` deletes only the current authenticated user's run records.

### 5. Run 1 vs Run 2 Lifecycle & CLI Control
- **Decision**: Automatic run-state detection:
  - When `python -m tracker.run` is called:
    - If no prior runs exist for the user, it executes as **Run 1** and writes `reports/run1.md` and `reports/run1_trace.json`.
    - If prior runs exist, it executes as **Run 2** (skipping cached URLs, comparing with previous Top K, generating New / Retained / Dropped sections), writing `reports/run2.md` and `reports/run2_trace.json`.
  - A `--reset` flag (`python -m tracker.run --reset`) is provided to wipe saved tracker state for testing from scratch.

### 6. Two-Tier Job Deduplication & Canonical Representation (AGENT.md Q3 Alignment)
- **Decision**: Combine rule-based fingerprinting with model semantic disambiguation:
  - **Tier 1 (Fast-Path Deterministic Rule)**: Normalize `[slugify(company) + ":" + slugify(clean_title)]`. Identical fingerprints from different URLs are merged immediately without extra token cost.
  - **Tier 2 (Fuzzy Threshold Triggered LLM Disambiguation)**:
    - **Trigger Condition**: When two job postings belong to the same company (or alias) and their title token overlap meets a moderate threshold (e.g., Jaccard similarity > 0.5) but falls short of an exact match, invoke the LLM disambiguation check. This avoids wasteful LLM calls on completely disparate roles (e.g., Frontend vs ML).
    - **Inspection Criteria & Contract**: Instruct the LLM to inspect seniority level, core tech stack, and team/department focus. The LLM returns strict JSON: `{"is_same_role": bool, "reason": str, "canonical_title": str}`. On parse error or low confidence, the runtime conservatively defaults to `is_same_role = False` to prevent dropping legitimate opportunities.
  - **Multi-Source Merge Strategy**: When two URLs describe the same development, they are merged into a single canonical record. The primary URL prioritizes direct corporate ATS links (Greenhouse, Lever, Ashby, Workday), and secondary URLs are appended to `supporting_sources` (satisfying PDF Requirement 6).
  - **Documented Failure Case for AGENT.md Question 3**: Multi-team pooled hiring false positive (e.g., Meta posting two "Research Engineer - Early Career" positions, one in FAIR Foundation Models and one in Reality Labs). Due to matching titles, company, and overlapping ML qualifications, the system may mistakenly merge them into one development.

### 7. Frontend Command Center & Zero-Trust Plain Text Rendering
- **Decision**:
  - Extend the React navbar with an "Intelligence Tracker" dashboard.
  - Provide a **"Run Tracker Now"** button calling `/api/tracker/trigger` to run the tracker asynchronously and refresh results.
  - Render all job titles, descriptions, and summary texts inside standard React JSX expressions (`<span>{item.summary}</span>`).
  - **Rationale**: React automatically escapes string values, converting `<script>` into benign text entities (`&lt;script&gt;`), physically neutralizing seeded injection test pages.

## Risks / Trade-offs

- **[Risk] Upstream 429 Rate Limits from OpenRouter/Groq** → *Mitigation*: Implement exponential backoff with jitter and a 3-retry cap for transient 429 responses.
- **[Risk] Terminal daily quota exhaustion during testing** → *Mitigation*: Fail fast with an unambiguous error log without retrying, satisfying Requirement 5.
- **[Risk] Web page format discrepancies** → *Mitigation*: BeautifulSoup extracts clean text snippets with fallbacks for malformed HTML.
- **[Risk] Stale or dead links (Ghost Jobs)** → *Mitigation*: Verified live status via `fetch_article` before ranking in Top K.
