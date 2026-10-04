# Spec Delta: refine-agentic-tracker

## MODIFIED Requirements

### Requirement: Recrawl Memory and Multi-Run Differentiation
The tracker SHALL persist state between runs to ensure that subsequent runs skip already-fetched URLs, recognize developments previously covered, and organize findings into `New since last run`, `Still in top K`, and `Dropped`. When the agent requests to fetch an article that was already fetched in a prior run, the runtime tool executor SHALL immediately return `status: "skipped as already seen"` without initiating network requests or consuming fetch budget.

#### Scenario: Second run incremental analysis
- **WHEN** the agent is executed for a second time (`Run 2`)
- **THEN** it reads previous run state, skips URLs cached from `Run 1`, and formats the final report partitioned into `New since last run`, `Still in top K`, and `Dropped`.

#### Scenario: Already-seen article skipped at tool boundary
- **WHEN** the agent invokes `fetch_article` on a URL recorded in previous run state
- **THEN** the runtime intercepts the invocation, records `status: "skipped as already seen"`, does not decrement the remaining fetch budget, and returns the cached title and status.

## ADDED Requirements

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
