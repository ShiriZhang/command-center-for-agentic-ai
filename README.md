# FNMS Assignment 1, 1B & 2: Foundations, Command Center & Agentic Orchestration

> **Course:** CSCI-GA.2630 · Foundations of Networks and Mobile Systems (Fall 2026)  
> **Student:** Shiyu Zhang  
> **Topic:** Top 10 newest entry-level and new grad AI/ML engineering roles ($K=10$)  
> **Repository:** Full-Stack Foundations, Autonomous Command Center & Multi-Agent Orchestration  

---

## 1. What It Is

This platform evolves from a secure, decoupled full-stack foundation (Assignment 1) and an autonomous single-agent tracker (Assignment 1B) into an **authenticated, distributed three-service agentic orchestration system** (Assignment 2):

1. **Backend Orchestrator** (`backend/app` on port `8000`):  
   Deterministic Python control plane owning persistent run state in Neon PostgreSQL, user admission, reservation accounting, multi-run diffing, and final report assembly. Contains zero third-party multi-agent frameworks (LangGraph, CrewAI, AutoGen prohibited).
2. **Researcher Worker** (`services/researcher` on port `8001`):  
   Autonomous discovery service executing web searches across corporate ATS portals (Greenhouse, Lever, Ashby) without database access, returning ranked developments broken into atomic cited claims.
3. **Verifier Worker** (`services/verifier` on port `8002` locally, deployed to Render free tier):  
   Independent claim-auditing service that retrieves each cited source itself via DNS pre-resolution SSRF guardrails. Enforces factual claim grounding in pure Python code (`verify_evidence`) using Unicode normalization (`html.unescape`, NFKC, whitespace collapsing, outer trim, lowercase).

Workers communicate strictly over HTTP wire contracts ([`shared/contracts.py`](shared/contracts.py)) with independent Bearer tokens, process-local in-memory idempotency, and cold-start timeout buffers.

---

## 2. Prerequisites

- **Python**: `3.11+` (Developed and verified on `Python 3.13.9`)
- **Node.js**: `20+` (Developed and verified on `Node.js v22.18.0`, `npm 10.9.3`)
- **Git**
- **Operating System**: Windows, macOS, or Linux

---

## 3. Environment Configuration (.env)

A ready-to-run template covering all services is provided at [`.env.example`](.env.example). Create your root `.env` file:

```bash
# Copy template to .env
cp .env.example .env
```

Your root `.env` configuration:

```ini
# 1. Database Connection (Backend Orchestrator Only)
DATABASE_URL=postgresql://user:password@your-project.aws.neon.tech/neondb?sslmode=require

# 2. JWT Security (Backend Authentication)
JWT_SECRET=fnms-course-super-secret-key-change-in-production-2026
JWT_ALGORITHM=HS256
JWT_ACCESS_TOKEN_EXPIRE_MINUTES=120

# 3. Model & Search Credentials
OPENROUTER_API_KEY=your_openrouter_api_key_here
TAVILY_API_KEY=your_tavily_api_key_here
GROQ_API_KEY=your_groq_api_key_here

# 4. Orchestration Worker Services
RESEARCHER_URL=http://127.0.0.1:8001
RESEARCHER_TOKEN=replace_with_secure_researcher_token

VERIFIER_URL=http://127.0.0.1:8002
VERIFIER_TOKEN=replace_with_secure_verifier_token

# 5. Tracker CLI Execution Settings
TRACKER_USER=NYUgrader
TRACKER_PASSWORD=Courant2026!
BACKEND_URL=http://localhost:8000
```

---

## 4. Execution Commands (In Order)

### Option A: Three-Service Agentic Orchestration (Assignment 2)

#### Terminal 1 — Start the Backend Orchestrator (Port 8000)
From the project root:
```bash
# Activate Python virtual environment
.\.venv\Scripts\activate   # Windows
# source .venv/bin/activate  # macOS / Linux

# Run Orchestrator API server
uvicorn backend.app.main:app --host 0.0.0.0 --port 8000 --reload
```
*Backend API live at `http://localhost:8000` (Swagger docs at `http://localhost:8000/docs`).*

#### Terminal 2 — Start the Researcher Worker (Port 8001)
From the project root:
```bash
uvicorn services.researcher.app:app --host 0.0.0.0 --port 8001 --reload
```
*Researcher Worker live at `http://localhost:8001` (Health probe at `http://localhost:8001/healthz`).*

#### Terminal 3 — Start the Verifier Worker (Port 8002 / Render)
From the project root:
```bash
uvicorn services.verifier.app:app --host 0.0.0.0 --port 8002 --reload
```
*Verifier Worker live at `http://localhost:8002` (or deployed to Render free tier via [`render.yaml`](render.yaml)).*

#### Terminal 4 — Start the Frontend Command Center (Port 5173)
From the project root:
```bash
cd frontend
npm install
npm run dev
```
*Frontend command center live at `http://localhost:5173`.*

#### Terminal 5 — Execute Stage 7 Orchestration Runs
To trigger and execute the reproducible two-run orchestration cycle (Run 1 initial crawl + Run 2 differential recrawl):
```bash
python scripts/execute_stage7_runs.py
```
*Produces correlated JSONL traces and Markdown reports in [`reports/run1/`](reports/run1/) and [`reports/run2/`](reports/run2/).*

---

### Option B: Standalone Autonomous Tracker CLI (Assignment 1B Baseline)

The legacy single-agent loop remains fully functional for baseline comparison:

```bash
# Run 1: Initial Crawl
python -m tracker.run --reset

# Run 2: Differential Recrawl
python -m tracker.run
```

---

## 5. Standalone Tools CLI Execution (Without Model)

Individual tools can be tested directly from the terminal without invoking any LLM:

```bash
# 1. Fetch an article with DNS/SSRF guardrail and HTML extraction
python -m tracker.tools fetch_article "https://jobs.ashbyhq.com/quora/cf34f80e-fe5c-454d-bc9a-4c59993ffda0"

# 2. Test SSRF Guardrail blocking loopback addresses
python -m tracker.tools fetch_article "http://127.0.0.1:8000/internal-admin"

# 3. Execute dual-source web search (Tavily + AI Dev Jobs ATS seeding)
python -m tracker.tools search_web "entry level machine learning engineer new grad greenhouse" 5

# 4. Complete report synthesis via finish tool
python -m tracker.tools finish "Research complete. Discovered 10 verified roles."
```

---

## 6. Database Schema & Architecture

Persistent multi-run state is owned exclusively by the Orchestrator in **Neon Cloud PostgreSQL**, strictly scoped to the authenticated user with cascading deletion (`ondelete="CASCADE"`):

```
┌─────────────────────────────────┐
│              User               │
│  id, username, email, password  │
└────────────────┬────────────────┘
                 │ 1:N (CASCADE)
                 ▼
┌────────────────────────────────────────────────────────┐
│                      TrackerRun                        │
│  id, user_id, run_uuid, run_number, topic, target_k,   │
│  status, is_baseline_eligible, reset_generation,       │
│  researcher_status, verifier_status, reserved_steps,   │
│  measured_steps, charged_steps, stale_source_run_uuid, │
│  report_path, trace_path, created_at                   │
└───────┬───────────────────┬────────────────────┬───────┘
        │ 1:N (CASCADE)     │ 1:N (CASCADE)      │ 1:N (CASCADE)
        ▼                   ▼                    ▼
┌─────────────────┐ ┌──────────────────────┐ ┌────────────────────────┐
│ TrackerArticle  │ │  TrackerDevelopment  │ │      TrackerClaim      │
│ id, run_id,     │ │  id, run_id, rank,   │ │ id, run_id,            │
│ url, title,     │ │  title, company,     │ │ development_id,        │
│ status, bytes,  │ │  primary_url,        │ │ claim_id, text,        │
│ latency_ms,     │ │  location, salary,   │ │ source_url, verdict,   │
│ error_message   │ │  recrawl_status, fp  │ │ evidence, created_at   │
└─────────────────┘ └──────────┬───────────┘ └────────────────────────┘
                               │ 1:N (CASCADE)
                               └─────────────────┘
```

| Table Name | Column Name | Data Type | Constraints / Attributes | Description |
| :--- | :--- | :--- | :--- | :--- |
| `tracker_runs` | `id` | `INTEGER` | `PRIMARY KEY`, Auto-increment | Unique execution run identifier |
| | `user_id` | `INTEGER` | `FOREIGN KEY(users.id)`, `CASCADE` | Scoped user account ID |
| | `run_uuid` | `VARCHAR(36)` | `NOT NULL`, Unique | UUID shared across cross-service traces |
| | `run_number` | `INTEGER` | `NOT NULL` | Sequential run index (Run 1, Run 2, etc.) |
| | `topic` | `VARCHAR(255)`| `NOT NULL` | Configured tracking objective |
| | `target_k` | `INTEGER` | `NOT NULL`, Default 10 | Target number of top positions |
| | `status` | `VARCHAR(50)` | `NOT NULL` | `running`, `complete`, `partial`, or `error` |
| | `researcher_status`| `VARCHAR(50)`| Nullable | Researcher outcome (`complete`, `partial`, `failed`) |
| | `verifier_status` | `VARCHAR(50)`| Nullable | Verifier outcome (`complete`, `partial`, `failed`, `skipped`) |
| | `is_baseline_eligible` | `BOOLEAN` | `DEFAULT FALSE` | Only complete research promotes to comparison baseline |
| | `reset_generation` | `INTEGER` | `DEFAULT 0` | Scoped comparison lineage identifier |
| | `stale_source_run_uuid` | `VARCHAR(36)` | Nullable | Source run UUID when displaying stale fallback |
| | `reserved_steps` / `tokens` | `INTEGER` | Default 0 | Fixed slices reserved before dispatch |
| | `charged_steps` / `tokens` | `INTEGER` | Default 0 | Settled usage charged against budget |
| `tracker_developments` | `id` | `INTEGER` | `PRIMARY KEY`, Auto-increment | Unique ranked job posting identifier |
| | `run_id` | `INTEGER` | `FOREIGN KEY(tracker_runs.id)`, `CASCADE` | Enclosing run ID |
| | `rank` | `INTEGER` | `NOT NULL` | Position in Top K ranking (1 to 10) |
| | `title` | `VARCHAR(255)`| `NOT NULL` | Standardized job role title |
| | `company` | `VARCHAR(255)`| `NOT NULL` | Standardized corporate employer name |
| | `primary_url` | `TEXT` | `NOT NULL` | Verified corporate application portal link |
| | `recrawl_status`| `VARCHAR(50)`| `NOT NULL` | `New since last run`, `Still in top K`, `Dropped` |
| | `fingerprint` | `VARCHAR(255)`| Nullable | Deterministic slug fingerprint |
| `tracker_claims` | `id` | `INTEGER` | `PRIMARY KEY`, Auto-increment | Unique cited atomic claim record identifier |
| | `run_id` | `INTEGER` | `FOREIGN KEY(tracker_runs.id)`, `CASCADE` | Enclosing run ID |
| | `development_id` | `INTEGER` | `FOREIGN KEY(tracker_developments.id)`, `CASCADE` | Parent job development ID |
| | `claim_id` | `VARCHAR(64)` | `NOT NULL` | Run-unique claim identifier (e.g. `c1_1`) |
| | `text` | `TEXT` | `NOT NULL` | Atomic claim statement |
| | `source_url` | `TEXT` | `NOT NULL` | Cited primary source URL |
| | `verdict` | `VARCHAR(50)` | `NOT NULL` | `supported`, `unsupported`, `unreachable`, `unverified` |
| | `evidence` | `TEXT` | Nullable | Normalized source excerpt ($\le 300$ chars) |
| `tracker_articles` | `id` | `INTEGER` | `PRIMARY KEY`, Auto-increment | Unique article fetch audit identifier |
| | `run_id` | `INTEGER` | `FOREIGN KEY(tracker_runs.id)`, `CASCADE` | Run during which fetch was performed |
| | `url` | `TEXT` | `NOT NULL` | Target URL requested |
| | `status` | `VARCHAR(50)` | `NOT NULL` | `fetched`, `rejected`, or `error` |
| | `byte_size` | `INTEGER` | `NOT NULL` | Response byte count (capped at 1MB) |
| | `fetch_time_ms`| `INTEGER` | `NOT NULL` | Network request latency in milliseconds |
| | `error_message`| `TEXT` | Nullable | Reason for guardrail rejection or timeout |

---

## 7. Full-Stack API Endpoints Specification

Protected endpoints require header: `Authorization: Bearer <token>`.

### Backend Orchestrator (`http://localhost:8000`)

| Method | Path | Auth Required | Status Code | Purpose |
| :--- | :--- | :---: | :---: | :--- |
| `GET` | `/healthz` | No | `200` | Unauthenticated health check, returns `{"status": "ok"}` |
| `POST` | `/api/auth/register` | No | `201` | Creates account with bcrypt hash (12 rounds) |
| `POST` | `/api/auth/login` | No | `200` | Authenticates credentials, returns signed JWT token |
| `GET` | `/api/auth/me` | Yes | `200` | Returns profile of current authenticated user |
| `GET` | `/api/users/:id` | Yes | `200` | Read profile (Rule 3: 403 on cross-user attempt) |
| `PATCH`| `/api/users/:id` | Yes | `200` | Update user email or password (Rule 3: 403) |
| `DELETE`| `/api/users/:id` | Yes | `200` | Delete user account (Cascades to all tracker data) |
| `GET` | `/api/tracker/runs` | Yes | `200` | List user's runs with developments, claims, and fetch logs |
| `GET` | `/api/tracker/runs/:id`| Yes | `200` | Retrieve specific run (403 on cross-user access) |
| `POST` | `/api/tracker/runs` | Yes | `405` | **Method Not Allowed** (Public ingestion removed; use trigger) |
| `POST` | `/api/tracker/trigger`| Yes | `202` | Asynchronously dispatches orchestration run in background |
| `GET` | `/api/tracker/history` | Yes | `200` | Summary telemetry of user's historical crawl activity |
| `POST` | `/api/tracker/reset` | Yes | `200` | Advances reset generation, scoping new baseline lineage |
| `DELETE`| `/api/tracker/runs` | Yes | `200` | Reset / wipe all tracker runs for authenticated user |

### Worker Microservices

| Service | Method | Path | Auth Required | Status Code | Purpose |
| :--- | :--- | :--- | :---: | :---: | :--- |
| **Researcher** (8001) | `GET` | `/healthz` | No | `200` | Unauthenticated readiness check |
| | `POST` | `/research` | `RESEARCHER_TOKEN` | `200`/`400`/`401`/`409`/`503` | Discovers Top K roles and decomposes into atomic claims |
| **Verifier** (8002 / Render) | `GET` | `/healthz` | No | `200` | Unauthenticated readiness check |
| | `POST` | `/verify` | `VERIFIER_TOKEN` | `200`/`400`/`401`/`409`/`503` | Fetches sources independently and audits claim excerpts |

---

## 8. Security Guardrails & Architectural Guarantees

1. **Token-Before-Body Authentication:**  
   Workers validate `Authorization: Bearer <token>` before parsing raw JSON bytes. Missing or invalid tokens immediately yield HTTP 401 without revealing schema details.
2. **SSRF Guardrail & Pinned Network Transport:**  
   Pre-resolves hostnames via `socket.getaddrinfo()`. Rejects loopback (`127.0.0.0/8`, `::1`), RFC 1918 private subnets, and cloud metadata (`169.254.169.254`). Uses custom `PinnedSyncBackend` connecting directly to approved IPs to prevent Time-of-Check-to-Time-of-Use (TOCTOU) DNS rebinding. Manually inspects redirects up to 3 hops with a 1MB streaming cap.
3. **Pure-Code Evidence Grounding:**  
   The Verifier's Python code (`normalize_for_matching`) normalizes text via HTML entity unescaping, Unicode NFKC, whitespace collapsing, outer trimming, and lowercase matching. Supported verdicts require an exact substring excerpt of $\le 300$ characters from the fetched page.
4. **Process-Local Idempotency Engine:**  
   Both workers implement `IdempotencyRegistry` computing canonical SHA-256 hashes over sorted keys. Identical completed requests replay cached outputs with 0 duplicate model calls and 0 fetches. Concurrent duplicates receive HTTP 503 with `Retry-After: 5`. Altered payloads with a reused `request_id` receive HTTP 409 Conflict.
5. **Cold-Start Resilience Buffer:**  
   Orchestrator attempt timeout (210s) significantly exceeds worker execution budget (120s), safely absorbing Render free-tier cold-start provisioning (~36s) without premature network aborts.
6. **Zero-Trust Frontend Plain Text Rendering:**  
   All job titles, company names, claims, and verification excerpts render as pure text nodes (`textContent`). HTML injection (`dangerouslySetInnerHTML`) is prohibited. Hyperlinks are validated strictly for `http:` and `https:` schemes.

---

## 9. Verification & Automated Test Suites

### 1. Stage 7 HTTP Matrix & Resilience Tests (Assignment 2)
Tests real TCP socket HTTP worker matrices, token-before-body barriers, idempotency deduplication, in-flight 503s, SSRF rejections, and cold-start attempt deadlines:
```bash
pytest tests/test_stage7_deployment_and_env.py tests/test_stage7_workers_http_matrix.py tests/test_stage7_resilience_matrix.py -v
```

### 2. Core Worker, Contract & Normalization Unit Tests
```bash
pytest tests/test_contracts.py tests/test_orchestration_config.py tests/test_verifier_normalization.py tests/test_verifier_fetch.py tests/test_verifier_idempotency.py -v
```

### 3. Legacy 4-Pillar Tracker Verification (Assignment 1B)
```bash
python scripts/test_tracker.py
```

---

## 10. Submission Deliverables Summary

- **Assignment 2 Architectural Analysis & Q&A**: [`ORCHESTRATION.md`](ORCHESTRATION.md) (All 5 required questions: wire fields rationale, Render cold-start latency analysis, idempotency code quotes, prompt injection threat model, and empirical comparison vs A1B)
- **Render Deployment Blueprint**: [`render.yaml`](render.yaml)
- **Assignment 2 Orchestration Deliverables**:
  - Run 1 Summary: [`reports/run1/summary.json`](reports/run1/summary.json)
  - Run 1 Markdown Report: [`reports/run1/run1_report.md`](reports/run1/run1_report.md)
  - Run 1 Correlated Traces: [`reports/run1/orchestrator.jsonl`](reports/run1/orchestrator.jsonl), [`reports/run1/researcher.jsonl`](reports/run1/researcher.jsonl), [`reports/run1/verifier.jsonl`](reports/run1/verifier.jsonl)
  - Run 2 Summary: [`reports/run2/summary.json`](reports/run2/summary.json)
  - Run 2 Markdown Report: [`reports/run2/run2_report.md`](reports/run2/run2_report.md)
  - Run 2 Correlated Traces: [`reports/run2/orchestrator.jsonl`](reports/run2/orchestrator.jsonl), [`reports/run2/researcher.jsonl`](reports/run2/researcher.jsonl), [`reports/run2/verifier.jsonl`](reports/run2/verifier.jsonl)
- **Domain Glossary**: [`GLOSSARY.md`](GLOSSARY.md)
- **Architecture Decision Records**: [`docs/adr/0001-decoupled-http-microservices.md`](docs/adr/0001-decoupled-http-microservices.md), [`docs/adr/0002-in-memory-idempotency-and-render-cold-starts.md`](docs/adr/0002-in-memory-idempotency-and-render-cold-starts.md)
- **OpenSpec Specification**: [`openspec/specs/agentic-orchestration/spec.md`](openspec/specs/agentic-orchestration/spec.md)
- **Assignment 1B Baseline Report**: [`AGENT.md`](AGENT.md)
- **Centralized Policy Configuration**: [`config.yaml`](config.yaml)
- **Environment Template**: [`.env.example`](.env.example)
