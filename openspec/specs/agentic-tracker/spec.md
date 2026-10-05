# agentic-tracker Specification

## Purpose
Provides an autonomous web research agent that discovers, ranks, and summarizes the top K newest entry-level and new grad AI/ML engineering roles with multi-run state memory, budget enforcement, network guardrails, and full-stack command center integration.

## Requirements

### Requirement: Handwritten Agent Runtime Loop
The system SHALL execute an autonomous research loop (`search -> fetch -> observe -> decide -> synthesize`) written natively in Python without utilizing external agent orchestration frameworks (such as LangChain, CrewAI, or AutoGen).

#### Scenario: Agent loop execution
- **WHEN** the user runs `python -m tracker.run`
- **THEN** the agent runtime initializes state, selects actions dynamically through LLM reasoning, executes tools, and terminates when `finish()` is called or a budget is exhausted.

### Requirement: Standalone CLI Tool Invocation
The system SHALL provide `search_web(query)`, `fetch_article(url)`, and `finish(report)` tools that are executable directly from the command line without invoking an LLM.

#### Scenario: Direct tool execution
- **WHEN** a user or test script runs `python -m tracker.tools fetch_article "https://example.com"`
- **THEN** the tool executes the fetch action independently and returns standard JSON output to stdout.

### Requirement: Centralized Configuration Policy
The system SHALL load all tracker execution policies, topic definitions, target K, allowed network schemes, and resource limits from a structured `config.yaml` file.

#### Scenario: Policy configuration parsing
- **WHEN** the agent starts up
- **THEN** it validates that `config.yaml` contains `topic`, `K`, `model`, `instructions`, `tools`, and `limits` (`max_steps`, `max_fetches`, and `token_budget`).

### Requirement: Runtime Budget Enforcement and Partial Reporting
The runtime SHALL track step counts, fetch operations, and token usage, and SHALL immediately halt execution when any budget limit is exceeded, producing a report marked `partial`.

#### Scenario: Fetch budget exhausted
- **WHEN** the count of fetched articles reaches `limits.max_fetches`
- **THEN** the agent ceases exploratory tool calls and synthesizes a final report marked with status `partial` using the evidence collected so far.

### Requirement: Failure Classification and Resilient Backoff
The runtime SHALL distinguish between transient failures (timeouts, HTTP 429 per-minute rate limits, HTTP 413 token-per-minute request limits) and terminal failures (HTTP 401 invalid credentials, HTTP 402 payment required, genuine account quota exhaustion).

#### Scenario: Handling HTTP 429 rate limit
- **WHEN** an upstream model or tool API returns HTTP 429 with retry indicators
- **THEN** the agent applies exponential backoff with a maximum retry cap before re-attempting the request.

#### Scenario: Handling Groq 413 TPM rate limit with billing URLs
- **WHEN** an upstream model returns HTTP 413 or rate_limit_exceeded referencing TPM capacity and containing upgrade/billing links
- **THEN** the classifier treats the failure as a transient rate limit or triggers context pruning, and does not classify it as terminal quota exhaustion.

#### Scenario: Handling terminal quota exhaustion
- **WHEN** an upstream API returns a terminal failure (such as daily quota exceeded or bad credentials)
- **THEN** the agent halts immediately without retrying and logs an explicit terminal error message.

### Requirement: Recrawl Memory and Multi-Run Differentiation
The tracker SHALL persist state between runs to ensure that subsequent runs skip already-fetched URLs, recognize developments previously covered, and organize findings into `New since last run`, `Still in top K`, and `Dropped`. When the agent requests to fetch an article that was already fetched in a prior run, the runtime tool executor SHALL return `status: "cached_active"` or `status: "skipped as already seen"` with valid retained metadata and without marking the event as an operational error.

#### Scenario: Second run incremental analysis
- **WHEN** the agent is executed for a second time (`Run 2`)
- **THEN** it reads previous run state, skips URLs cached from `Run 1`, and formats the final report partitioned into `New since last run`, `Still in top K`, and `Dropped`.

#### Scenario: Already-seen article skipped at tool boundary
- **WHEN** the agent invokes `fetch_article` on a URL recorded in previous run state
- **THEN** the runtime intercepts the invocation, records `status: "skipped as already seen"` or `status: "cached_active"`, does not decrement the remaining fetch budget, and returns the cached title and valid retained status.

### Requirement: Network SSRF Guardrails on Article Fetching
The `fetch_article` tool SHALL validate all URLs before initiating network connections, rejecting non-http(s) schemes, hosts resolving to loopback (`127.0.0.0/8`), private networks (`10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`), or link-local addresses (`169.254.0.0/16`), and enforcing byte size and timeout caps.

#### Scenario: Malicious loopback request rejected
- **WHEN** `fetch_article` is called with `http://127.0.0.1:8000/admin`
- **THEN** the guardrail halts the request before socket creation, returns a rejection status, and logs a security audit record.

### Requirement: Strict Data Provenance and Anti-Hallucination
Every job development included in the Top K report SHALL explicitly cite the source URL from which its title, company, and qualifications were extracted.

#### Scenario: Job report citation
- **WHEN** a ranked development is synthesized in the final report
- **THEN** it contains a verified source link to the job posting or announcement page.

### Requirement: Authenticated Backend Tracker Endpoints
The A1 backend SHALL expose `/api/tracker/runs` and `/api/tracker/history` endpoints that require valid JWT Bearer authentication and enforce cross-user horizontal authorization consistent with A1 Rule 3.

#### Scenario: Unauthorized access to tracker data
- **WHEN** a request without a valid Bearer token hits `/api/tracker/runs`
- **THEN** the backend responds with HTTP 401 Unauthorized.

### Requirement: Zero-Trust Plain Text Rendering in Frontend
The A1 frontend SHALL render all retrieved job titles, descriptions, and summaries as pure text nodes, strictly prohibiting the use of raw HTML injection (such as `dangerouslySetInnerHTML`) to prevent Stored XSS.

#### Scenario: Malicious script payload in crawled content
- **WHEN** fetched job data containing `<script>alert('xss')</script>` or malicious HTML tags is loaded into the frontend
- **THEN** the content is rendered as harmless visible text characters without executing any script.

### Requirement: Comprehensive Model and Tool Trace Logging
The runtime SHALL log every LLM model call and every tool call into the execution trace with `step`, `tool`, `arguments`, `status`, `latency`, and `tokens` (or credits).

#### Scenario: Logging model completion calls
- **WHEN** the agent runtime queries the LLM for next-step reasoning or tool calling
- **THEN** a trace record is appended recording `tool: "model"`, the conversation messages as `arguments`, the response `status`, the network `latency` in seconds, and `tokens` consumed.

#### Scenario: Logging tool invocations
- **WHEN** the agent runtime executes a tool (`search_web`, `fetch_article`, or `finish`)
- **THEN** a trace record is appended recording the tool name, its `arguments`, execution `status`, invocation `latency`, and relevant token/budget telemetry.

### Requirement: Frontend Article Audit Display Completeness
The frontend command center SHALL display the complete network audit log of all articles fetched, rejected, or skipped during each execution run, including page title, target URL, fetch latency, and distinctive status badges.

#### Scenario: Viewing skipped and fetched articles in audit log
- **WHEN** an authenticated user inspects a research run in the Tracker view
- **THEN** the audit table displays the article `title`, target `url`, `fetch_time_ms`, and displays `[SKIPPED - CACHED]` for cached URLs, `[SSRF BLOCKED]` for rejected URLs, and `[SAFE FETCHED]` for successful fetches.

### Requirement: Hierarchical Native Memory Package
The system SHALL organize agent memory into a dedicated native package (`tracker.memory`) comprising `WorkingMemory`, `EpisodicMemory`, and `SemanticMemory` without external memory frameworks or vector database dependencies.

#### Scenario: Unit testing isolated memory interfaces
- **WHEN** unit tests or runtime components import `WorkingMemory`, `EpisodicMemory`, and `SemanticMemory`
- **THEN** each memory class executes independently with standalone interfaces, clean state boundaries, and deterministic behavior.

### Requirement: Dynamic Working Context and Observation Pruning
The `WorkingMemory` module SHALL maintain a structured scratchpad of active candidates, verified openings, and step budgets, and SHALL prune older raw tool observations in conversation history down to compact single-line summaries to enforce that per-request prompt context remains below 2,500 tokens.

#### Scenario: Tool observation pruning during multi-step execution
- **WHEN** the agent loop executes multiple `search_web` or `fetch_article` tool calls across successive steps
- **THEN** `WorkingMemory` collapses past verbose tool response strings into concise metadata records, preventing quadratic context growth and avoiding upstream token-per-minute limits.

### Requirement: Priority-Queued Multi-Factor Candidate Scoring
The `SemanticMemory` module SHALL score discovered candidate roles using a multi-factor priority rubric (Freshness, Direct ATS Channel, Entry-Level Exemption) and discard postings that violate hard qualification boundaries.

#### Scenario: Freshness bonus and 30-day expiration
- **WHEN** a discovered job was posted within 24 hours
- **THEN** it receives a +5 freshness bonus.
- **WHEN** a discovered job was posted more than 30 days prior to the current system timestamp
- **THEN** the system immediately disqualifies the posting from the candidate queue.

#### Scenario: Seniority hard-filter exclusion
- **WHEN** a candidate role contains senior keywords (`senior`, `sr.`, `lead`, `staff`, `principal`, `director`, `5+ years`) without entry keywords (`new grad`, `entry level`, `junior`, `early career`, `intern`)
- **THEN** the system immediately disqualifies the posting.

### Requirement: Lazy Web Search and Resilient Fallback
The agent runtime SHALL prioritize direct fetching of candidate ATS links from AI Dev Jobs seeds, invoking web search (`search_web` / `search_tavily`) lazily only when direct links are absent or fetch operations fail, and SHALL automatically fall back to broad keyword search if the seed API encounters an outage.

#### Scenario: Direct ATS fetching without search call
- **WHEN** a candidate role contains an authentic corporate ATS link (`greenhouse.io`, `lever.co`, `ashbyhq.com`)
- **THEN** the agent fetches the URL directly without making intermediate search calls.

#### Scenario: Automatic fallback on seed API outage
- **WHEN** the AI Dev Jobs API returns an HTTP 5xx error or connection timeout
- **THEN** the system logs a fallback warning and transparently switches to Tavily keyword discovery without terminating the agent.
