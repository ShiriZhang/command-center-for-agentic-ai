# Researcher Service Contract and Operational Guide

Autonomous HTTP microservice responsible for discovering, ranking, and synthesizing job developments and cited atomic claims.

## Contracts and Network Interface

- **Port**: `8001` (by default)
- **Authentication**: `Authorization: Bearer <RESEARCHER_TOKEN>`
- **Endpoints**:
  - `GET /healthz`: Public, unauthenticated readiness probe returning `{"status": "ok"}`.
  - `POST /research`: Authenticated worker endpoint accepting `shared.contracts.ResearchRequest` and returning `shared.contracts.ResearchResponse`.
- **Status Matrix**:
  - `401 Unauthorized`: Missing or invalid Bearer token (evaluated before JSON parsing).
  - `400 Bad Request`: Malformed JSON or schema validation failure.
  - `409 Conflict`: Reused `request_id` with an altered payload hash.
  - `503 Service Unavailable`: Duplicate identical request arriving while original is in flight (`Retry-After: 5`).
  - `200 OK`: Completed or partial research results, or cached replay of a prior successful request.
  - `500 Internal Server Error`: Terminal unhandled failure, cached and replayed for duplicate identical requests.

## Isolation and Security Guarantees

- **Credential & Storage Isolation**: Zero imports from `tracker.*` or `backend.*`. The service must not possess database credentials, ORM models, or file persistence access.
- **SSRF Defense**:
  - Hostnames pre-resolved via DNS before connection.
  - Rejection of IPv4/IPv6 loopback, private networks, cloud metadata (`169.254.169.254`), link-local, and reserved ranges. Public IPv6 is permitted.
  - Connections pinned to validated IPs to defeat DNS rebinding.
  - Manual hop-by-hop redirect inspection capped at 3 hops; redirects stop when remaining fetch budget is 0.
  - Streaming response byte cap strictly enforced at 1 MiB (`1,048,576` bytes).
- **Resource Accounting**:
  - Monotonic clock enforcement against `time_budget_ms`.
  - Conservative pre-call token reservations.
  - Telemetry: Correlated 11-field JSONL traces logged for all inbound requests and outbound fetch/discovery operations.

## Key Operational Commands

```powershell
# Run the Researcher service standalone
uvicorn services.researcher.app:app --port 8001

# Run Researcher unit and integration tests
pytest tests/test_researcher_service.py tests/test_researcher_idempotency.py tests/test_researcher_fetch.py tests/test_researcher_synthesis.py tests/test_researcher_runtime.py tests/test_researcher_telemetry.py -v

# Run type checker
pyright services/researcher
```
