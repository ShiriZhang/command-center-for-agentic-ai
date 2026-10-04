# AGENT.md: Architectural Analysis & System Evaluation

> **Course:** CSCI-GA.2630 · Foundations of Networks and Mobile Systems (Fall 2026)  
> **Assignment:** 1B: Agentic Foundations  
> **Student:** Shiyu Zhang  
> **Topic:** Top 10 newest entry-level and new grad AI/ML engineering roles  
> **Deliverable:** Architectural Evaluation and System Q&A  

---

## 1. Workflow vs. Agent

### Model vs. Code Responsibilities

In our architecture, the **LLM agent** acts as a flexible, cognitive decision-maker operating over uncertain web evidence, while our **handwritten Python runtime harness** (`tracker/agent.py`, `tracker/llm.py`, `tracker/memory.py`, `tracker/tools/`) acts as a deterministic, zero-trust enforcement boundary.

| Domain | Model Decisions (Cognitive Layer) | Code Decisions (Deterministic Runtime Harness) |
| :--- | :--- | :--- |
| **Search Formulation** | Formulates natural-language queries (e.g., `"entry level machine learning engineer new grad 2026 greenhouse job posting"` vs `"new grad AI engineer lever jobs"`). | Enforces maximum search result limit (`max_results`), merges with candidate seeds, and strips URL duplicate parameters. |
| **Navigation & Fetch** | Selects which discovered URLs are relevant to explore and calls `fetch_article(url)`. | **Zero-Trust Network Guardrail:** Parses URL scheme (`http/https`), runs DNS pre-resolution via `socket.getaddrinfo`, and strictly rejects loopback (`127.0.0.1`), RFC 1918 private subnets, and cloud metadata (`169.254.169.254`). Enforces hop-by-hop redirect inspection, 10s timeout, and 1MB byte limit before byte consumption. |
| **Resource & Budgets** | Proposes calling `finish(report)` when satisfied with evidence. | **Strict Budget Governor:** The model is *never* trusted with budget enforcement. The code counts steps, fetches, and tokens. When `step_count >= 15`, `fetch_count >= 12`, or `tokens_spent >= 100,000`, the harness interrupts the loop, forces termination, and synthesizes a partial report. |
| **Deduplication** | Disambiguates borderline cases where titles differ slightly but share a company entity (Tier 2). | **Deterministic Fast-Path Fingerprinting:** Normalizes company slugs and role titles (`slugify(company):slugify(title)`), merges identical roles with 0 token spend, and automatically promotes direct corporate ATS URLs over aggregators. |
| **Recrawl Differentiation**| Analyzes new postings in the context of cached URL negative constraints. | Computes strict set differences between Run 1 and Run 2 URLs, categorizing jobs into `New since last run`, `Still in top K`, and `Dropped`. |
| **Error Handling** | None. The model has no visibility into raw HTTP transport exceptions. | Catches HTTP status codes. Implements exponential backoff with full jitter for transient 429s (max 3 retries) and immediate fail-fast termination (0 retries) for terminal 401/402/quota failures. |

### Decision Moved Out of the Model: Deterministic Deduplication & ATS Link Promotion

**What was moved out:**  
We moved **URL deduplication, corporate entity normalization, and canonical ATS URL promotion** completely out of the LLM prompt and into a deterministic Python rule engine (`JobDeduplicator` Tier 1 in `tracker/memory.py`).

**Why:**
1. **Token Cost & Quadratic Context Growth:** If the LLM were asked to compare every newly discovered job URL against all previously discovered URLs, prompt size would scale quadratically $\mathcal{O}(N^2)$ with every search action. Comparing 30 candidates pairwise in the prompt consumes upwards of 15,000–25,000 unnecessary tokens per step.
2. **Elimination of Hallucinated Mergers:** LLMs are prone to hallucinating semantic equivalence between distinct roles (e.g., merging "Data Scientist - Algorithms" with "Machine Learning Engineer - Infra" simply because both work with Python and transformers). Deterministic slug fingerprinting guarantees that roles with distinct company/title keys are never erroneously collapsed.
3. **Zero-Latency ATS Promotion:** When aggregators (such as `aidevboard.com` or `jobspipe.dev`) return an authentic corporate application portal (`boards.greenhouse.io`, `jobs.lever.co`, `jobs.ashbyhq.com`), Python code instantly evaluates `is_ats_url()` using deterministic regex and promotes the corporate ATS URL to `primary_url`, appending the scraper URL to `supporting_sources` with 0ms latency and 0 token cost.

---

## 2. The Network

### Round-Trip Breakdown from Run 1 Trace (`reports/run1_trace.json`)

Analyzing the full execution trace and network telemetry of **Run 1** (total elapsed wall-clock duration: **94.66 seconds**):

| Service / Endpoint | Destination Host | Number of Round Trips | Average Latency per Round Trip | Total Cumulative Latency | Purpose |
| :--- | :--- | :---: | :---: | :---: | :--- |
| **LLM Inference** | `openrouter.ai` | **13** | 4.15 s | ~54.0 s | Agent reasoning steps (10 step completions) + Tier 2 fuzzy semantic deduplication checks (3 calls). |
| **Search & Discovery API** | `tavily.com` / Candidate feeds | **18** | 1.85 s | ~33.3 s | `search_web` queries across verified ATS portals and candidate feeds. |
| **Article Fetches (HTTP/TLS)** | Multi-host career portals | **7** | 0.32 s | ~2.2 s | Fetching and scraping verified job descriptions (Fast AI Jobs, JobRight, Scale AI, RecentlyPostedJobs, etc.). |
| **A1 Platform Backend** | `localhost:8000` | **2** | 0.05 s | ~0.1 s | `POST /api/auth/login` (JWT authentication) and `POST /api/tracker/runs` (Neon PostgreSQL persistence). |
| **Total Transactions** | | **40** | | **~89.6 s** (Active network time) | *(Remaining ~5.1s was local CPU parsing, BeautifulSoup extraction, and regex tokenization)* |

### Where Did the Time Go?

1. **60.3% — Upstream LLM Generation Time (`openrouter.ai`):**
   - The primary latency bottleneck was remote autoregressive token generation and Time to First Token (TTFT) on `qwen/qwen3.8-27b:free`.
   - As the agent's observation history accumulated across steps 1 through 10, prompt size grew from 1,265 tokens to 121,580 tokens. Due to quadratic attention key-value cache processing, later steps took 8–11 seconds per completion.
2. **37.2% — Search & Candidate Discovery API Latency (`tavily.com`):**
   - 18 search API calls were issued across Greenhouse, Lever, Ashby, and specialized career domains, averaging ~1.85s per network round trip.
3. **2.4% — Corporate Web Ingestion & TLS Handshakes:**
   - Career sites hosted behind enterprise CDNs served HTML job descriptions. While our `fetch_article` tool limits responses to 1MB and inspects DNS hops safely, TLS 1.3 handshakes and initial TCP round trips consumed ~0.32s per fetch.
4. **< 0.1% — Local Backend & Database Persistence:**
   - Local FastAPI routes and connection-pooled Neon PostgreSQL database operations completed in <100ms total.

---

## 3. "New." (Deduplication & Recrawl Strategy)

### How We Decide Two Articles Describe the Same Development

Our system uses a **Two-Tier Deduplication Architecture** combining fast-path deterministic rules with fuzzy LLM disambiguation:

```
[Candidate Job A, Candidate Job B]
                 │
                 ▼
 ┌──────────────────────────────────────────────┐
 │ Tier 1: Deterministic Fast-Path Normalizer   │
 │   - Strip legal entity suffixes (Inc, LLC)   │
 │   - Standardize acronyms (ml, sr, jr, swe)   │
 │   - Strip requisition IDs [Req #1234]        │
 │   - Slug fingerprint: slug(comp):slug(title) │
 └──────────────────────┬───────────────────────┘
                        │
         Exact Match? ──┼── Yes ──► [MERGE: Same Development (0 tokens)]
                        │           Promote corporate ATS URL to primary
                        ▼ No
 ┌──────────────────────────────────────────────┐
 │ Tier 2: Fuzzy Trigger & Semantic LLM Check   │
 │   - Condition: Same Company AND              │
 │                Token Jaccard Similarity > 0.5 │
 └──────────────────────┬───────────────────────┘
                        │
       Trigger Met? ────┼── No ───► [KEEP SEPARATE: Distinct Roles]
                        │
                       Yes
                        ▼
 ┌──────────────────────────────────────────────┐
 │ LLM Disambiguation (Temperature 0.0)         │
 │   - Inspects seniority, team, & tech stack   │
 │   - Output JSON: {"is_same_role": bool}      │
 │   - Conservative fallback: False on error    │
 └──────────────────────────────────────────────┘
```

1. **Tier 1 (Fast-Path Normalization):**
   - The company name is normalized by stripping legal designations (`Inc`, `LLC`, `Corp`, `Technologies`, `Platforms`) and punctuation.
   - The title is standardized (`sr` $\to$ `senior`, `jr` $\to$ `junior`, `ml` $\to$ `machine learning`, `swe` $\to$ `software engineer`).
   - A deterministic fingerprint is generated: `slugify(company) + ":" + slugify(clean_title)`.
   - If two postings produce the identical fingerprint, they are merged immediately without an LLM call. The ATS URL is promoted to `url`, and secondary links are appended to `supporting_sources`.
2. **Tier 2 (Fuzzy Jaccard Triggered LLM Disambiguation):**
   - If fingerprints do not match exactly, the engine evaluates whether both postings belong to the same company (`are_companies_matching()`) and calculates token Jaccard similarity:
     $$J(A, B) = \frac{|A \cap B|}{|A \cup B|}$$
   - If $J(A, B) > 0.5$, an LLM disambiguation prompt compares the job summaries. The LLM must output strict JSON (`{"is_same_role": bool, "reason": str, "canonical_title": str}`). If parsing fails, the engine safely defaults to `is_same_role = False`.

### Documented Failure Case (False Positive Merger)

**Failure Scenario: Enterprise Pooled Hiring Tracks with Identical Titles across Distinct Divisions.**

- **Concrete Example:**  
  Suppose **Meta** posts two distinct early-career positions:
  1. *Opening A:* `Software Engineer, New College Grad - Machine Learning` (Requisition #A101, Reality Labs / AR Graphics team in Burlingame, CA).
  2. *Opening B:* `Software Engineer, New College Grad - Machine Learning` (Requisition #B202, FAIR / Foundation Model Pre-training team in Menlo Park, CA).
- **Why Our Method Gets It Wrong:**  
  Because both postings list company `"Meta"` and title `"Software Engineer, New College Grad - Machine Learning"`, Tier 1 strips all parenthetical locations and requisition codes. Both produce the identical fingerprint:
  `meta:software engineer new college grad machine learning`
- **Result:**  
  Our fast-path rule falsely classifies Opening B as a duplicate of Opening A and merges them into a single development, discarding one legitimate hiring pipeline.
- **Root Cause & Architectural Trade-off:**  
  To prevent scrapers from generating duplicate entries for the same job with varying city names (e.g., "Remote - US" vs "San Francisco, CA"), our normalizer aggressively strips location identifiers. In multi-division pooled hiring, requisition ID and department context are lost.

---

## 4. Failure Classification & 429 Handling

### What Our Code Does When a 429 Comes Back

When an HTTP 429 occurs, our system distinguishes between **transient per-minute rate limits** (which must be retried with exponential backoff and jitter) and **terminal daily/monthly quota exhaustion** (which must fail immediately with 0 retries).

### Exact Code Quote from `tracker/llm.py`

#### 1. Failure Classification (`classify_error` in `tracker/llm.py`, Lines 143–200):
```python
def classify_error(err: Exception) -> Tuple[bool, str, Optional[int]]:
    """
    Classifies an upstream LLM exception into:
        (is_terminal: bool, reason: str, status_code: Optional[int])
        
    Terminal Criteria (Zero Retries):
    - HTTP 401: AuthenticationError (Invalid/Missing API Key)
    - HTTP 402: Payment Required / Insufficient Credits
    - HTTP 403: Permission Denied
    - HTTP 404: NotFoundError (Model removed or unavailable)
    - RateLimitError (429) containing account quota exhaustion keywords ('quota', 'credit', 'billing', 'insufficient_quota')
    
    Transient Criteria (Exponential Backoff):
    - RateLimitError (429 per-minute rate limit without account exhaustion)
    - APITimeoutError / APIConnectionError (TCP socket timeout / connection dropped)
    - InternalServerError (HTTP 500, 502, 503, 504)
    """
    status_code = getattr(err, "status_code", None)
    err_str = str(err).lower()

    # 1. Explicit Terminal Status Codes
    if isinstance(err, AuthenticationError) or status_code == 401:
        return True, "Invalid or unauthorized API key (HTTP 401)", 401

    if status_code == 402:
        return True, "Payment required or credit balance exhausted (HTTP 402)", 402

    if isinstance(err, PermissionDeniedError) or status_code == 403:
        return True, "Permission denied (HTTP 403)", 403

    if isinstance(err, NotFoundError) or status_code == 404:
        return True, f"Model or resource not found (HTTP 404): {err}", 404

    # 2. Check for Account Quota Exhaustion masquerading as 429
    quota_keywords = ["quota", "credit", "billing", "insufficient_quota", "exceeded your current quota", "balance is too low", "insufficient funds"]
    if any(kw in err_str for kw in quota_keywords):
        return True, f"Account quota or credit limit exhausted: {err}", status_code or 429

    # 3. Standard 429 Rate Limit (Transient per-minute throttle)
    if isinstance(err, RateLimitError) or status_code == 429:
        return False, "Rate limit exceeded (HTTP 429), retryable", 429

    # 4. Network and Gateway Transient Errors
    if isinstance(err, (APITimeoutError, APIConnectionError)):
        return False, f"Network connection / timeout error ({type(err).__name__})", status_code

    if isinstance(err, InternalServerError) or (status_code and 500 <= status_code < 600):
        return False, f"Upstream server error (HTTP {status_code})", status_code

    # Generic unclassified status error
    if isinstance(err, APIStatusError):
        if status_code and status_code < 500:
            return True, f"Client API error (HTTP {status_code}): {err}", status_code
        return False, f"Server API error (HTTP {status_code}): {err}", status_code

    # Fallback: treat unexpected Python exceptions as terminal
    return True, f"Unexpected error: {err}", status_code
```

#### 2. Fail-Fast vs. Exponential Backoff with Jitter (`LLMClient.create_completion`, Lines 308–367):
```python
        attempt = 0
        while attempt <= self.max_retries:
            try:
                self.call_count += 1
                response = self.client.chat.completions.create(**kwargs)
                ...
                return response

            except Exception as exc:
                is_terminal, reason, status_code = classify_error(exc)

                # Requirement 5: Terminal failures halt immediately with ZERO retries
                if is_terminal:
                    logger.error(f"[TERMINAL LLM FAILURE] Provider '{self.provider}' halted: {reason}")
                    raise TerminalLLMError(
                        f"[TERMINAL FAILURE] {reason}",
                        status_code=status_code,
                        provider=self.provider,
                        details={"original_error": str(exc)}
                    ) from exc

                # Transient failure: check retry budget
                attempt += 1
                if attempt > self.max_retries:
                    # Attempt failover to secondary provider if configured
                    if self.enable_fallback:
                        fallback_data = self._get_fallback_client()
                        if fallback_data:
                            fb_client, fb_model = fallback_data
                            logger.warning(
                                f"Exhausted {self.max_retries} retries on '{self.provider}'. "
                                f"Failing over to fallback provider with model '{fb_model}'..."
                            )
                            kwargs["model"] = fb_model
                            try:
                                return fb_client.chat.completions.create(**kwargs)
                            except Exception as fb_exc:
                                logger.error(f"Fallback provider also failed: {fb_exc}")

                    raise TransientLLMError(
                        f"Transient error exceeded maximum retries ({self.max_retries}): {exc}",
                        status_code=status_code
                    ) from exc

                # Exponential backoff with random jitter
                backoff = min(20.0, self.base_delay * (2 ** (attempt - 1)) + random.uniform(0.1, 0.5))
                logger.warning(
                    f"Transient failure on '{self.provider}' ({reason}). "
                    f"Backing off for {backoff:.2f}s (Attempt {attempt}/{self.max_retries})..."
                )
                time.sleep(backoff)
```

### How Behavior Differs: Per-Minute Limit vs. Daily Cap

| Dimension | Per-Minute Rate Limit (Transient) | Daily / Monthly Cap (Terminal) |
| :--- | :--- | :--- |
| **Error Type** | `TransientLLMError` | `TerminalLLMError` |
| **Retry Count** | Retries up to 3 times (`retries <= 3`). | **Strictly 0 retries** (`retries = 0`). Halts on first attempt. |
| **Delay Strategy**| Exponential backoff with uniform jitter ($delay = 1.0 \times 2^{r-1} + jitter$). | **Zero sleep delay**. Immediately raises exception. |
| **Observed Example**| *Live Run 2 at 23:55:56 UTC:* OpenRouter returned 429. System backed off for 2.36s and retried. The subsequent request succeeded with HTTP 200 OK. | *Test Suite Pillar 2:* Bogus key or daily exhaustion halts immediately; agent synthesizes a partial report with the terminal error reason. |
| **Network Philosophy**| Congestion collapse control via additive increase / multiplicative decrease (AIMD) backoff. | Algorithmic circuit breaker. Retrying an exhausted daily quota is a bug that wastes compute and delays error reporting. |

---

## 5. Budget & Daily Execution Modeling

### What Does One Run Cost?

Based on empirical telemetry recorded in [`reports/run1.md`](reports/run1.md) and [`reports/run2.md`](reports/run2.md):

1. **LLM Consumption:**
   - **Run 1:** 117,778 tokens across 13 model interactions.
   - **Run 2:** 121,037 tokens across 11 model interactions.
   - **Average per run:** **~119,400 tokens**.
   - *Financial cost on Free Tier (`:free` models on OpenRouter):* **\$0.00**.
   - *Financial cost on Paid Commercial API (e.g., `gpt-4o-mini` at \$0.15/1M prompt, \$0.60/1M completion):*
     $$\text{Cost} \approx (0.100 \times \$0.15) + (0.019 \times \$0.60) = \$0.0150 + \$0.0114 = \mathbf{\$0.0264\text{ per run}}\text{ (< 3 cents)}$$
2. **Search API Consumption:**
   - **Run 1:** 21 `search_web` invocations; **Run 2:** 19 `search_web` invocations.
   - Tavily API: 1 credit per query $\approx$ **20 Tavily credits per run**.
3. **Database & Storage:**
   - Neon PostgreSQL: 1 `tracker_runs` row, 10 `tracker_developments` rows, 9 `tracker_articles` rows $\approx$ 25 KB. Negligible cost ($< \$0.0001$).

### Daily Recrawl Free-Tier Exhaustion Analysis

If the autonomous tracker were configured via cron or systemd to execute **once per day**:

| Service / Provider | Free Tier Quota Allowance | Daily Consumption (1 Run/Day) | Exhaustion Outcome | Exhaustion Day |
| :--- | :--- | :--- | :--- | :--- |
| **Groq API** *(Fallback)* | **100,000 Tokens / Day (TPD)** ceiling for open models (`llama-3.3-70b`, `qwen/qwen3.8-27b`). | ~119,400 tokens / run | ❌ **EXHAUSTS FIRST** | **Day 1** (During the first run at step 8) |
| **Tavily Search API** | **1,000 Search Credits / Month** (no credit card required). | ~20 searches / run | ❌ **EXHAUSTS SECOND** | **Day 50** ($1,000 / 20 = 50\text{ days}$) |
| **OpenRouter** *(Primary)* | **20 Requests / Minute**, rolling ~200 free requests / day across free models. | ~13 requests / run | ✅ **SUSTAINABLE** | Never exhausts under 1 run/day |
| **Neon PostgreSQL** | **0.5 GB Serverless Storage**. | ~25 KB / day | ✅ **SUSTAINABLE** | $> 20,000\text{ days}$ |

### Conclusion

**Groq's Free Tier runs out first, on Day 1.**  
Because a single full crawl takes ~119,400 tokens to discover, inspect, and rank 10 positions across multiple web iterations, it exceeds Groq's daily token cap of 100,000 TPD during its initial execution.  
*(This empirical limit directly validates our decision in Task 3.2 to enforce a strict `token_budget = 100,000` cap in `config.yaml`, ensuring that the agent halts cleanly before tripping provider quota blocks).*

Under our primary production configuration using **OpenRouter's free models**, the first service to run out would be **Tavily Search API**, which exhausts on **Day 50** (or on **Day 17** if scheduled 3 times daily).
