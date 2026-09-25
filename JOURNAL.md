# Assignment 1 Journal: Foundations and Fundamentals

**Course:** CSCI-GA.2630 · Foundations of Networks and Mobile Systems (Fall 2026)  
**Student:** Shiyu Zhang  
**Project:** Decoupled Full-Stack Architecture & Security Bedrock  
**Date:** September 2026  

---

### 1. Architectural Philosophy & Tech Stack Decisions
In engineering the foundation for my personal command center, I anchored every design choice around the "holy trinity" of system architecture: **Security, Speed, and Reliability**.

- **Backend (Python 3.13 + FastAPI + Uvicorn):** Rather than defaulting to an Express.js runtime, I chose FastAPI. The primary architectural driver was forward-compatibility: Assignment 1B mandates an agentic loop implemented natively in Python (`python -m tracker.tools ...`). Choosing FastAPI ensures a unified Python runtime across backend APIs and future agent services, eliminating the performance and maintenance penalties of a multi-language microservice bridge. FastAPI also brings high-throughput asynchronous ASGI performance, compile-time type verification via Pydantic, and automatic OpenAPI contract generation.
- **Database & Persistence (Neon Serverless PostgreSQL + SQLAlchemy 2.0):** User account entities have clear relational invariants (unique IDs, unique emails, strict timestamps, and deterministic cascades upon deletion). PostgreSQL provides ACID guarantees and structured schema enforcement that document stores cannot match for identity management. I selected Neon over Render and Supabase because free-tier Render instances are destroyed after 30 days and Supabase projects pause after 7 days of inactivity; Neon provides persistent serverless scaling without risking grading outages.
- **Frontend (React 19 + Vite + Tailwind CSS):** A decoupled Single-Page Application (SPA) running on Vite offers sub-second Hot Module Replacement (HMR) and lightweight static bundles. Tailwind CSS enables a disciplined, utility-first UI design system that produces a clean, responsive interface without bloated stylesheet cascades.

---

### 2. Deep-Dive into Key Architectural Trade-Offs

#### A. Rule 3 Authorization: The HTTP 403 vs. HTTP 404 Decision
The specification mandated choosing between `HTTP 403 Forbidden` and `HTTP 404 Not Found` when a caller attempts to access, update, or delete another user's account (`:id != current_user.id`), and maintaining strict consistency across `GET`, `PATCH`, and `DELETE`.

**I deliberately selected `HTTP 403 Forbidden`.**  
- *Semantics & Standards Compliance:* Under RFC 9110 §15.5.4, `403 Forbidden` indicates that the server understands the client's identity (the JWT is valid and authenticated), but refuses authorization based on insufficient permissions. In contrast, `404 Not Found` (RFC 9110 §15.5.5) asserts that the target resource was not found.
- *Observability vs. Enumeration:* While `404` is occasionally utilized in public multitenant systems to prevent user enumeration (hiding whether a specific user ID exists), in an authenticated command-center API, semantic truth and auditability take precedence. Emitting `403` enables security monitoring systems to cleanly distinguish between benign routing errors (`404`) and malicious cross-tenant privilege escalation attempts (`403`). By implementing this check before querying the target record, the system guarantees consistent, fail-fast protection with identical latency characteristics regardless of whether the target ID exists in the database.

#### B. Cryptographic Hashing: bcrypt with 12 Rounds
Rather than delegating authentication to a black-box third-party provider (e.g., Clerk or Auth0), I authored the authentication engine directly using standard `bcrypt` with an adaptive work factor of 12 rounds:
- Unlike fast cryptographic hashes (SHA-256 or MD5), which can be brute-forced at billions of hashes per second using modern GPUs, bcrypt is a slow, memory-hard key derivation function based on the Blowfish cipher.
- A cost factor of 12 requires $2^{12} = 4,096$ iterations, benchmarking to approximately 250–300ms on modern server hardware. This creates a computational barrier that makes offline dictionary and rainbow-table attacks economically infeasible, while remaining low enough to prevent CPU exhaustion denial-of-service under normal user login loads. Each hash generates a cryptographically secure 128-bit salt, and password verification is executed in constant time to thwart timing side-channel attacks.

#### C. Cross-Origin Networking (CORS) & Token Transport: Bearer Tokens vs. Cookies
Running the frontend on `http://localhost:5173` and backend on `http://localhost:8000` accurately reproduces cloud microservice architectures (e.g., Vercel client communicating with a Render/AWS API). This separation highlighted the intricacies of the HTTP preflight handshake:
- Any non-simple cross-origin request (such as requests sending `Content-Type: application/json` or an `Authorization` header) triggers an automated browser preflight: an HTTP `OPTIONS` request querying `Access-Control-Allow-Methods`, `Access-Control-Allow-Headers`, and `Access-Control-Allow-Origin`.
- I chose **HTTP Bearer Tokens** stored in memory and synchronized via local storage over cookies. Cross-origin cookies encounter complex modern browser barriers regarding `SameSite=None; Secure` requirements and cross-site tracking mitigations. Furthermore, cookie-based sessions expose APIs to Cross-Site Request Forgery (CSRF). By utilizing explicit Bearer tokens in HTTP headers, every cross-origin request requires deliberate client action, neutralizing CSRF vectors by design and maintaining fully stateless RESTful endpoints.

---

### 3. Engineering Challenges & Problem Resolution
1. **Serverless Database Connection Idling:** Cloud serverless PostgreSQL instances (like Neon) aggressively terminate idle TCP sockets during inactivity. Initially, subsequent API calls after idle periods threw `psycopg.OperationalError: SSL connection has been closed unexpectedly`. I resolved this by configuring SQLAlchemy's engine with `pool_pre_ping=True` and a 300-second connection recycle interval. This issues a lightweight `SELECT 1` ping before executing queries, transparently rebuilding dead connections without surfacing 500 errors to clients.
2. **Preventing Accidental Password Hash Leakage (Rule 1):** To eliminate the risk of ever returning `hashed_password` in HTTP responses—even in development or error stacks—I established a strict boundary between database entities (`models.User`) and API schemas (`schemas.UserResponse`). FastAPI's Pydantic response filtering acts as an immutable physical firewall: because `hashed_password` is absent from the schema definition, the serializer cannot emit it into JSON under any circumstance.
3. **Automated Seed Convergence:** To satisfy the grading requirement for account `NYUgrader` / `Courant2026!` without requiring manual seed scripts, I leveraged FastAPI's asynchronous `lifespan` context manager. On startup, the server inspects the database and idempotently provisions the account if absent, guaranteeing zero-friction evaluation on clean environments.

---

### 4. What I Learned & Reflections
Building this foundational system shifted my perspective from "vibe coding"—gluing disparate libraries together without understanding their internals—to **intentional systems architecture**. I gained a hands-on appreciation for how network protocols (HTTP preflight, CORS headers), cryptographic math (Blowfish cost curves), and database connection pooling intersect to create a secure, resilient application. This bedrock is clean, reliable, and rigorously tested, ready to serve as the command center for the autonomous agents we will build next week in Assignment 1B.
