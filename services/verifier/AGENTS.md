# Verifier Service Contract and Operational Guide

Autonomous HTTP microservice responsible for independently verifying factual claims against cited web sources.

## Contracts and Network Interface

- **Port**: `8002` (by default)
- **Authentication**: `Authorization: Bearer <VERIFIER_TOKEN>`
- **Endpoints**:
  - `GET /healthz`: Public, unauthenticated readiness probe returning `{"status": "ok"}`.
  - `POST /verify`: Authenticated worker endpoint accepting `shared.contracts.VerifyRequest` and returning `shared.contracts.VerifyResponse`.
- **Status Matrix**:
  - `401 Unauthorized`: Missing or invalid Bearer token (evaluated before JSON parsing).
  - `400 Bad Request`: Malformed JSON or schema validation failure.
  - `409 Conflict`: Reused `request_id` with an altered payload hash.
  - `503 Service Unavailable`: Duplicate identical request arriving while original is in flight (`Retry-After: 5`).
  - `200 OK`: Completed or partial verification results, or cached replay of a prior successful request.
  - `500 Internal Server Error`: Terminal unhandled failure, cached and replayed for duplicate identical requests.

## Isolation and Security Guarantees

- **Zero Direct Dependency on Backend/Researcher**: No imports from `tracker.*`, `backend.*`, or `services.researcher.*`. The service must not possess database credentials or run storage access.
- **Independent Source Retrieval**:
  - Claims grouped by identical `source_url` within a request so each source is fetched at most once.
  - No page caching or sharing across requests.
  - Direct prohibited URLs or SSRF blocked destinations are classified as `unreachable` without making prohibited connections.
- **SSRF Defense**:
  - Hostnames pre-resolved via DNS before connection.
  - Rejection of IPv4/IPv6 loopback, private networks, cloud metadata (`169.254.169.254`), link-local, and reserved ranges. Public IPv6 is permitted.
  - Connections pinned to validated IPs to defeat DNS rebinding.
  - Hop-by-hop redirect inspection capped at 3 hops; redirects stop when remaining fetch budget is 0.
  - Streaming response byte cap strictly enforced at 1 MiB (`1,048,576` bytes).
- **Code-Level Evidence Verification**:
  - Normalized string matching (HTML unescape, NFKC, whitespace collapse, outer trim, lowercase).
  - Maximum excerpt length of 300 Unicode characters.
  - Downgrades non-matching, overlong, or blank excerpts to `unsupported` with `evidence=null`.
- **Untrusted Input Boundary**:
  - Claim and source text demarcated from instructions. Control flow and budgets remain code-controlled.
- **Resource Accounting & Telemetry**:
  - Monotonic clock enforcement against `time_budget_ms`.
  - Correlated 11-field JSONL traces logged for all inbound requests, source fetches, and model calls without secrets.

## Key Operational Commands

```powershell
# Run the Verifier service standalone
uvicorn services.verifier.app:app --port 8002

# Run Verifier unit and integration tests
pytest tests/test_verifier*.py -v

# Run type checker
pyright services/verifier
```
