# Spec Delta

## ADDED Requirements

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

## MODIFIED Requirements

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
