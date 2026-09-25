# Design: Assignment 1 Architecture & Security Blueprint

## Context
See `proposal.md` for overall motivation. The system consists of a decoupled frontend and backend running on separate origins (Frontend at `http://localhost:5173` and Backend at `http://localhost:8000`), accurately modeling real-world distributed web architecture and cross-origin security challenges.

## Goals / Non-Goals

**Goals:**
- Provide robust, RESTful authentication and user management APIs.
- Enforce the 3 core security invariants (No password hash leakage, 401 on bad credentials, 403 on cross-user access).
- Guarantee data persistence across server restarts using SQLAlchemy ORM (compatible with Neon PostgreSQL and local SQLite).
- Deliver 4 polished, responsive frontend screens (Register, Login, Home, Account) styled with Tailwind CSS.
- Automatically seed the grading user (`NYUgrader` / `Courant2026!`) on startup.

**Non-Goals:**
- Web scraping, Agent loops, or AI tracker capabilities (strictly deferred to A2 / Assignment 1B).
- Complex multi-tenant role hierarchies (standard single-user ownership model suffices for A1).

## Decisions

### Decision 1: Python FastAPI for Backend
- **Choice**: Python 3.13 + FastAPI + Uvicorn.
- **Rationale**: Assignment 2 explicitly mandates Python for the agent loop (`python -m tracker.tools ...`). Building the A1 backend in FastAPI ensures complete code harmony when integrating the agent endpoints in A2. Additionally, FastAPI provides built-in Pydantic validation and automatic OpenAPI documentation.
- **Alternative Considered**: Express.js (Node.js). Rejected because it would introduce a dual-language runtime penalty when building A2's Python tracker next week.

### Decision 2: SQLAlchemy ORM with Dual-Engine Compatibility
- **Choice**: SQLAlchemy 2.0 with PostgreSQL driver (`psycopg2-binary`) and local SQLite fallback.
- **Rationale**: Meets the requirement that "Data survives a service restart". Using SQLAlchemy decouples business logic from SQL dialect specifics. `pool_pre_ping=True` prevents connection drops on serverless cloud databases (e.g., Neon).
- **Alternative Considered**: Raw SQL. Rejected due to vulnerability to SQL injection and lack of portable schema migration.

### Decision 3: Password Hashing with bcrypt (12 Rounds)
- **Choice**: Direct `bcrypt` library with random salt generation.
- **Rationale**: Rubric requires `argon2id`, `scrypt`, or `bcrypt`. bcrypt is an adaptive slow-hashing algorithm that resists GPU-accelerated brute-force and rainbow table attacks.
- **Alternative Considered**: SHA-256 / MD5. Rejected because fast cryptographic hashes are unsafe for password storage.

### Decision 4: Cross-User Access Returns Consistent HTTP 403 Forbidden
- **Choice**: Return `HTTP 403 Forbidden` consistently across `GET`, `PATCH`, and `DELETE` on `/api/users/:id` when `:id` does not match the token's authenticated user ID.
- **Rationale**: RFC 9110 specifies 403 when the server understands the client's identity but refuses authorization. Consistent status codes prevent grader script test failures.
- **Alternative Considered**: HTTP 404 Not Found. While 404 obscures user existence (preventing user enumeration), 403 is semantically accurate for permission refusal in internal API contracts.

### Decision 5: Separation of Database Model and Pydantic Schema
- **Choice**: Define `User` in `models.py` with `hashed_password`, but define `UserResponse` in `schemas.py` excluding all password attributes.
- **Rationale**: Enforces Rule 1 at the serialization boundary. FastAPI's Pydantic response filter ensures password hashes can never be returned in HTTP response JSON.

## Risks / Trade-offs

- **[CORS Preflight Blocking]** → Configured `CORSMiddleware` in FastAPI allowing credentials, headers, and explicit origins (`http://localhost:5173`).
- **[Secret Leakage in Git]** → Placed strict `.gitignore` blocking `.env` files; provided safe `.env.example`.
- **[Cloud DB Idling & Deletion]** → Recommended Neon over Render (free Render Postgres deleted in 30 days; free Supabase pauses in 7 days). Local SQLite supported out-of-the-box.
