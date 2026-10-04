# Spec Delta: Agentic Tracker

## Purpose

Provides an autonomous web research agent that discovers, ranks, and summarizes the top K newest entry-level and new grad AI/ML engineering roles with multi-run state memory, budget enforcement, network guardrails, and full-stack command center integration.

## ADDED Requirements

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
The runtime SHALL distinguish between transient failures (timeouts, HTTP 429 per-minute rate limits) and terminal failures (HTTP 401 invalid credentials, HTTP 402 payment required, daily quota exhaustion).

#### Scenario: Handling HTTP 429 rate limit
- **WHEN** an upstream model or tool API returns HTTP 429 with retry indicators
- **THEN** the agent applies exponential backoff with a maximum retry cap before re-attempting the request.

#### Scenario: Handling terminal quota exhaustion
- **WHEN** an upstream API returns a terminal failure (such as daily quota exceeded or bad credentials)
- **THEN** the agent halts immediately without retrying and logs an explicit terminal error message.

### Requirement: Recrawl Memory and Multi-Run Differentiation
The tracker SHALL persist state between runs to ensure that subsequent runs skip already-fetched URLs, recognize developments previously covered, and organize findings into `New since last run`, `Still in top K`, and `Dropped`.

#### Scenario: Second run incremental analysis
- **WHEN** the agent is executed for a second time (`Run 2`)
- **THEN** it reads previous run state, skips URLs cached from `Run 1`, and formats the final report partitioned into `New since last run`, `Still in top K`, and `Dropped`.

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
