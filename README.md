# FNMS Assignment 1: Foundations and Fundamentals

> **CSCI-GA.2630 · Foundations of Networks and Mobile Systems (Fall 2026)**  
> **Student:** Shiyu Zhang  
> **Repository:** Full-Stack Foundations & Command Center for Agentic AI

---

## 1. What It Is
This project is a secure, decoupled full-stack platform providing robust authentication, authorization, and account management. It serves as the foundational command center ("the bedrock") for future agentic tools and vertical trackers developed in Assignment 1B.

---

## 2. Prerequisites
- **Python**: `3.11+` (Developed and verified on `Python 3.13.9`)
- **Node.js**: `20+` (Developed and verified on `Node.js v22.18.0`, `npm 10.9.3`)
- **Git**

---

## 3. Quick Start (Exact Copy-Pasteable Commands)

### Step 1: Start the Backend Server (Port 8000)
Open a terminal in the project root:

```bash
cd backend
python -m venv .venv

# On Windows (PowerShell):
.\.venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

# On macOS / Linux:
# source .venv/bin/activate
# pip install -r requirements.txt
# uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```
*The backend API will be live at `http://localhost:8000` with interactive Swagger docs at `http://localhost:8000/docs`.*

---

### Step 2: Start the Frontend Application (Port 5173)
Open a second terminal in the project root:

```bash
cd frontend
npm install
npm run dev
```
*The frontend user interface will be live at `http://localhost:5173`.*

---

## 4. Environment Configuration (.env)

As permitted by the Assignment 1 specification:
> *"Database credentials are the one exception to 'no secrets.' Create a throwaway database for this assignment and include its connection string so we can run your app."*

The repository includes a ready-to-run `backend/.env` connecting to a dedicated course throwaway database hosted on **Neon Serverless PostgreSQL**.

A sanitized template is also provided at [`backend/.env.example`](backend/.env.example):

```ini
# Neon Cloud PostgreSQL Connection String (Throwaway database for course grading)
DATABASE_URL=postgresql://neondb_owner:npg_fpFyclhiC0D9@ep-broad-bird-b4p2idis-pooler.c-6.us-east-2.aws.neon.tech/neondb?sslmode=require&channel_binding=require

# JWT Token Signing Secret (HMAC-SHA256)
JWT_SECRET=fnms-course-super-secret-key-change-in-production-2026
JWT_ALGORITHM=HS256
JWT_ACCESS_TOKEN_EXPIRE_MINUTES=120

# Network Settings
PORT=8000
HOST=0.0.0.0
```

---

## 5. Anything Weird / Startup Automation
- **Zero manual database migrations required**: Upon server launch, the FastAPI `lifespan` handler automatically creates all required tables (`users`) in the connected database.
- **Automatic Seed User**: The required grading account is automatically seeded into the database on startup:
  - **Username**: `NYUgrader`
  - **Password**: `Courant2026!`
  - *(An "Auto Fill" button is also provided on the login page for instantaneous grading convenience.)*

---

## 6. API Endpoints Specification

Protected endpoints require the HTTP request header: `Authorization: Bearer <token>`.

| Method | Path | Auth | Status Code | Purpose |
| :--- | :--- | :---: | :---: | :--- |
| `GET` | `/healthz` | No | `200` | Public health check, returns `{"status": "ok"}` |
| `POST` | `/api/auth/register` | No | `201` | Creates account with bcrypt slow hash (12 rounds) |
| `POST` | `/api/auth/login` | No | `200` | Authenticates credentials, returns signed JWT token |
| `GET` | `/api/auth/me` | Yes | `200` | Returns current logged-in user profile |
| `GET` | `/api/users/:id` | Yes | `200` | Read user profile (Enforces Rule 3: 403 on cross-user) |
| `PATCH` | `/api/users/:id` | Yes | `200` | Update user email or password (Enforces Rule 3: 403) |
| `DELETE` | `/api/users/:id` | Yes | `200` | Delete user account (Enforces Rule 3: 403) |

---

## 7. Compliance with the Three Strict Security Rules

1. **Rule 1: Never Return a Password Hash**
   - Implemented via Pydantic response filtering (`UserResponse`). The `hashed_password` attribute is strictly omitted from the serialization schema, physically preventing password hash leakage across all endpoints, error payloads, and development logs.
2. **Rule 2: Missing, Bad, or Expired Token → HTTP 401 (Not 200, Not 500)**
   - Enforced by `get_current_user` in `backend/app/auth.py`. Any missing header, malformed token, invalid signature, or expired timestamp reliably raises `HTTP 401 Unauthorized` with `WWW-Authenticate: Bearer`.
3. **Rule 3: Cross-User Account Protection → Consistent HTTP 403 Forbidden**
   - On `GET`, `PATCH`, and `DELETE` at `/api/users/:id`, if `:id != current_user.id`, the backend consistently refuses with `HTTP 403 Forbidden`.

---

## 8. Verification & Automated Test Suites

You can execute the automated test suites using the pre-configured scripts:

### A. Run Automated Grading Test Suite (Simulating Grader Script)
```bash
cd backend
.\.venv\Scripts\python test_api.py
```
*Tests all endpoints, tests NYUgrader, verifies Rule 1 recursive JSON sanitize, verifies Rule 2 (401 on missing/bad/expired), and verifies Rule 3 (403 refusal consistency across GET/PATCH/DELETE).*

### B. Run End-to-End Live Socket & CORS Test
```bash
# From project root:
.\backend\.venv\Scripts\python scripts/test_e2e.py
```
*Spawns a live Uvicorn socket on port 8000, tests real browser CORS preflight (OPTIONS) from Origin `http://localhost:5173`, and verifies the complete frontend production build bundle.*
