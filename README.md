# FNMS Assignment 1 & 1B: Foundations, Command Center & Agentic Tracker

> **CSCI-GA.2630 · Foundations of Networks and Mobile Systems (Fall 2026)**  
> **Student:** Shiyu Zhang  
> **Topic:** Top 10 newest entry-level and new grad AI/ML engineering roles ($K=10$)  
> **Repository:** Full-Stack Foundations & Autonomous Command Center for Agentic AI  

---

## 1. What It Is

This platform combines a secure, decoupled full-stack foundation (Assignment 1) with an autonomous, framework-free research agent (Assignment 1B). 
The **Agentic Tracker** autonomously monitors the web for the **Top 10 newest entry-level and new grad AI/ML engineering roles**, verifies authentic corporate application links (Greenhouse, Lever, Ashby, Workday), enforces network SSRF security guardrails and resource budgets, remembers state between runs, and displays live ranked findings and audit logs in the command center frontend.

---

## 2. Prerequisites

- **Python**: `3.11+` (Developed and verified on `Python 3.13.9`)
- **Node.js**: `20+` (Developed and verified on `Node.js v22.18.0`, `npm 10.9.3`)
- **Git**
- **Operating System**: Windows, macOS, or Linux

---

## 3. Environment Configuration (.env)

A ready-to-run template is provided at [`.env.example`](.env.example). Create your root `.env` file:

```bash
# Copy template to .env
cp .env.example .env
```

Your root `.env` contains:

```ini
# 1. OpenRouter API Key (Primary LLM Provider)
OPENROUTER_API_KEY=your_openrouter_api_key_here

# 2. Tavily Search API Key (Web Search)
TAVILY_API_KEY=your_tavily_api_key_here

# 3. Optional: Groq API Key (Ultra-fast fallback provider)
GROQ_API_KEY=your_groq_api_key_here

# 4. Neon Cloud PostgreSQL Connection String (Course throwaway database)
DATABASE_URL=postgresql://neondb_owner:npg_fpFyclhiC0D9@ep-broad-bird-b4p2idis-pooler.c-6.us-east-2.aws.neon.tech/neondb?sslmode=require&channel_binding=require

# 5. Security & Authentication Settings
JWT_SECRET=fnms-course-super-secret-key-change-in-production-2026
JWT_ALGORITHM=HS256
JWT_ACCESS_TOKEN_EXPIRE_MINUTES=120
TRACKER_USER=NYUgrader
TRACKER_PASSWORD=Courant2026!
BACKEND_URL=http://localhost:8000
```

---

## 4. Exact Execution Commands (In Order)

### Command 1: Bring Up Your A1 Backend and Frontend

#### Terminal 1 — Start the Backend Server (Port 8000)
From the project root:
```bash
cd backend
python -m venv .venv

# On Windows (PowerShell):
.\.venv\Scripts\activate
# On macOS / Linux:
# source .venv/bin/activate

pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```
*The backend API will be live at `http://localhost:8000` (Swagger docs at `http://localhost:8000/docs`).*

#### Terminal 2 — Start the Frontend Application (Port 5173)
From the project root:
```bash
cd frontend
npm install
npm run dev
```
*The frontend command center will be live at `http://localhost:5173`.*

---

### Command 2: Run the Tracker (Run 1: Initial Crawl)

From the project root in an activated Python terminal:
```bash
python -m tracker.run --reset
```
*Authenticates as `NYUgrader`, executes the initial autonomous crawl, produces [`reports/run1.md`](reports/run1.md) and [`reports/run1_trace.json`](reports/run1_trace.json), caches visited URLs to `reports/tracker_state.json`, and syncs results to Neon PostgreSQL.*

---

### Command 3: Run It Again (Run 2: Differential Recrawl)

From the project root in an activated Python terminal:
```bash
python -m tracker.run
```
*Detects prior run state, skips the 9 cached URLs from Run 1, discovers new roles, categorizes them into `New since last run`, `Still in top K`, and `Dropped`, and generates [`reports/run2.md`](reports/run2.md) and [`reports/run2_trace.json`](reports/run2_trace.json).*

---

### Command 4: Reset Its Saved State

From the project root in an activated Python terminal:
```bash
python -m tracker.run --reset
```
*Wipes local recrawl memory state (`reports/tracker_state.json`) and resets the tracker to run as a clean Run 1.*

---

## 5. Standalone Tools CLI Execution (Without Model)

Each standalone tool can be executed directly from the terminal without invoking any LLM:

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

The tracker stores persistent state in **Neon Cloud PostgreSQL**, strictly normalized and scoped to the authenticated user with cascading deletion (`ondelete="CASCADE"`):

```
┌─────────────────────────────────┐
│              User               │
│  id, username, email, password  │
└────────────────┬────────────────┘
                 │ 1:N (CASCADE)
                 ▼
┌────────────────────────────────────────────────────────┐
│                      TrackerRun                        │
│  id, user_id, run_number, topic, target_k, status,     │
│  step_count, fetch_count, tokens_spent, report_path,   │
│  trace_path, created_at                                │
└──────────────┬──────────────────────────┬──────────────┘
               │ 1:N (CASCADE)            │ 1:N (CASCADE)
               ▼                          ▼
┌──────────────────────────────┐ ┌───────────────────────────────────────┐
│        TrackerArticle        │ │          TrackerDevelopment           │
│  id, run_id, url, title,     │ │  id, run_id, rank, title, company,    │
│  status, byte_size,          │ │  primary_url, supporting_sources,     │
│  fetch_time_ms, error_msg,   │ │  location, compensation, snippet,     │
│  created_at                  │ │  recrawl_status, fingerprint          │
└──────────────────────────────┘ └───────────────────────────────────────┘
```

| Table Name | Column Name | Data Type | Constraints / Attributes | Description |
| :--- | :--- | :--- | :--- | :--- |
| `tracker_runs` | `id` | `INTEGER` | `PRIMARY KEY`, Auto-increment | Unique execution run identifier |
| | `user_id` | `INTEGER` | `FOREIGN KEY(users.id)`, `CASCADE` | User account that executed the crawl |
| | `run_number` | `INTEGER` | `NOT NULL` | Sequential run index (Run 1, Run 2, etc.) |
| | `topic` | `VARCHAR(255)`| `NOT NULL` | Configured tracking objective |
| | `target_k` | `INTEGER` | `NOT NULL`, Default 10 | Target number of top positions |
| | `status` | `VARCHAR(50)` | `NOT NULL` | `complete`, `partial`, or `error` |
| | `step_count` | `INTEGER` | `NOT NULL` | Agent reasoning steps taken |
| | `fetch_count`| `INTEGER` | `NOT NULL` | HTML articles fetched |
| | `tokens_spent`| `INTEGER` | `NOT NULL` | Total LLM tokens consumed |
| | `report_path`| `VARCHAR(255)`| Nullable | Path to generated markdown report |
| | `trace_path` | `VARCHAR(255)`| Nullable | Path to generated JSON trace log |
| `tracker_articles`| `id` | `INTEGER` | `PRIMARY KEY`, Auto-increment | Unique article audit record identifier |
| | `run_id` | `INTEGER` | `FOREIGN KEY(tracker_runs.id)`, `CASCADE` | Run during which article was fetched |
| | `url` | `TEXT` | `NOT NULL` | Target URL requested |
| | `title` | `VARCHAR(255)`| Nullable | Page title extracted from HTML `<title>` |
| | `status` | `VARCHAR(50)` | `NOT NULL` | `fetched`, `rejected`, or `error` |
| | `byte_size` | `INTEGER` | `NOT NULL` | Response byte count (capped at 1MB) |
| | `fetch_time_ms`| `INTEGER` | `NOT NULL` | Network request latency in milliseconds |
| | `error_message`| `TEXT` | Nullable | Reason for guardrail rejection or timeout |
| `tracker_developments`| `id` | `INTEGER` | `PRIMARY KEY`, Auto-increment | Unique ranked job posting identifier |
| | `run_id` | `INTEGER` | `FOREIGN KEY(tracker_runs.id)`, `CASCADE` | Run in which role was synthesized |
| | `rank` | `INTEGER` | `NOT NULL` | Position in Top K ranking (1 to 10) |
| | `title` | `VARCHAR(255)`| `NOT NULL` | Standardized job role title |
| | `company` | `VARCHAR(255)`| `NOT NULL` | Standardized corporate employer name |
| | `primary_url` | `TEXT` | `NOT NULL` | Verified corporate application portal link |
| | `supporting_sources`| `TEXT` | Nullable | Secondary and aggregator URLs (JSON array) |
| | `location` | `VARCHAR(255)`| Nullable | Location / Remote status |
| | `compensation`| `VARCHAR(255)`| Nullable | Disclosed salary range |
| | `qualifications_summary`| `TEXT`| Nullable | Summary of technical qualifications |
| | `recrawl_status`| `VARCHAR(50)`| `NOT NULL` | `New since last run`, `Still in top K`, `Dropped` |
| | `fingerprint` | `VARCHAR(255)`| Nullable | Deterministic slug fingerprint |

---

## 7. Full-Stack API Endpoints Specification

Protected endpoints require header: `Authorization: Bearer <token>`.

| Method | Path | Auth Required | Status Code | Purpose |
| :--- | :--- | :---: | :---: | :--- |
| `GET` | `/healthz` | No | `200` | Health check, returns `{"status": "ok"}` |
| `POST` | `/api/auth/register` | No | `201` | Creates account with bcrypt hash (12 rounds) |
| `POST` | `/api/auth/login` | No | `200` | Authenticates credentials, returns signed JWT token |
| `GET` | `/api/auth/me` | Yes | `200` | Returns profile of current authenticated user |
| `GET` | `/api/users/:id` | Yes | `200` | Read profile (Rule 3: 403 on cross-user attempt) |
| `PATCH`| `/api/users/:id` | Yes | `200` | Update user email or password (Rule 3: 403) |
| `DELETE`| `/api/users/:id` | Yes | `200` | Delete user account (Cascades to all tracker data) |
| `GET` | `/api/tracker/runs` | Yes | `200` | List tracker runs with developments and fetch logs |
| `POST` | `/api/tracker/runs` | Yes | `201` | Ingest completed tracker run payload into database |
| `POST` | `/api/tracker/trigger`| Yes | `202` | Trigger autonomous tracker execution asynchronously |
| `GET` | `/api/tracker/history` | Yes | `200` | Summary telemetry of user's historical crawl activity |
| `DELETE`| `/api/tracker/runs` | Yes | `200` | Reset / wipe all tracker runs for authenticated user |

---

## 8. Security Guardrails & Architectural Guarantees

1. **SSRF Guardrail & Hop-by-Hop Redirect Inspection:**
   - Pre-resolves domain hostnames via `socket.getaddrinfo()`.
   - Rejects loopback (`127.0.0.0/8`), RFC 1918 private subnets (`10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`), and AWS/GCP/Azure link-local metadata addresses (`169.254.0.0/16`).
   - Disables automatic client redirects (`follow_redirects=False`) and manually inspects `Location` headers at each hop, validating the new destination before following.
2. **Zero-Trust Plain Text Rendering (Stored-XSS Neutralization):**
   - The React frontend strictly renders all job titles, company names, and scraped summaries as pure text nodes (`<span>{job.title}</span>`, `document.createTextNode`).
   - Completely bans `dangerouslySetInnerHTML`, converting `<script>` tags into inert text entities (`&lt;script&gt;`).
3. **Multi-Tenant Authorization (Rule 3 Compliance):**
   - All tracker runs, developments, and audit logs are strictly scoped to `current_user.id` extracted from the verified JWT Bearer token.
4. **Algorithmic Circuit Breakers & Resource Budgets:**
   - Enforces `max_steps <= 15`, `max_fetches <= 12`, `token_budget <= 100,000`, 10s request timeout, and 1MB size limit.
   - Distinguishes transient 429 rate limits (exponential backoff with jitter) from terminal daily quota exhaustion (fail-fast termination with 0 retries).

---

## 9. Verification & Automated Test Suites

### 1. Run Automated 4-Pillar Tracker Verification
Verifies SSRF attacks, bogus API key handling, budget exhaustion partial reporting, and two-run recrawl differentiation:
```bash
python scripts/test_tracker.py
```
*Expected output: `ALL PILLARS VERIFIED SUCCESSFULLY [PASS] ✓`*

### 2. Run Complete Unit & Integration Test Suite (64 Tests)
```bash
python -m unittest discover tests -v
```
*Runs all 64 unit tests covering configuration, SSRF guardrails, search tools, LLM retry backoffs, agent state machine, recrawl memory, backend routes, and frontend views.*

---

## 10. Submission Deliverables Summary

- **Agent Evaluation Report**: [`AGENT.md`](AGENT.md) (Answering all 5 required system questions)
- **Run 1 Report**: [`reports/run1.md`](reports/run1.md)
- **Run 1 Trace Log**: [`reports/run1_trace.json`](reports/run1_trace.json)
- **Run 2 Report**: [`reports/run2.md`](reports/run2.md)
- **Run 2 Trace Log**: [`reports/run2_trace.json`](reports/run2_trace.json)
- **Persistent State File**: [`reports/tracker_state.json`](reports/tracker_state.json)
- **Policy Configuration**: [`config.yaml`](config.yaml)
- **Environment Template**: [`.env.example`](.env.example)
